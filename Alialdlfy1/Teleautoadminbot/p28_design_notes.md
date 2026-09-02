
## Implementation design (final)

### 1. BloggerDatabase (modules/blogger/database.py) — additions only, JSON-compatible
- `_slots_state_key = "_daily_slots"`. State: {"day": str, "sections": {section: {"fixed": {"10:00": fp|None, ...}, "candidates": {"10:00": fp|None, ...}, "published": {"10:00": fp|None, ...}, "source_ids": {fp: source_id}}}} — stored inside stats dict like _schedule.
- New methods (add after get_schedule_state): `get_slots_state()`, `save_slots_state(state)`. Minimal; uses the same lock pattern.

### 2. scheduler.py — changes
- Keep existing generic schedule (9–23:30, 29 slots) for all sections EXCEPT: for sections declaring `slots` config override → use those slots instead. Jobs section channel has section="وظائف" (jobs). Section config lives in `sections` table (get_all_sections returns {id: {name, labels, ...}}). Add optional per-section override: sections[name]["publish_slots"] = list of "HH:MM". Jobs → ["10:00","14:00","18:00","22:00"]. Generic default: no override → existing behavior (29 slots, FIFO). This satisfies "must generalize to any future section automatically".
- In `_process_queue`: build per-section slot list. For sections with override slots: use slots-state machine:
  - Load state for day; reset on new day.
  - For each section with slots: compute "remaining slot keys" = slots whose time has passed (for missed ones: treat latest missed? requirement: slot 10:00 if unpublished → "عالجه/جهزه لأنه متأخر" = process ASAP as first remaining). Define slot order; "available for publish now" = earliest slot whose fixed time <= now+grace AND not published; if multiple slots passed, only the FIRST passed processes now (one per cycle per section), rest are handled in later cycles — this matches "لا تجهز 4 وظائف إذا لم تكن Slots متبقية" and restart semantics: after restart, process remaining slots one at a time at their fixed times; missed slots are processed immediately (as first remaining).
  - Candidate selection for a section: newest = queued articles of that section sorted by created_at DESC (or message id — store source_message_id on article at enqueue? scheduler fetch sets channel_id+section; newest = latest message id in source URL https://t.me/c/x/{id} extract id). Use URL message id for "أحدث" (requirement: أحدث وظيفة جديدة — the newest Telegram message).
  - Candidate stays pending until slot time. At slot time: pick newest candidate → run Section-Scoped Dedup (bot_core.is_hybrid_news_duplicate with scope_id=section scope) → if dedup pass → fix slot: mark slot published (update article status published, pop from queue, daily count, slot state), mark fingerprints consumed; if dedup fail → drop candidate (it's stale/dup) and try next newest in same cycle? Requirement: "إذا لم تعد صالحة، اختر أحدث Candidate مناسب بديل" — yes, try alternatives until good or none → slot stays empty for this cycle? Slots are fixed times; processing happens at/after slot time; if no valid candidate, slot remains empty permanently (req 6, 18).
  - One article cannot occupy two slots: fingerprint recorded in slots state per section; also article status changes to published so get_articles_by_status("queued") excludes it.
- Drain cap (req 15/16): in `_process_gemini_pending`, for sections with slot override: only process pending items up to max(unfixed slots today, 0) for that section — prevents burning AI when few slots left. Existing behavior preserved for non-override sections.
- Keep PROGRESSIVE_DRAIN_BATCH for non-slotted sections; for slotted, drain cap applies in addition.
- Restart/idempotency: state persisted in DB; on boot, _cycle resumes with saved state; slots-state reset only on new day.

### 3. bot_core integration (dedup at slot fix)
- Import in scheduler: `from bot_core import is_hybrid_news_duplicate, section_scope_for_channel` — bot_core.py imports modules (circular risk: bot_core imports modules.blogger.ui, ui imports scheduler? check: bot_core line 26: `from modules.blogger.ui import register_blogger_handlers, ...`; ui.py likely imports scheduler/processor). Import inside function (lazy) to avoid circular: inside `_process_queue` helper.
- scope_id for a section: use bot_core's `section_scope_for_channel(cid)` with ANY channel of that section (pick one). Or define local helper using channels[section]. Simplest: compute from scheduler's channels map: channels with same section → first channel id → section_scope_for_channel(cid).
- Dedup call: `is_hybrid_news_duplicate(text, cleaned=..., scope_id=..., url=...)` — reuse as before (P27 uses same signature in publish_source_message).

### 4. Titles (req 11)
- Add per-section title guidance in prompts.py: extend SYSTEM_REWRITE's "إذا المحتوى عن وظيفة" line with stronger instruction: vary title structure per job, reflect actual details (job title, entity, location, experience, qualifications), no fixed template, no invented info, Arabic job titles. Keep Gemini generation same pipeline; round-robin key unchanged.

### 5. What stays untouched
- _fetch_new_posts, is_published/fingerprint dedup in ingest (still runs; slots dedup adds second gate at fix time, harmless), ui, publisher, blogger_client, gemini, config, ai_manager, bot_core, main database.py.

### Test harness: run_p28_scenarios.py
Mock BloggerDatabase via monkeypatching or real temp file; mock processor gemini pipeline (track AI calls/keys used) and publisher (captures posts with time labels). Scenarios S1–S11 per requirements + restart test + AI rotation count test.

## PROGRESS TRACKER (update as I go)

DONE:
1. database.py: added DAILY_SLOTS_KEY + get_slots_state/save_slots_state (lines ~279-298). ✓
2. prompts.py: SYSTEM_REWRITE title-varied guidance for jobs added. ✓
3. scheduler.py constants added: P28_SECTION_FIXED_SLOTS (وظائف 10/14/18/22), P28_SLOT_GRACE_MIN=30. ✓
4. scheduler.py: _get_section_fixed_slots + _p28_remaining_slot_keys helpers. ✓
5. scheduler.py: _process_gemini_pending(channels) now has drain cap for slotted sections (limit=1 when slotted sections have remaining slots; per-section cap inside loop via section_pending_counts). ✓

TODO:
6. scheduler.py _process_queue(channels): integrate slots per section. Plan: existing generic slots logic stays for non-slotted sections. For sections in P28_SECTION_FIXED_SLOTS: use slots-state machine (load get_slots_state, reset on new day, _p28_remaining_slot_keys, pick newest queued article of section by source URL message id, optional dedup gate via bot_core.is_hybrid_news_duplicate lazy import, publish at/after slot time, mark fixed+published in state, daily count, pop from queue).
7. Also preserve existing daily_limit check; publish ONE article per cycle total (same as now) — slot pick among sections chooses earliest publishable slot across slotted sections, falling back to generic queue otherwise.
8. bot_core.py must NOT be changed (P27 dedup reused; check import works).
9. Write run_p28_scenarios.py: mock DB via temp blogger_data.json file (tempfile), mock processor (_process_next_pending returns fake article using source URL msg id for title), mock publisher (capture), mock time via freezegun or manual datetime patch. Scenarios:
   S1 full day jobs: 4 jobs → published at 10/14/18/22 order; S2 2 jobs → 2 slots published, rest slots stay empty forever; S3 restart mid-day → state resumes; S4 dup rejected at slot fix; S5 newest candidate selection; S6 dedup candidate drop + next candidate tried; S7 future slots not published early; S8 generic sections unaffected (news 29-slot queue still FIFO); S9 key rotation untouched (AI call count); S10 daily limit respected; S11 slot empty permanently when no candidate.
10. Run p28 harness, p20 133-unit suite against p28 copies, py_compile both files + blogger modules.
11. Final report Arabic A-F style + deliver folder.

Files: /home/ubuntu/p28/{bot_core.py,database.py,modules/...}, /home/ubuntu/p28/p28_design_notes.md. Test run dirs used previously: /home/ubuntu/p27 (133 suite passed 133/133). p20 dir has tests/.

## STATUS UPDATE (post-implementation)

DONE (implementation complete, all py_compile OK):
- database.py: get_slots_state/save_slots_state (DAILY_SLOTS_KEY "_daily_slots" in stats).
- prompts.py: title-varied guidance.
- scheduler.py: P28 constants; _get_section_fixed_slots; _p28_remaining_slot_keys (sentinel "_locked" excluded from used); _process_gemini_pending(channels) drain cap (limit=1 when any slotted section has remaining slots, + per-section stop in loop); _process_queue now calls _process_slots first, falls through to generic FIFO; _process_slots (lock→candidate pick newest by t.me msg id → dedup gate via bot_core.is_hybrid_news_duplicate lazy + section_scope_for_channel → publish → state fixed/candidates/published → daily count; empty slots marked "" permanently); _slot_candidates excludes claimed; "_locked" = cycle claim not a used slot.
- Empty-slot sentinel fixed to "" (falsy, not reconsidered).
- bot_core section_scope_for_channel at line 4172, is_hybrid_news_duplicate at 1652 (scope_id kwarg) — verified exist.

REMAINING:
1. Write run_p28_scenarios.py (harness with temp BloggerDatabase file, mocked processor/publisher, time via datetime patch). Scenarios S1-S11 (see earlier TODO).
2. Run harness → fix issues.
3. Run p20 133-unit suite against /home/ubuntu/p28 copies: cd /home/ubuntu/p28 && python3 -m unittest discover tests (tests dir copied from p20 earlier in p27).
4. Py-compile main bot_core.py/database.py.
5. Deliver: report (Arabic A-F: S1 root need = what was implemented), files (bot_core.py, database.py unchanged? NO — only blogger modules changed: modules/blogger/{scheduler,database,processor,prompts}.py! bot_core.py and main database.py UNCHANGED in p28). NOTE: deliverables are the 4 blogger module files + report + harness.
6. Check protected logic: ui.py publisher.py config.py ai_manager.py gemini.py blogger_client.py unchanged.

## HARNESS DEBUG STATE (run_p28_scenarios.py at /home/ubuntu/run_p28_scenarios.py)

Harness runs against /home/ubuntu/p28. BloggerDatabase uses BLOGGER_DB_PATH env var (real code line ~line 8: `DB_FILE = os.environ.get("BLOGGER_DB_PATH", ...)`) — GOOD.

REAL API signatures confirmed:
- save_channel(channel_id, channel_data) / get_all_channels returns list of channel dicts
- add_section(section_id, section_data) / get_all_sections returns {id: {name, labels, ...}}
- add_to_gemini_pending(raw_text, source_url, media, fingerprint, channel_id, section) — stores "raw_text" key
- get_gemini_pending_queue() / save_gemini_pending_queue(q) / remove_pending_by_fingerprint(fp)
- get_stats() → data["stats"] (daily: {date:{section:count}})
- increment_daily_count(section) works
- get_article(fp) / save_article(fp, article) / update_article_status / get_articles_by_status(status)
- is_published(fp)

CURRENT HARNESS ISSUES (from last run):
1. "processed == 10 not 4": seed_pending's enrichment loop overwrites ALL pending entries in DB each add_to_gemini_pending call — but worse: add_to_gemini_pending re-adds entries because harness uses source_text enrichment + fingerprint already there — Actually real issue: `_process_next_pending` in MockProcessor has signature mismatch error "missing 1 required positional argument 'db'" for test_s13 → process_all_pending(db) calls _process_next_pending(db, publisher) OK but test_s13 ERROR; the 10 count issue: seed_pending loops q and sets created_at for ALL entries then save; fine. REAL CAUSE of 10: process_all_pending keeps running: after 4 jobs processed, pending empty → returns False → stops. But test got processed=10 → means add_to_gemini_pending was called multiple times per seed item? seed_pending: add then enrichment. Hmm but pending queue showed 10 items. Cause: seed_pending enrichment: for each raw, after add, enriches; but add_to_gemini_pending dedup check `any(p.get("fingerprint")==fingerprint)` → OK no dup. WAIT: 10 = 4 jobs + 6 from test_s13? No, isolated tests... unless setUp doesn't reset DB properly — BLOGGER_DB_PATH is per-test tempfile, OK. 10 = 4 + ... ? Actually run order: process_all_pending processed 10 means pending had 10 entries when called. seed_pending called with 4 items... but add_to_gemini_pending appends. enrichment save_gemini_pending_queue saves q (4). Next add: dedup finds existing → return early (NO append). Then enrichment: q = get (4) → updates all 4 → save. Fine. So where do 10 come from?? Answer: test_s13 runs first alphabetically? No, S13 after. Wait: "10 != 4" is the FIRST processed assertion in test_s1. seed_pending 4 items → but add_to_gemini_pending called 10 times?? NO.
   TRUE ROOT: seed_pending's enrichment loop does `p["created_at"] = raw.get("created_at", len(q))` — fine. BUT `_pending_pop`/`remove_pending_by_fingerprint` — not the issue.
   Hmm, reconsider: processed=10 means while loop ran 10 times. After each process, pending re-queried. If pending never empties... but pop removes. Unless MockProcessor.process_all_pending in test_s1: `_process_next_pending` returns True always except empty → if db.get_gemini_pending_queue empty returns False. 10 iterations = pending started with 10?
   SUSPECT: add_to_gemini_pending dedup uses `fingerprint and any(...)` — fingerprint is truthy ✓. BUT seed_pending enrichment re-saves: next call to add_to_gemini_pending for same fp → dedup sees it → returns. So 4 items. UNLESS the enrichment `save_gemini_pending_queue(q)` is followed by... no.
   NEXT SUSPECT: maybe tests share state because os.environ["BLOGGER_DB_PATH"] set in setUp but new_db() called FIRST which reads env at import time? BloggerDatabase.__init__ uses module-level DB_FILE — set at import, NOT re-read per instance! The env var change in setUp has NO effect on BloggerDatabase in p28 (module already imported). All tests use SAME file /home/ubuntu/p28/data/blogger_data.json!! That's the leak: tests run alphabetically? unittest order may vary. test_s13 seeds 6 pending before S1 (test order by name: s10,s11,s12,s13,s1,s2,...). S13 seeds 6 + later S7/S8 add 1 each + S10 4 + S11/S12 adds... total pending at test_s1 run: 10 (6+4). Confirmed root cause: single shared DB file.
   FIX: patch DB_FILE in modules.blogger.database per test, or reload module. Best: before new_db(), set modules.blogger.database.DB_FILE = tempfile path and re-init. Do: `import modules.blogger.database as mbd; mbd.DB_FILE = tmpfile`.
2. test_s7/s8 ERROR: "جميع المتغيرات الأساسية مطلوبة" — bot_core import fails without required env vars? is_hybrid_news_duplicate is in bot_core which on import validates config/env. FIX: set needed env vars (TG_API_ID/TG_API_HASH/SESSION_STRING etc.) OR mock bot_core imports. Check bot_core top for required vars.
3. test_s10: titles set = 34 → because shared DB leaked articles from other tests (get_articles_by_status("queued") returned ALL queued articles across tests). Fixed by root cause fix.
4. test_s11: generic queue publish got 0 → _cycle: publisher.config.is_enabled mocked True but also _process_slots runs first: jobs has no candidates so returns False → falls through to generic queue; at 9:00 slot 0 (09:00) window = 9:00-9:30 → current_total_min 540 >= next_total_min 540 → not before, not past window → publishes... but got 0. Maybe scheduler._queue loaded in __init__ empty; test adds to self.sched._queue after → OK. _process_queue(channels) receives None? _cycle passes channels list? check _cycle: `await self._process_queue()` with no arg! _process_queue default channels=None → `channels = self.db.get_all_channels()` inside works. But _process_slots calls self.db.get_all_channels() too. Maybe issue: P28 test_s11 queue[0] is news article; article["section"]="أخبار"; _get_section_labels works. Hmm, but earlier tests also failed... after DB fix retest.
5. test_s9: 6 items not 5 — fixed already.
6. S9 also: 6 processed but pending queue? fine after DB fix.

PLAN: patch mbd.DB_FILE per test; set TG env vars for bot_core imports (check which vars: grep 'os.environ.get("TG' /home/ubuntu/p28/bot_core.py); then rerun.

## HARNESS vs REAL SCHEDULER GAP (discovered from logs)

Real _cycle order: fetch → _process_gemini_pending(channels) → _process_queue(channels).
Logs show: cycle runs but "new day X, reset schedule and daily slots" then "no valid candidate for وظائف slot 10:00" → meaning _process_slots picks from the GEMINI PENDING QUEUE (raw posts), not from queued articles. The slots publish raw→Gemini per slot. Harness MockProcessor processes ALL pending into "queued" articles first, then scheduler finds empty pending queue → no candidate → slots stay empty.

FIX for harness: seed pending items are picked directly by _process_slots; so the mock Gemini pipeline must be hooked into _process_slots' publish path. Simpler approach: make the MockProcessor.process hook be called by patching scheduler._process_gemini_pending or by replacing scheduler._pick_and_publish_for_slot. CLEANEST: patch BloggerScheduler._process_gemini_pending? No — real flow: for each slot, candidate picked from pending, Gemini processes it, publishes. The harness should let the real _process_slots drive; mock only the Gemini call (processor.process for one item) and publisher.

Approach: keep MockProcessor but change semantics: _process_next_pending(db) stays; in setUp, do NOT pre-process. Slots call processor pipeline inline. Need to know how scheduler invokes Gemini: check _process_slots code for the publish step (it likely calls processor.publish... or _process_single_pending). Read modules/blogger/scheduler.py around _process_slots publish region and grep "await self.processor" in scheduler.

Also note: "6 items in Gemini pending queue, processing batch of up to 5" → S13 drain-cap path works via _process_gemini_pending with limit 5 for news; fine.
Also _pending_pop not needed anymore if slots drive pending removal.

## CORRECT UNDERSTANDING OF IMPLEMENTED P28 (from reading _process_slots)

Slots publish from self._queue (articles queued/queued-by-ingest), NOT from gemini pending directly.
Flow: slot lock ("_locked") → candidate = newest queued article of section (_slot_candidates) not consumed by another slot today → dedup gate (_p28_candidate_valid: is_published + P27 section hybrid dedup) → fixed[slot]=fp → article from self._queue → make_article_html → publisher.publish_article → published[slot]=fp, daily count.
Grace: P28_SLOT_GRACE_MIN (missed slots publish first; future slot skipped if < time-grace).
One slot fixed per cycle (like generic queue fixes one per cycle).
Generic queue: still FIFO 30-min; _process_queue falls through when no slotted section publishable.
"new day reset schedule" happens at day change (state.day != today → reset, slots recomputed).
Drain cap: in _process_gemini_pending — limits processing per cycle; log "6 items pending, processing batch of up to 5" (news batch size 5?).

HARNESS REWRITE NEEDED:
- Slots take articles from scheduler._queue (seed "queued" articles into _queue + db save_article? _slot_candidates uses... need to check: candidates come from self._queue filtered by section + dedup validity). So: pre-create queued articles in db.save_article with status="queued" AND self.sched._queue.extend([...]).
- Skip harness pre-processing via MockProcessor entirely for slot tests; only MockProcessor needed for S9 (key rotation) and S10 (titles) — patch _process_next_pending usage in scheduler... or make MockProcessor process queued articles into ready articles? Simpler: keep MockProcessor for S9/S10 using real db pending queue, and for S1-S8/S12 pre-build queued articles.
- For S9/S10/S13: keep the _process_gemini_pending batch + _queue consumption path.
- Titles (S10): articles' title is whatever in the queued article; test can seed titles and vary them — or test processor title generation (make rewrite prompt). Real titles come from Gemini via processor; S10 can assert queued articles have distinct titles (provided by ingest) OR test prompts text directly.
- S11: generic queue test: news/sports queued articles, cycle at 9:00 publishes first (FIFO) ✓ (previous 0 = because at 9:00 no slotted section publishable AND _queue consumption works... got 0; maybe article section mismatch for labels/daily — retest with correct seeding).
- publisher.config mock still needed.
- _today_published_count: uses stats daily count — increment_daily_count("وظائف") etc.

## HARNESS REWRITE DONE — current state

Harness /home/ubuntu/run_p28_scenarios.py rewritten:
- seed_queued() added (fills self._queue + db.save_article, status=queued) — used by S1,S2,S4,S5,S6,S7,S8,S11,S12.
- S3 (no jobs), S7/S8 (dedup gate via bot_core remember_published_text+section_scope_for_channel), S9 (real scheduler._process_gemini_pending ×2 with patched AIManager, expect 6 keys round-robin), S10 (SYSTEM_REWRITE prompt contains "متنوع" + 4 queued articles distinct titles + contains real detail), S11 (news/sports FIFO via generic queue at 9:00), S12 (10:00 empty → 13:50 stays empty → 14:05 publishes /950), S13 (drain cap: after 10:00 fixed, only ≤3 AI calls, ≥3 pending remain).
- DB isolation fixed: new_db() patches mbd.DB_FILE per test; cleanup uses self.db._db_path.
- Config env vars set before import (API_ID=1000000 etc. — harness placeholders).
- pub.config.is_enabled() mocked True in setUp + new_scheduler restart paths.
- datetime patched via side_effect for non-patched attributes.

NEXT STEPS:
1. python3 run_p28_scenarios.py 2>/tmp/p28log.txt → check 13/13. Fix failures.
2. Run 133 unit suite: cp -r tests from p20 into /home/ubuntu/p28 (tests already in p27? check /home/ubuntu/p27/tests) then cd /home/ubuntu/p28 && python3 -m unittest discover tests → expect 133 PASS (or known baseline).
   NOTE: 133 suite runs against copies in p28 dir — bot_core.py/database.py at p28 root unchanged? (they must be copies from p27 baseline). Verify.
3. py_compile: p28/bot_core.py, p28/database.py, p28/modules/blogger/{scheduler,database,prompts,processor}.py.
4. Verify protected modules unchanged vs p27: modules/blogger/{publisher,config,ui,ai_manager,gemini,blogger_client}.py diff against p27.
5. Write report report_p28_jobs_slots.md (Arabic) covering: files modified, slot determination (P28_SECTION_FIXED_SLOTS 10:00/14:00/18:00/22:00 + sections.publish_slots override), newest-candidate selection (_slot_candidates by t.me msg id desc), single-slot-per-cycle lock, dedup gate at fix time, restart safety (slots state persisted stats._daily_slots), AI rotation untouched, titles prompt, drain cap, unaffected sections. Results.
6. Deliver: report + 4 modified blogger module files + harness. (bot_core.py and root database.py UNCHANGED — mention explicitly.)

## REAL AI ARCHITECTURE (not K1/K2/K3 round robin)

modules/blogger/ai_manager.py has AIKeyManager (not AIManager) with cooldown-based rotation:
- acquire_usable_key(): picks usable key per provider using _provider_index, offset-based next key (key_idx = (idx+1+offset) % len).
- switch_to_next_key(current_kid): on failure moves to next.
- record_success/record_failure(key_id, cooldown). No simple deterministic K1/K2/K3 log.
- ArticleProcessor uses self.gemini.acquire_session() → likely AIKeyManager.

CONSEQUENCE for S9: original harness expected round-robin K1..K3 with a MockProcessor that never matches reality. Since we rewrote S9 to drive the REAL scheduler._process_gemini_pending with patched "modules.blogger.processor.AIManager" (nonexistent) → AttributeError.
Better fix: S9 should test REAL key rotation semantics without network: patch the gemini chat function at modules.blogger.ai_manager level or patch AIKeyManager.acquire_usable_key to return rotating keys. Simplest reliable: patch AIKeyManager.acquire_usable_key with a fake returning (provider, kid, "KEY"+i) cycling; call scheduler._process_gemini_pending on 6 pending items; assert 6 distinct rotation calls / same order as acquire_usable_key cycling.

Also S10: get_articles_by_status("queued") works; mock AI the same way (patch AIKeyManager.acquire_usable_key).
