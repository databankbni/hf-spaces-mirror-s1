import asyncio
import time
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

# Keep an unpatched reference for converting persisted Unix timestamps. Tests
# patch the module-level datetime to simulate scheduler time.
REAL_DATETIME = datetime

from modules.blogger.database import BloggerDatabase
from modules.blogger.processor import ArticleProcessor

logger = logging.getLogger(__name__)

POLL_INTERVAL = 600
SCHEDULE_START_HOUR = 9
SCHEDULE_END_HOUR = 23
SCHEDULE_INTERVAL_MIN = 30
SLOTS_PER_DAY = ((SCHEDULE_END_HOUR - SCHEDULE_START_HOUR) * 60) // SCHEDULE_INTERVAL_MIN + 1

# Progressive AI draining: how many articles to recover from the Gemini pending queue per cycle.
PROGRESSIVE_DRAIN_BATCH = 5

# Default fixed-slot sections: these sections publish at explicit daily times
# ("HH:MM", 24h format) instead of the generic 30-minute queue slots.
# Any future section can be added here without touching the rest of the scheduler.
P28_SECTION_FIXED_SLOTS = {
    # Keep both configured names supported; production logs use "وظائف شاغره".
    "وظائف": ["10:00", "14:00", "18:00", "22:00"],
    "وظائف شاغره": ["10:00", "14:00", "18:00", "22:00"],
}
# A slotted section may publish one article per slot per cycle. The slot's fixed time
# plus this grace window is the moment it becomes publishable; missed slots are
# processed as soon as they are the earliest remaining slot (catch-up of the
# earliest missed slot only — no burst publishing).
P28_SLOT_GRACE_MIN = 30
# Version for the persisted fixed-slot state. Version 2 reopens empty slots
# written by the pre-fix logic, which compared minutes with Unix timestamps.
P28_SLOT_STATE_VERSION = 2


class BloggerScheduler:
    def __init__(self, db: BloggerDatabase, processor: ArticleProcessor, publisher):
        self.db = db
        self.processor = processor
        self.publisher = publisher
        self._running = False
        self._queue: List[Dict] = []

    async def start(self):
        self._running = True
        logger.info("BloggerScheduler: started")
        self._queue = self.db.get_articles_by_status("queued")
        logger.info(f"BloggerScheduler: loaded {len(self._queue)} queued articles from DB")
        if self._queue:
            logger.info(f"DB Load Sample Section: {self._queue[0].get('section', 'MISSING')}")
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.exception(f"BloggerScheduler: cycle error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self):
        self._running = False
        logger.info("BloggerScheduler: stopped")

    async def _cycle(self):
        logger.info("BloggerScheduler: cycle start")
        if not self.publisher.config.is_enabled():
            logger.info("BloggerScheduler: publisher disabled, skipping cycle")
            return
        channels = self.db.get_all_channels()
        if not channels:
            logger.info("BloggerScheduler: no channels configured, skipping cycle")
            return
        logger.info(f"BloggerScheduler: {len(channels)} channels, starting fetch")
        await self._fetch_new_posts(channels)
        logger.info("BloggerScheduler: fetch done")
        await self._process_gemini_pending(channels)
        await self._process_queue(channels)
        logger.info("BloggerScheduler: cycle end")

    async def _fetch_new_posts(self, channels: List[Dict]):
        from bot_core import user_client
        if not user_client:
            logger.warning("BloggerScheduler: user_client not available for polling")
            return
        for ch in channels:
            if not ch.get("enabled", True):
                logger.info(f"BloggerScheduler: channel {ch.get('channel_id')} disabled, skip")
                continue
            ch_id = ch.get("channel_id", "")
            if not ch_id:
                continue
            try:
                last_id = ch.get("last_message_id", 0)
                chat_identifier = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
                latest_id = last_id
                any_success = False
                logger.info(f"BloggerScheduler: polling channel {ch_id}, last_id={last_id}")

                # Drive the async generator manually so a single corrupted message
                # (e.g. Pyrogram failing to decode its entities) can be skipped
                # without losing the rest of the batch or blocking last_message_id.
                history_iter = user_client.get_chat_history(chat_identifier, limit=3).__aiter__()
                while True:
                    try:
                        msg = await history_iter.__anext__()
                    except StopAsyncIteration:
                        break
                    except UnicodeDecodeError as e:
                        logger.warning(
                            f"BloggerScheduler: skipping a message in {ch_id} — "
                            f"Pyrogram failed to decode it ({e}). Cannot recover its content; "
                            f"continuing with the rest of the batch."
                        )
                        continue
                    except Exception as e:
                        logger.warning(f"BloggerScheduler: error fetching next message in {ch_id}, skipping it: {e}")
                        continue

                    if msg.id <= last_id:
                        logger.info(f"BloggerScheduler: msg {msg.id} <= last_id {last_id}, break")
                        break
                    if msg.id > latest_id:
                        latest_id = msg.id
                    # Force str() to trigger any deferred UTF-16-LE decode NOW,
                    # so the error is caught here — not later in _fingerprint.
                    try:
                        tmp = msg.text or msg.caption or ""
                    except UnicodeDecodeError as e:
                        logger.warning(f"BloggerScheduler: msg {msg.id} text decode failed, skipping: {e}")
                        continue
                    try:
                        raw = str(tmp) if tmp else ""
                    except (UnicodeDecodeError, UnicodeEncodeError) as e:
                        logger.warning(f"BloggerScheduler: msg {msg.id} text conversion failed, skipping: {e}")
                        continue
                    if not raw.strip():
                        logger.info(f"BloggerScheduler: msg {msg.id} has no text, skip")
                        continue
                    fingerprint = self.processor._fingerprint(raw, str(msg.id))
                    if self.db.is_published(fingerprint):
                        logger.info(f"BloggerScheduler: msg {msg.id} already published, skip")
                        continue
                    article = self.db.get_article(fingerprint)
                    if article and article.get("status") in ("queued", "published"):
                        logger.info(f"BloggerScheduler: msg {msg.id} already queued/published, skip")
                        continue
                    media = []
                    if msg.photo:
                        try:
                            media.append({"type": "photo", "file_id": msg.photo.file_id})
                        except Exception as e:
                            logger.warning(f"BloggerScheduler: msg {msg.id} photo access failed, skipping media: {e}")
                        else:
                            logger.info(f"BloggerScheduler: msg {msg.id} has photo")
                    elif msg.video:
                        try:
                            media.append({"type": "video", "file_id": msg.video.file_id})
                        except Exception as e:
                            logger.warning(f"BloggerScheduler: msg {msg.id} video access failed, skipping media: {e}")
                        else:
                            logger.info(f"BloggerScheduler: msg {msg.id} has video")
                    chat_str = str(ch_id).replace('-100', '') if str(ch_id).lstrip('-').isdigit() else str(ch_id).lstrip('@')
                    source_url = f"https://t.me/c/{chat_str}/{msg.id}"
                    # Ingestion never calls Gemini directly: save straight to the pending
                    # queue so a Gemini cooldown/outage can never cause a message to be lost.
                    try:
                        fingerprint = self.processor.enqueue_raw_post(raw, source_url, media, channel_id=ch_id, section=ch.get("section", ""))
                    except Exception as e:
                        logger.warning(f"BloggerScheduler: msg {msg.id} enqueue failed, skipping: {e}")
                        continue
                    if fingerprint:
                        any_success = True
                        logger.info(f"BloggerScheduler: msg {msg.id} from {ch_id} saved to Gemini pending queue")
                    else:
                        logger.info(f"BloggerScheduler: msg {msg.id} from {ch_id} already known/duplicate, skip")
                # last_message_id only depends on messages being durably captured (saved to
                # pending or already known) — never on whether Gemini processing succeeded,
                # and it is always reached now even if a message in between failed to decode.
                if latest_id > last_id:
                    self.db.save_channel(ch_id, {**ch, "last_message_id": latest_id})
                    logger.info(f"BloggerScheduler: updated last_message_id to {latest_id} for {ch_id}")
            except Exception as e:
                logger.warning(f"BloggerScheduler: failed to poll channel {ch_id}: {e}")

    def _get_section_fixed_slots(self, section: str) -> Optional[List[str]]:
        """Fixed daily publish slots for a section, if any. Override order: sections
        table (per-section publish_slots) > P28_SECTION_FIXED_SLOTS default map.
        Sections without an override keep the generic 30-minute queue slots."""
        sections = self.db.get_all_sections()
        for sdata in sections.values():
            if sdata.get("name") == section:
                override = sdata.get("publish_slots")
                if override:
                    return list(override)
                break
        return list(P28_SECTION_FIXED_SLOTS.get(section, []))

    def _p28_remaining_slot_keys(self, state_sections: Dict, section: str, slots: List[str], now_min: int) -> List[str]:
        """Slot keys still unfixed for the section today, in schedule order.
        A slot becomes publishable when its fixed time (+ grace) has passed and it
        was not yet fixed/published (a truthy fingerprint). The "_locked" sentinel
        means a slot is claimed this cycle and is counted as consumed for today.
        Earlier missed slots come first so a missed 10:00 slot is handled
        immediately as the earliest remaining slot, while slots still in the
        future wait for their time."""
        sec = state_sections.get(section, {})
        # A slot is consumed for today once it appears in 'fixed' at all: a real
        # fingerprint means published, an empty string means fixed-empty forever,
        # and "_locked" means claimed mid-cycle (all three are used slots).
        fixed = {k for k, v in sec.get("fixed", {}).items() if v != "_locked"}
        remaining = []
        for key in slots:
            if key in fixed:
                continue
            hh, mm = (int(p) for p in key.split(":"))
            total = hh * 60 + mm
            # A missed slot (now past its fixed time) is catch-up publishable
            # immediately on the next cycle (per requirement 2); a future slot is
            # publishable exactly at its fixed time — never earlier (the timing
            # gate lives in _process_slots). All unfixed slots stay in the
            # remaining list: the scheduler picks the earliest one and either
            # publishes it (when due) or returns "not yet due".
            remaining.append(key)
        return remaining

    async def _process_gemini_pending(self, channels: List[Dict] = None):
        """Process Gemini pending queue (raw posts waiting for AI processing).
        Runs only when Gemini keys are available (cooldown check done by caller).
        Drains progressively in batches of PROGRESSIVE_DRAIN_BATCH so a large backlog
        never blocks one scheduler cycle — each success recovers one processed article.
        For sections that declared fixed daily slots, draining is additionally capped
        at the number of remaining unfixed slots today, so AI (and Gemini keys)
        is never spent preparing candidates that cannot be published."""
        pending = self.db.get_gemini_pending_queue()
        if not pending:
            logger.info("BloggerScheduler: Gemini pending queue is empty.")
            return
        max_batch = PROGRESSIVE_DRAIN_BATCH
        # Section-aware drain cap for slotted sections (see _process_queue for the
        # matching slot-side logic). Generic sections keep PROGRESSIVE_DRAIN_BATCH.
        now_now = datetime.now()
        today = now_now.date().strftime("%Y-%m-%d")
        now_min = now_now.hour * 60 + now_now.minute
        state = self.db.get_slots_state()
        # Per slotted section, no more pending candidates than unfixed slots
        # remaining today; the batch limit is the tightest such cap (>=1), so
        # AI/Gemini is never spent preparing candidates that cannot publish.
        section_cap_used = False
        section_remaining: Dict[str, int] = {}
        if state.get("day") == today:
            # Slots state already initialized for today: cap at the unfixed
            # slots still available (missed slots are included since they can
            # still catch up; fixed-empty slots are excluded).
            for section, slots in P28_SECTION_FIXED_SLOTS.items():
                remaining = self._p28_remaining_slot_keys(state.get("sections", {}), section, slots, now_min)
                if remaining:
                    section_remaining[section] = len(remaining)
                    logger.info(f"BloggerScheduler: section '{section}' has {len(remaining)} unfixed slots remaining today, "
                                f"pending drain for this section limited accordingly")
                    section_cap_used = True
        else:
            # First cycle of the day — slots state has not been reset yet (the
            # reset lives in _process_queue which runs after pending drain).
            # Conservatively cap at the full declared slot counts so a big
            # backlog can never spend more AI than the day can publish.
            # Only slotted sections that actually have pending items are capped;
            # sections without fixed slots keep the full batch limit.
            pending_sections = set(p.get("section", "") for p in pending)
            for section, slots in P28_SECTION_FIXED_SLOTS.items():
                if slots and section in pending_sections:
                    section_remaining[section] = len(slots)
                    section_cap_used = True
        if section_cap_used:
            limit = min(max_batch, max(1, min(section_remaining.values())))
        else:
            limit = max_batch
        logger.info(f"BloggerScheduler: {len(pending)} items in Gemini pending queue, processing batch of up to {limit}...")
        processed = 0
        # Seed the per-section counters with the candidates ALREADY queued in the
        # memory queue: a later drain invocation must see the coverage built by
        # earlier batches/cycles, otherwise the cap would over-spend by one.
        section_pending_counts: Dict[str, int] = {}
        for _a in self._queue:
            if _a.get("status") == "queued" and self._get_section_fixed_slots(_a.get("section", "")):
                section_pending_counts[_a.get("section", "")] = (
                    section_pending_counts.get(_a.get("section", ""), 0) + 1)

        def _section_max_allowed(section: str) -> int:
            if section in section_remaining:
                # Day-start fallback: cap at the full declared slot count
                # until the slots state gets initialized this cycle.
                return section_remaining[section]
            today_state = self.db.get_slots_state()
            if today_state.get("day") == today:
                slots_def = self._get_section_fixed_slots(section)
                remaining = self._p28_remaining_slot_keys(
                    today_state.get("sections", {}), section, slots_def, now_min)
                return len(remaining)
            slots_def = self._get_section_fixed_slots(section)
            return len(slots_def)

        def _cap_reached() -> bool:
            if not section_cap_used:
                return False
            for section in section_pending_counts:
                slots_def = self._get_section_fixed_slots(section)
                if not slots_def:
                    continue
                max_allowed = _section_max_allowed(section)
                queued_now = sum(1 for a in self._queue
                                 if a.get("section") == section and a.get("status") == "queued")
                if queued_now >= max(1, max_allowed):
                    return True
            return False

        while pending and processed < limit and not _cap_reached():
            # Slotted-section drain cap (pre-consume check): never spend AI
            # preparing a candidate once the memory queue already covers all
            # unfixed slots of that section for today.
            if _cap_reached():
                logger.info(f"BloggerScheduler: stop draining pending for sections with no unfixed slots today")
                break
            recovered = await self.processor._process_next_pending()
            if not recovered:
                break
            processed += 1
            recovered["status"] = "queued"
            ch_id = recovered.get("channel_id", "")
            if ch_id:
                ch = self.db.get_channel(ch_id)
                if ch:
                    section_name = ch.get("section", "")
                    recovered["section"] = section_name
                    recovered["labels"] = list(self._get_section_labels(section_name))
                    logger.info(f"Selected Section: {section_name}")
                    logger.info(f"Section Loaded From DB: {section_name}")
                    logger.info(f"Labels from section config: {recovered.get('labels', [])}")
                else:
                    recovered_section = recovered.get("section", "")
                    if recovered_section:
                        recovered["labels"] = list(self._get_section_labels(recovered_section))
                        logger.info(f"Channel {ch_id} not found, using pending section: {recovered_section}")
                    else:
                        logger.warning(f"Channel {ch_id} not found in DB, no section fallback")
            else:
                logger.warning(f"No channel_id on recovered article")
            logger.info(f"Section Before Queue: section={recovered.get('section', 'MISSING')}, labels={recovered.get('labels', [])}")
            self._queue.append(recovered)
            self.db.save_article(recovered["fingerprint"], recovered)
            section_pending_counts[recovered.get("section", "")] = section_pending_counts.get(recovered.get("section", ""), 0) + 1
            logger.info(f"BloggerScheduler: recovered article '{recovered.get('title', '')[:30]}' from pending queue")
            pending = self.db.get_gemini_pending_queue()

    async def _process_queue(self, channels: List[Dict] = None):
        if channels is None:
            channels = self.db.get_all_channels()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        current_total_min = now.hour * 60 + now.minute

        # Build all generic slots: 09:00, 09:30, 10:00, … 23:00 (29 slots)
        slots = []
        for hour in range(SCHEDULE_START_HOUR, SCHEDULE_END_HOUR):
            for minute in (0, 30):
                slots.append((hour, minute))
        slots.append((SCHEDULE_END_HOUR, 0))
        if not slots:
            return

        # Load persisted schedule state
        state = self.db.get_schedule_state()
        last_day = state.get("day", "")
        last_slot = state.get("last_slot", -1)

        # Reset for a new day
        if last_day != today:
            last_slot = -1
            state["day"] = today
            state["last_slot"] = -1
            self.db.save_schedule_state(state)
            # Daily slots state resets with the new day as well
            self.db.save_slots_state({"day": today, "version": P28_SLOT_STATE_VERSION, "sections": {}})
            logger.info(f"BloggerScheduler: new day {today}, reset schedule and daily slots")
        else:
            # One-time migration for today's state: the old implementation could
            # permanently mark a slot empty after comparing `created_at` (Unix
            # seconds) with slot minutes. Reopen only legacy empty entries; new
            # empty slots created by this version remain permanently empty today.
            slots_state = self.db.get_slots_state()
            if slots_state.get("version") != P28_SLOT_STATE_VERSION:
                reopened = 0
                for section_state in slots_state.get("sections", {}).values():
                    fixed = section_state.get("fixed", {})
                    for slot_key, value in list(fixed.items()):
                        if value == "":
                            del fixed[slot_key]
                            reopened += 1
                slots_state["version"] = P28_SLOT_STATE_VERSION
                self.db.save_slots_state(slots_state)
                if reopened:
                    logger.warning(
                        f"BloggerScheduler: reopened {reopened} legacy empty fixed slots "
                        f"for {today} after time-unit fix"
                    )

        # ---------- P28 fixed-slot sections ----------
        # Sections with declared fixed daily times pick their own article at slot time
        # (newest queued candidate of that section), independent of the generic queue.
        # If a slot is fixed/published this cycle, the cycle ends here (one publish
        # per cycle). If no slot could be published (not yet due / no candidate),
        # the cycle falls through to the generic 30-minute queue below.
        p28_result = await self._process_slots(now, today, current_total_min)
        if p28_result is not None:
            action, _reason = p28_result
            if action is True:
                return  # a fixed-slot section published this cycle
            # (False, ...) — nothing was published; continue with the generic queue.
        # Generic 30-minute FIFO. Articles of P28 slotted sections NEVER use this
        # path (they publish only via their fixed slots), so a late-arriving job
        # cannot leak through the generic queue and cannot starve news/sports.
        queue = [a for a in self._queue
                 if a.get("status") == "queued"
                 and a.get("section") not in P28_SECTION_FIXED_SLOTS]
        if not queue:
            return

        next_slot_idx = last_slot + 1
        if next_slot_idx >= len(slots):
            logger.info(f"BloggerScheduler: all {len(slots)} slots used today, carry over to tomorrow")
            return

        next_hour, next_min = slots[next_slot_idx]
        next_total_min = next_hour * 60 + next_min

        # Not time yet
        if current_total_min < next_total_min:
            logger.info(f"BloggerScheduler: next slot {next_hour:02d}:{next_min:02d}, current {now.hour:02d}:{now.minute:02d}, waiting")
            return

        # Past the slot window — skip it to prevent catch-up burst publishing
        slot_window_end = next_total_min + SCHEDULE_INTERVAL_MIN
        if current_total_min >= slot_window_end:
            logger.info(f"BloggerScheduler: slot {next_slot_idx} ({next_hour:02d}:{next_min:02d}) window already passed, skipping")
            state["last_slot"] = next_slot_idx
            self.db.save_schedule_state(state)
            return

        # Time to publish ONE article from the generic queue (sections without
        # fixed daily slots keep their existing 30-minute FIFO behavior)
        today_published = self._today_published_count()
        article = queue[0]

        ch_id = article.get("channel_id", "")
        ch_config = next((c for c in channels if c.get("channel_id") == ch_id), {}) or {}
        logger.info(f"Selected Article ID: {article.get('fingerprint', 'N/A')[:16]}")
        logger.info(f"Selected Section: {article.get('section', 'MISSING')}")
        logger.info(f"Selected Labels: {article.get('labels', 'MISSING')}")
        logger.info(f"Selected Hashtags: {article.get('hashtags', 'MISSING')}")
        logger.info(f"Article keys: {list(article.keys())}")

        # Resolve section on the article itself so it propagates to publisher, labels, daily count
        if not article.get("section"):
            article["section"] = ch_config.get("section", "")
            logger.info(f"Section was MISSING, resolved from channel to: {article['section']}")

        section = article["section"]
        section_today = today_published.get(section, 0)
        daily_limit = ch_config.get("daily_limit", 10)
        ready_queue_count = sum(1 for queued_article in self._queue
                                if queued_article.get("status") == "queued"
                                and queued_article.get("section") == section)
        self._log_daily_budget(section, daily_limit, section_today, ready_queue_count, "generic")
        decision = "SKIP - limit reached" if section_today >= daily_limit else "PUBLISH"
        logger.info(f"Decision: {decision}")
        logger.info("Before Daily Limit")
        if section_today >= daily_limit:
            logger.info(f"BloggerScheduler: daily limit {daily_limit} for section {section} reached, skipping article and scheduling next slot")
            state["last_slot"] = next_slot_idx
            self.db.save_schedule_state(state)
            return
        logger.info("After Daily Limit")

        logger.info("Before Publish")
        logger.info(f"BloggerScheduler: publishing article '{article.get('title', '')[:30]}' in slot {next_hour:02d}:{next_min:02d}")
        logger.info(f"Section Before Publisher: section={section}")
        logger.info(f"Article dict has labels: {article.get('labels', [])}")
        logger.info(f"Article dict has hashtags: {article.get('hashtags', 'MISSING')}")
        html = self.processor.make_article_html(article)
        labels = list(self._get_section_labels(section))
        logger.info(f"Labels Sent To Blogger: {labels}")
        blogger_article = {
            "title": article.get("title", "عنوان المقال"),
            "content": html,
            "labels": labels,
        }
        post_id = await self.publisher.publish_article(blogger_article, article.get("fingerprint"))
        logger.info("After Publish")
        if post_id:
            self.db.update_article_status(article["fingerprint"], "published", {
                "post_id": post_id,
                "published_at": int(time.time()),
            })
            self.db.increment_daily_count(section)
            article["status"] = "published"
            logger.info(f"BloggerScheduler: published '{article.get('title', '')[:30]}' (post_id={post_id})")
            logger.info("Before Queue Pop")
            self._queue = [a for a in self._queue if a.get("fingerprint") != article["fingerprint"]]
            logger.info("After Queue Pop: removed only after successful publish")

            # Mark this slot as used only after the successful publish.
            state["last_slot"] = next_slot_idx
            self.db.save_schedule_state(state)
            logger.info(f"BloggerScheduler: slot {next_slot_idx} used, next at slot {next_slot_idx + 1}")
        else:
            # Keep the article queued so the next cycle can retry it. Do not
            # consume the generic slot or increment the daily counter.
            self.db.update_article_status(article["fingerprint"], "queued", {
                "last_publish_failed_at": int(time.time()),
            })
            article["status"] = "queued"
            logger.warning(
                f"BloggerScheduler: failed to publish '{article.get('title', '')[:30]}'; "
                "article remains queued and the slot remains available"
            )

    async def _process_slots(self, now: datetime, today: str, current_total_min: int):
        """P28 fixed-slot publishing for sections that declared explicit daily times.
        Rules (per requirement):
        - Each slot is fixed: candidate is prepared but only published at/after the
          slot's time (+grace); earlier missed slots publish first (no burst).
        - Candidate = newest queued article of the section (by Telegram message id).
        - Candidate is locked to the slot on first pick; if it later turns out to be
          a duplicate/invalid at fix time, the next newest candidate is tried.
        - An article can never occupy two slots (fingerprint recorded per section).
        - Slots with no remaining valid candidate stay empty permanently.
        Returns (True, reason) when a slot was fixed this cycle, (False, reason) when
        no slotted section had a publishable slot (caller falls through to the
        generic queue), or (None, None) when there was nothing to do at all."""
        state = self.db.get_slots_state()
        if state.get("day") != today:
            return (False, "new-day reset not yet applied")
        state_sections = state.setdefault("sections", {})

        channels = self.db.get_all_channels()
        # Sections that declare fixed slots and have at least one enabled channel
        slotted = {}
        for section, slots in P28_SECTION_FIXED_SLOTS.items():
            if not slots:
                continue
            has_channel = any(
                c.get("section") == section and c.get("enabled", True) and c.get("channel_id")
                for c in channels
            )
            if has_channel:
                slotted[section] = slots
        if not slotted:
            return (False, "no slotted sections with active channels")

        # Pick the earliest publishable slot across all slotted sections (missed
        # slots first, then future slots in time order). Only ONE slot is fixed per
        # cycle, exactly like the generic queue fixes one article per cycle.
        best = None  # (total_min, section, slot_key)
        for section, slots in slotted.items():
            for key in self._p28_remaining_slot_keys(state_sections, section, slots, current_total_min):
                hh, mm = (int(p) for p in key.split(":"))
                total = hh * 60 + mm
                if best is None or total < best[0]:
                    best = (total, section, key)
        if best is None:
            logger.info("BloggerScheduler: no remaining publishable slot for slotted sections today")
            return (False, "no remaining slots")
        total, section, slot_key = best
        # Publishing timing: a slot that has ALREADY PASSED (missed catch-up) may
        # publish immediately once a valid candidate exists. A FUTURE slot waits
        # for its exact fixed time (the candidate is prepared earlier but never
        # published ahead of the slot). Grace is never used to publish early —
        # it only softens the window for slots whose fixed time has passed.
        # Lock the slot immediately (prevents two concurrent cycles fixing it twice)
        sec_state = state_sections.setdefault(section, {"fixed": {}, "candidates": {}, "published": {}, "source_ids": {}})
        sec_state.setdefault("fixed", {})
        sec_state.setdefault("candidates", {})
        sec_state.setdefault("published", {})
        sec_state.setdefault("source_ids", {})

        if current_total_min < total:
            # Prepare-ahead rule: a future slot is prepared well before its fixed
            # time — the newest queued article of the section is locked to the slot
            # as its candidate now, stays a candidate (never published early), and
            # is verified at publish time. If a newer job arrives before the slot,
            # the candidate is refreshed to it.
            if sec_state.get("candidates", {}).get(slot_key):
                logger.info(f"BloggerScheduler: section '{section}' slot {slot_key} candidate already prepared, waiting for its time")
                return (False, f"slot {slot_key} not yet due (candidate prepared)")
            prepared = self._slot_candidates(section, sec_state)
            if prepared:
                sec_state["candidates"][slot_key] = prepared[0]
                self.db.save_slots_state({"day": today, "version": P28_SLOT_STATE_VERSION, "sections": state_sections})
                logger.info(f"BloggerScheduler: section '{section}' slot {slot_key} candidate {prepared[0][:16]} prepared in advance, will publish at its fixed time")
            else:
                logger.info(f"BloggerScheduler: section '{section}' slot {slot_key} not yet due, no queued article to prepare")
            return (False, f"slot {slot_key} not yet due")

        today_published = self._today_published_count()
        # Any section channel works to read the daily limit (limit is per channel but
        # sections share channels in our setup; take the first enabled one).
        ch_config = next((c for c in channels if c.get("section") == section
                          and c.get("enabled", True) and c.get("channel_id")), {})
        daily_limit = ch_config.get("daily_limit", 10)
        section_today = today_published.get(section, 0)
        ready_queue_count = sum(1 for queued_article in self._queue
                                if queued_article.get("status") == "queued"
                                and queued_article.get("section") == section)
        self._log_daily_budget(section, daily_limit, section_today, ready_queue_count, f"fixed:{slot_key}")
        if section_today >= daily_limit:
            logger.info(f"BloggerScheduler: daily limit {daily_limit} for section '{section}' reached, slot {slot_key} skipped for today")
            return (False, "daily limit reached")

        # "_locked" means a slot is claimed this cycle but not yet fixed to a
        # fingerprint; it is not counted as a used slot. Only real fingerprints
        # (candidates/published) occupy a slot permanently.
        # Choose/refresh the candidate: if one was prepared in advance for this
        # slot, keep it (refresh only if a newer queued article arrived); otherwise
        # pick the newest queued article of this section not already consumed by
        # another slot today, not published before.
        candidates = self._slot_candidates(section, sec_state)
        pre_locked = sec_state.get("candidates", {}).get(slot_key)
        # The prepared candidate was previously locked to this slot; keep it as
        # the first choice at due time (unless it disappeared from the queue or
        # a newer job arrived, in which case _slot_candidates already lists the
        # newer one first and the lock simply moves to it below).
        if pre_locked:
            queued_fps = [a.get("fingerprint") for a in self._queue if a.get("status") == "queued"]
            if pre_locked in queued_fps and pre_locked not in candidates:
                candidates = [pre_locked] + candidates
        # Missed-slot rule: if this slot's fixed time has already passed (missed
        # catch-up), only candidates that were queued BEFORE the slot's fixed time
        # may fill it. A job that arrived after the slot passed goes to the next
        # future slot; a missed slot with no pre-existing candidate stays empty.
        if candidates and current_total_min >= total:
            # `_slot_queue_time` returns `created_at` in Unix seconds. Convert
            # the fixed slot on today's local calendar day to the same unit;
            # never compare minutes-since-midnight with Unix timestamps.
            slot_dt = now.replace(
                hour=total // 60,
                minute=total % 60,
                second=0,
                microsecond=0,
            )
            allowed_before_ts = int(slot_dt.timestamp())
            candidates = [c for c in candidates
                          if self._slot_queue_time(c) < allowed_before_ts]
        fp = None
        while candidates:
            fp = candidates[0]
            if self._p28_candidate_valid(fp, section, today, state_sections):
                break
            logger.info(f"BloggerScheduler: candidate {fp[:16]} invalid/duplicate for slot {slot_key}, dropping it")
            candidates.pop(0)
        if not fp:
            # No valid candidate at all: the slot will never be fixed today. Mark
            # it explicitly empty so it is never reconsidered in later cycles.
            sec_state["fixed"][slot_key] = ""
            self.db.save_slots_state({"day": today, "version": P28_SLOT_STATE_VERSION, "sections": state_sections})
            logger.info(f"BloggerScheduler: no valid candidate for section '{section}' slot {slot_key} — slot stays empty permanently today")
            return (False, "no valid candidate")

        # Keep the candidate lock while rendering/publishing. The slot becomes
        # permanently fixed only after a successful publish.
        sec_state["candidates"][slot_key] = fp
        self.db.save_slots_state({"day": today, "version": P28_SLOT_STATE_VERSION, "sections": state_sections})

        article = next((a for a in self._queue if a.get("fingerprint") == fp), None)
        if not article:
            logger.warning(f"BloggerScheduler: slot {slot_key} candidate {fp[:16]} missing from memory queue, will retry next cycle")
            return (False, "candidate not in memory queue")

        # Resolve section/labels like the generic path does
        if not article.get("section"):
            article["section"] = ch_config.get("section", section)
        article.setdefault("labels", list(self._get_section_labels(article.get("section", section))))
        logger.info(f"P28 Slots: section='{section}' slot={slot_key} candidate={fp[:16]} title='{article.get('title', '')[:30]}'")

        html = self.processor.make_article_html(article)
        labels = list(self._get_section_labels(article.get("section", section)))
        blogger_article = {"title": article.get("title", "عنوان المقال"), "content": html, "labels": labels}
        post_id = await self.publisher.publish_article(blogger_article, fp)
        if post_id:
            self.db.update_article_status(fp, "published", {"post_id": post_id, "published_at": int(time.time())})
            self.db.increment_daily_count(section)
            sec_state["published"][slot_key] = fp
            sec_state["fixed"][slot_key] = fp
            self.db.save_slots_state({"day": today, "version": P28_SLOT_STATE_VERSION, "sections": state_sections})
            self._queue = [a for a in self._queue if a.get("fingerprint") != fp]
            logger.info(f"P28 Slots: section '{section}' slot {slot_key} published post_id={post_id}; removed from queue after success")
        else:
            self.db.update_article_status(fp, "queued", {"last_publish_failed_at": int(time.time())})
            logger.warning(
                f"P28 Slots: section '{section}' slot {slot_key} publish failed for {fp[:16]}; "
                "candidate remains queued and slot remains retryable"
            )
        return (True, "published" if post_id else "failed")

    def _slot_candidates(self, section: str, sec_state: Dict) -> List[str]:
        """Newest queued articles of the section (by Telegram message id in the
        source URL), excluding fingerprints already claimed by another slot today."""
        claimed = set()
        for keys in (sec_state.get("candidates", {}), sec_state.get("published", {}), sec_state.get("fixed", {})):
            claimed.update(v for v in keys.values() if v)
        queued = [a for a in self._queue
                  if a.get("status") == "queued" and a.get("section") == section
                  and a.get("fingerprint") not in claimed]
        queued.sort(key=lambda a: self._slot_message_id(a), reverse=True)
        return [a["fingerprint"] for a in queued]

    def _slot_queue_time(self, fp: str) -> int:
        """When the candidate arrived into the queue (enqueue time), used to
        decide whether a MISSED slot may still catch up with it: a missed slot
        only ever uses candidates that were already queued BEFORE the slot's
        fixed time; a job that arrives after its slot has passed goes to the
        nearest FUTURE unfixed slot and can never retro-fill an empty one."""
        article = self.db.get_article(fp) or {}
        return int(article.get("created_at") or 0)

    @staticmethod
    def _slot_message_id(article: Dict) -> int:
        """Newest = latest Telegram message id from the source URL; falls back to
        created_at so enqueue order still works when the URL has no message id."""
        url = article.get("source_url", "") or ""
        m = __import__("re").search(r"t\.me/c/[^/]+/(\d+)$", url)
        if m:
            return int(m.group(1))
        return article.get("created_at", 0) or 0

    def _p28_candidate_valid(self, fp: str, section: str, today: str, state_sections: Dict) -> bool:
        """Gate at slot fix time: published-IDs dedup still holds, plus the P27
        section-scoped hybrid dedup so the same news event cannot be republished
        under a newer message id. Import is lazy to keep modules import-safe."""
        if self.db.is_published(fp):
            return False
        try:
            from bot_core import is_hybrid_news_duplicate
            article = self.db.get_article(fp) or {}
            text = article.get("source_text", "")
            if text:
                # Lazy import of the scope helper; any failure degrades to ingest-only dedup.
                try:
                    from bot_core import section_scope_for_channel
                    cid = next((c.get("channel_id") for c in self.db.get_all_channels()
                                if c.get("section") == section and c.get("channel_id")), "")
                    scope_id = section_scope_for_channel(cid) if cid else ""
                except Exception:
                    scope_id = ""
                dup, why, best = is_hybrid_news_duplicate(text, scope_id=scope_id)
                if dup:
                    try:
                        _recent = self.db.get_recent_fingerprints(scope_id=scope_id) if scope_id else []
                    except Exception:
                        _recent = []
                    logger.info(f"P28 Slots: candidate {fp[:16]} rejected by section-scoped dedup (recent={[r.get('fp','') for r in _recent][-6:]}, why={why}, best={best})")
                    return False
        except Exception as e:
            logger.warning(f"P28 Slots: hybrid dedup gate unavailable ({e}), using ingest dedup only")
        return True

    def _can_publish_now(self, ch_config: Dict, current_hour: int, today_published: Dict) -> bool:
        if not ch_config.get("enabled", True):
            logger.info(f"BloggerScheduler: channel disabled")
            return False
        start_hour = ch_config.get("start_hour", 9)
        end_hour = ch_config.get("end_hour", 23)
        if current_hour < start_hour or current_hour >= end_hour:
            logger.info(f"BloggerScheduler: current hour {current_hour} outside window {start_hour}-{end_hour}")
            return False
        daily_limit = ch_config.get("daily_limit", 10)
        section = ch_config.get("section", "")
        section_count = today_published.get(section, 0)
        if section_count >= daily_limit:
            logger.info(f"BloggerScheduler: daily limit {daily_limit} reached for section {section}")
            return False
        return True

    def _today_published_count(self) -> Dict:
        """Return successful Blogger publishes for the current local calendar day.

        The article records are authoritative because they carry the successful
        publish timestamp. The legacy stats.daily counter remains for UI/history,
        but it is not used for admission decisions, avoiding stale or duplicated
        counter values after retries or restarts.
        """
        now = datetime.now()
        today = now.date()
        period_label = today.strftime("%Y-%m-%d")
        counts: Dict[str, int] = {}
        get_all_articles = getattr(self.db, "get_all_articles", None)
        if callable(get_all_articles):
            for article in get_all_articles():
                if article.get("status") != "published":
                    continue
                published_at = int(article.get("published_at") or 0)
                if not published_at:
                    continue
                if REAL_DATETIME.fromtimestamp(published_at).date() != today:
                    continue
                # Use the canonical section name from the article record
                section = article.get("section", "") or "general"
                counts[section] = counts.get(section, 0) + 1
            
            # Detailed logging of the counting process for auditability
            logger.info(
                f"BloggerScheduler: daily budget audit - method=published_article_records "
                f"period={period_label} total_found={sum(counts.values())} "
                f"breakdown={counts}"
            )
            return counts

        # Compatibility fallback for test doubles/older adapters without the
        # article-list API. Production BloggerDatabase has get_all_articles().
        stats = self.db.get_stats()
        daily = stats.get("daily", {})
        counts = dict(daily.get(period_label, {}))
        logger.info(
            "BloggerScheduler: daily budget count method=legacy_stats_daily "
            f"period=local_calendar_day:{period_label} counts={counts}"
        )
        return counts

    def _log_daily_budget(self, section: str, daily_limit: int, section_today: int,
                          ready_queue_count: int, context: str) -> None:
        remaining = max(0, int(daily_limit) - int(section_today))
        logger.info(
            f"BloggerScheduler: [DAILY BUDGET CHECK] "
            f"Section: {section!r} | "
            f"Context: {context} | "
            f"Method: Published Article Records | "
            f"Period: Local Calendar Day ({datetime.now().strftime('%Y-%m-%d')}) | "
            f"Counted: {section_today} | "
            f"Limit: {daily_limit} | "
            f"Remaining: {remaining} | "
            f"Queue Size: {ready_queue_count} | "
            f"Decision: {'PUBLISH' if remaining > 0 else 'STOP'}"
        )

    def _get_section_labels(self, section_name: str) -> list:
        sections = self.db.get_all_sections()
        for sdata in sections.values():
            if sdata.get("name") == section_name:
                labels = sdata.get("labels", [])
                if labels:
                    return list(labels)
                return [section_name]
        if section_name and section_name != "general":
            return [section_name]
        return []

    def add_to_queue(self, article: Dict):
        article["status"] = "queued"
        self._queue.append(article)
        self.db.save_article(article["fingerprint"], article)
        logger.info(f"BloggerScheduler: manually queued article '{article.get('title', '')[:30]}'")
