# P27 Design Notes — Shared Section Dedup

## Current state (bot_core.py @ 61ebef53, database.py @ dd0f8a41)

### Dedup existing layers (is_hybrid_news_duplicate, lines 1604-1653, TEXT only)
Order inside loop over recent[-300:] fingerprints:
1. exact (text_fp == fp)
2. event (event_fp == event_fp)
3. url (url_fp == url_fp)
4. similarity (SequenceMatcher >= 0.75, guarded by _event_details_differ numbers AND event_fp equality)
5. event_overlap (0.60-0.75 ratio + overlap>=0.70 + same event_fp) — but spec requires event_fp DIFFERENCE blocks duplicate; current code already requires stored_event_fp == event_fp for overlap → spec item 7 partially satisfied, BUT overlap returns dup even if details_differ was flagged only inside similar block. Spec 5 (number update like 5→8): `_event_details_differ` guards only similarity>=threshold block AND it compares numbers in normalized vs sample; 5 vs 8 differ → continue, so NOT duplicate. OK.

### Scoping problem (root of new task)
- recent_fingerprints is GLOBAL: all sources share one dedup pool. Spec wants DEDUP PER SECTION (channel/publishing-target): news/sports/jobs.
- claim_source_event is per source_id:message_id → protects same-message duplicate only. New requirement: cross-source same-event dedup per section with atomic claim per (section scope, fingerprint).

### Section concept in codebase
- NO section/category field exists. A "section" = the publishing channel (target). News/رياضة/وظائف = different Telegram publishing channels. Section = tuple of target channel_ids a source publishes to, or more robust: scope = the publishing channel itself.
- Simplest robust mapping: scope per event = frozenset of target_ids (from get_targets_for_source). A source targeting the news channel only scopes to that channel. Two sources publishing to the same channel share scope → cross-source dedup happens per channel naturally.
- Fingerprint storage must carry scope (target_ids set) and section label derived from channel names (auto: channel.title normalized). New scope auto-created = no code change needed for new sections.

### 48-hour window
- get_recent_fingerprints currently keeps 3 days (3*86400 = 72h). Change TTL to 48h (2*86400) in get_recent_fingerprints + add_recent_fingerprint cleanup. Also compare against ACCEPTED/PUBLISHED only: current pool includes rejected? remember_published_text is called only on success → pool contains accepted+published. Good; ensure rejected texts never get added (they don't; only any_success triggers remember_published_text). Note hybrid dedup compares against pool; pool = accepted. ✓
- Also remember_published_text must add scope field to fingerprint item.

### New atomic section claim (requirement 9/10)
- db.add_scope_claim(scope_id, fp) inside lock: returns True only once per (scope_id, fp) within 48h. scope_id = e.g. "ch_-1001210871112" (per publishing channel) → atomic under same db lock, TOCTOU safe.
- On publish success, claim is registered BEFORE or AFTER? Spec: first atomic claim wins and publishes; second rejected as duplicate. So claim must happen AT DECISION TIME inside is_hybrid check or right after deciding not-duplicate, under lock, together with fingerprint addition. Simplest: inside get_recent_fingerprints check path, once we decide not-duplicate, call add_scope_claim; if another process won, treat as duplicate. Since db lock is single lock, "check recent fp then add claim+fp" done inside same lock = atomic. Implement db.decide_section_fingerprint(scope_id, fp, sample, event_fp, url_fp, source_id, message_id) → ("new", None) or ("duplicate", reason).

### Blocked words early reject (requirement 11/12)
- Currently: clean_text (per-channel blocked words) runs inside loop AFTER dedup. Global blocked words (get_blocked_words) checked only inside clean_text via channel list; blocked_word_in_text (4089) exists but unused in publish flow.
- Fix: at publish_source_message entry, check RAW TEXT (pre full_clean_text) against get_blocked_words() + union of all channel blocked words → reject immediately with log "Blocked before processing: blocked_word", no AI/no dedup/no normalization. For channel-specific words: union is acceptable (reject if ANY channel would block) — early reject; channel-specific filtering still happens later too.

### Layer order per spec 6
Exact → URL → Event → Similarity → Event Overlap → AI gray zone if still gray.
Current code already does exact/url/event/similarity/overlap; but current order inside loop: exact → event → url → similarity → event_overlap. Spec wants URL before EVENT. Change order to: exact → url → event → similarity → event_overlap. (Functional difference: none for final verdict, but comply.)
- Gray-zone AI hook: add ai_decide_duplicate_if_configured(normalized, sample) — called only when 0.60-0.75 similarity + event_fp==same (gray). No existing AI dedup call found → this adds optional AI layer when AI keys exist and ai dedup setting on. Default off (no token consumption for ordinary flow). Mark as configurable.

### Log formats required
- "Duplicate detected: scope=NEWS reason=event" → implement via scope_label from channel title (auto) e.g. normalize Arabic title → label like NEWS? Better: label = channel id + name first word. Use channel title normalized to ascii-ish? Simple: scope label = channel name (arabic ok). Format: `🔁 Duplicate detected: scope=<channel-name> reason=<reason>` etc.
- "New event accepted: scope=SPORTS"
- "Blocked before processing: blocked_word"
- No secrets in logs.

### Files to modify
1. database.py: 
   - add_scope_claim / get_scope_claims / decide_section_fingerprint (lock-atomic) — new key "section_claims" dict {scope_id: [{fp, ts, ...}]}, TTL 48h.
   - get_recent_fingerprints TTL 72h→48h + filter by scope.
   - add_recent_fingerprint: add scope_id + section_label fields, cleanup by scope.
2. bot_core.py:
   - compute_scope_label + scope_ids_for_source (target_ids → section scope IDs; for cross-source dedup, scope = per-channel scope IDs; dedup check per each target scope).
   - is_hybrid_news_duplicate(signature) → use scope-qualified storage instead of global: accept optional scope_id param; comparison only against fingerprints with matching scope.
   - publish_source_message: raw blocked-word early reject before full_clean_text + before dedup + before claim.
   - remember_published_text: pass scope + section_label.
   - publish_source_album: same for text captions (smart duplicate → upgrade to hybrid with scope).
   - Logs with scope.
   - claim_source_event: extend? Keep as-is (source-level message claim); add section-level event claim via db.decide_section_fingerprint.
- DO NOT touch: UI, blogger, scheduler, media/album forwarding logic (only dedup call changes in album), short posts, source routing.

### Test harness (P27 scenarios A-M)
- Mirror p26 harness pattern: FakeMsg, mock Telegram network, import p27 copies of bot_core.py/database.py, run scenarios with real execution paths, count sends, check AI not called via mock counter.

### Notes
- AI gray-zone: only invoke if an AI key exists and setting enabled; else skip. Ensure no token usage for blocked posts (early reject happens before any AI) ✓.
- event_fp differing → NOT duplicate: similarity block already continues on event_fp mismatch; event_overlap block already requires equality → spec 7 satisfied (keep).
- Number change 5→8: _event_details_differ → continue → not duplicate ✓ (existing).

## IMPLEMENTATION PROGRESS (Phase 2)

### database.py DONE (new functions at ~line 1084-1166):
- DEDUP_WINDOW_SECONDS = 2*86400 (48h)
- get_recent_fingerprints(scope_id=None): 48h cutoff + optional scope filter
- add_recent_fingerprint(..., scope_id=None, section_label=None): stores scope+label
- claim_section_event(scope_id, event_fp): atomic under lock, 48h TTL, returns True if won
- is_section_event_claimed(scope_id, event_fp): read-only check

### bot_core.py DONE:
- check_global_blocked_words_raw(raw_text): raw-text blocked word check (global + union of all channel blocked words) → Early Reject
- section_scope_for_channel(cid) → f"ch_{cid}"; section_label_for_channel(cid); scopes_for_source(sid)
- _ai_decide_gray_zone(normalized, sample): called only in gray zone; requires ai_keys + setting "ai_gray_zone_dedup"; counters via globals _p27_ai_call_count
- is_hybrid_news_duplicate(..., scope_id=None): new layer order Exact→URL→Event→Similarity→EventOverlap→AI gray; scope-qualified recent fingerprints; event_fp mismatch blocks (details_differ)
- check_section_claim(scope_id, event_fp)
- publish_source_message: raw blocked-word early reject BEFORE full_clean_text (line ~4264); text-path dedup loop per target scope + claim; "New event accepted" log with scopes; remember_published_text per target with scope/label
- remember_published_text(text, source_id, message_id, scope_id, section_label)

### TODO next:
1. publish_source_album: apply same raw blocked-word early reject + scope dedup for text captions (currently is_smart_duplicate; upgrade to is_hybrid_news_duplicate with scope) — keep albums/media unchanged otherwise.
2. py_compile both files.
3. Build run_p27_scenarios.py harness (mirror p26 harness pattern in /home/ubuntu/run_p26_scenarios.py): FakeMsg, mock Telegram send/forward/get_chat etc., scenarios A-M:
   A same text 2 sources same section → 1 publish
   B same event different wording 2 sources → 1
   C same source twice → 1
   D same news 2 different channels/sections → both allowed (needs 2 channels)
   E sports-like news in NEWS section doesn't block SPORTS channel → need source→channel mapping: special_sources per channel
   F jobs-like news doesn't block jobs channel
   G number update 5→8 → NOT duplicate
   H same event different URL → Duplicate (url layer)
   I similarity high + event_fp different → NOT duplicate
   J race 2 sources same time → claim one wins
   K blocked word → reject before normalization/AI, AI counter = 0
   L media/albums/short posts behavior unchanged
   M >48h old news → not compared (seed old fingerprint with ts older than 48h)
4. Test: existing 133 unit tests (run via /home/ubuntu/run_p20_tests.py or unit suite — verify with p25 runner run_p25_scenarios.py, 4 tests) — NOTE copies in /home/ubuntu/p27/ now; run against p27 copies.
5. Deliver: modified bot_core.py + database.py copies, report answering 1-10 items.

### Key file paths:
- Working copies: /home/ubuntu/p27/{bot_core.py,database.py}
- Old proven harness: /home/ubuntu/run_p26_scenarios.py (7/7 pattern)
- Device mount: /mnt/desktop/بوت النشر التلقائي/ (MD5 61ebef53/dd0f8a41 baseline)
- Report template: /home/ubuntu/report_final_duplication.md (previous task)

## Failure analysis (first harness run)
- 6/13 passed, 7 failed. Root issue identified: in this test setup each source publishes to 1 channel (news→2001 etc.), but counts show DOUBLE publish per single message (2 instead of 1). Cause: `get_targets_for_source` also adds public-source rule? No — each source is special to exactly one channel. Why 2 sends per msg? Look at media path: publish_source_message for MEDIA posts sends via copy_middle → 1 send per target. For TEXT path: safe_send_channel_message. So 2 sends means message went through BOTH targets? Check FakeMessage: media=False, chat=SRC_NEWS (1001). get_targets_for_source(1001) → special_sources of channels: NEWS_CH only. Unless... "src1001" also in public? No.
- Actually wait — maybe the issue is message.chat.id = SRC_NEWS but publish loop also includes something else. OR: clean_state bug: _sent.clear clears module list but capture_send created new local list; self.sent is local. len should be correct.
- Likely real bug: `check_section_claim` for NEW event uses event_fp; but is_hybrid_news_duplicate called first (no match), then claim called twice per target? No, claims after each target in the same call, but only one target for news.
- Hmm 2 sends for single NEW message → maybe both text path AND... no. Need print debug.
- Alternative theory: the harness sent list captures from multiple publishes? clean_state before each test; each test does 2 publishes. F expects 2, got 3. G 4 vs 2, H 2 vs 1, I 4 vs 2, J 3 vs 1, L 2 vs 1, M 2 vs 1.
- Pattern: every single publish produces 2 sends in most cases. F produced 3 for 2 publishes. Suggests: each text publish sends TWICE, or there's a second handler path.
- Possible cause: publish_source_message → text path uses `await safe_send_channel_message(target, ...)` AND earlier `record_published_message`... no.
- Wait — in the new code, when media=False, we loop over target_ids; but BEFORE dedup loop I added target_ids_for_dedup = get_targets_for_source(source_id) ... Actually for text: the dedup loop uses `sorted(target_ids)` then the publishing loop again uses target_ids. That's fine.
- REAL candidate: for test F/G/I, both messages from same source (SRC_NEWS) — publish twice → 4 sends when expect 2. That's consistent with 2 sends per publish.
- But why 2 sends per publish? Check compose_channel_post_text or the loop: maybe target_ids includes both NEWS and another because... `get_all_channels()` includes paused=False, special_sources=[SRC_NEWS] for news only. Hmm.
- Another candidate: `if any_success and raw_text: for target in target_ids: remember_published_text(...)` — no sends.
- Most likely: my new dedup loop for text does `for target in sorted(target_ids): ...` then if not duplicated publishes loop again. Still one loop. But WAIT — there may be a double publish because `target_ids` computed at line 4287 BEFORE... no.
- Need actual debug print: print target_ids and sent list contents.

## Debug findings (round 2)
Debug script (single publish) shows EXACTLY 1 send. So harness double-count comes from harness itself: capture_send creates a fresh local `sent` but bc.safe_send_channel_message etc. assigned each call. BUT clean_state() does `_sent.clear()` where _sent is the module list — different object from test's local sent! So the "extra" sends recorded were captured in prior test's list leftover? No — each setUp creates new list.
TRUE root cause candidate: publish loop calls `record_published_message` — if it's async and we set noop returning None → warning only, no double send.
Next theory: the harness `_sent` is module-level; after test A, tearDown doesn't clean module list; test F uses local list. F saw 3 sends for 2 publishes. If local list got 3 → someone appended 3 times. BUT debug single-call = 1. So per-test publishes DO add 2. WHY? Because get_targets_for_source now also adds NEWS? Wait — source SRC_NEWS=1001 is special to NEWS only. But FakeMessage chat=1001 → target_ids={2001}. Single publish = 1 send per debug.
=> The harness double count must be because tests F/G/I/J use `SRC_NEWS` and a SECOND source that ALSO targets NEWS? F: SRC_JOBS targets JOBS only. Still got 3 sends for 2 publishes → publish count mismatch.
Hypothesis: publish_source_message returns early True BUT still sends? No, debug shows correct.
REAL ANSWER: In harness, `clean_state()` calls `_sent.clear()` (module list) but NOT the local `sent` list created in setUp. The local `sent` is shared with the closure — fine. BUT test A's `self.sent = capture_send()`; then tests run in alphabetical order: A before B etc. The `clean_state` in setUp clears module list but the previous test's `capture_send` closures still point at OLD lists — no double counting though, they're separate lists.
=> Actually the real problem: publish loop in bot_core text path calls `record_published_message(target, sent_msg.id, "text")` — but this is a def (not async?) in bot_core ~line 4394. Check: in new flow, `record_published_message` might be async now → `await` would raise? No, it ran fine (debug).
Decision: rerun harness with added print of sent list contents per failure to see actual duplicates.

## ROOT CAUSE OF HARNESS FAILURES FOUND (round 3)
Tests run alphabetically: A, B, C, D, E, F... Test D mutates channels so SRC_NEWS targets BOTH 2001 and 2002. clean_state() does NOT restore channel special_sources, so subsequent tests (E, F, G, H, I, J) see SRC_NEWS → [2001, 2002] → double sends. Also test A (runs before D) published twice?? A expected 1 — need to check A's log. A runs first with default setup (SRC_NEWS→[2001]); but the second source in A is SRC_NEWS+9=1010, which has NO channels → "لا توجد قنوات مستهدفة" (0 sends). So A gets 1 send total → passes.
Fix: in clean_state(), also reset channels' special_sources to per-channel defaults (NEWS→[SRC_NEWS], SPORTS→[SRC_SPORTS], JOBS→[SRC_JOBS]).

## J failure analysis (round 4)
Debug shows: sources 1002-1015 have NO channels → "لا توجد قنوات مستهدفة" → each contender returns early True, 0 sends from them. So the 3 sends in harness came from: only 1001 targets NEWS, but test harness setup (alphabetical leak from D fixed now) — after isolation fix J should have only sources targeting NEWS publish. Actually the harness still saw 3 sends: sources 1001-1015 each target... after clean_state isolation, ONLY SRC_NEWS (1001) targets NEWS. But 15 contenders use SRC_NEWS+idx → only idx=0 (source 1001) has channels. So expected sends = 1, but got 3?? Wait, in last harness run (with isolation fix) J still failed with 3 sends. Why? Because contention: multiple contenders for source 1001 race between `claim_source_event` (source-level) and the section dedup loop: contender A wins source claim, contender B arrives after A recorded but before B... Actually source_claim returns True only for winner. Losers should exit early with logged "الحدث محجوز مسبقاً". Debug run with the SAME setup showed 0 sends for losers?? No—debug used 15 contenders ALL targeting source 1001 (message from SRC_NEWS+idx chat but source_id passed = SRC_NEWS+idx, so losers have no channels).
=> REAL bug candidate: in harness test J, contenders pass source_id = SRC_NEWS+idx (each different source, none target NEWS) BUT the sent list showed 3. That means the 3 sends came from source 1001 contender ONLY (idx=0)... 3 sends from a single publish = old leak? No, isolation fixed that. OR: multiple contenders with source 1001? idx=0 only.
=> Re-examine: contenders are 0..14, source = SRC_NEWS+idx → only idx=0 → source 1001. One publish → expected 1 send. Got 3. Possibility: race in publish loop — contender idx=0 may run concurrently 3x? gather creates 15 coros, each with unique source. Only one hits NEWS.
=> Need rerun of just test J with debug prints of sent contents.

## J ROOT CAUSE FINAL
No code bug. Test J contenders use sources 1001, 1002, 1003 (idx 0,1,2) — each is special to a DIFFERENT channel (news/sports/jobs = 3 different sections). Same text published once per section = 3 sends = correct section-scoped semantics. Fix: contenders 1..14 should use source 1001 (all same section), OR expectation = 1 per section. Better: fix contender source to SRC_NEWS for all 15, so they share the same section → expect 1 publish. This is the true TOCTOU race case.
