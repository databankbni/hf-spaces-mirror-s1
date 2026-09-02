/* One decoder in the pool.
 *
 * Every worker holds an identical receiver and the identical stream, and each
 * one takes the frames where `t % N == id`. That rule is derived from a shared
 * clock, not negotiated — there are **no messages between workers, no handshake,
 * and no consensus round**, because a frame here is not defined in terms of any
 * other frame. A codec with a prediction chain cannot be split this way at all:
 * worker 3 would need worker 2's output before it could start.
 *
 * So the pool is not a trick to hide latency. It is the addressing property
 * cashed out as throughput.
 */
let E = null, W = 0, H = 0, BW = 0, BH = 0, ID = 0, N = 1;
/* The index: `u64 offset, u32 len` per frame at a fixed 12-byte stride. Its
   LENGTH is the frame count, which is why a live client needs no manifest. */
let IDX = null, URL = "", FETCHED = 0;
/* The UNIT table, one level finer: `u32` byte length per unit, `nunits` per
   frame, fixed stride. Units are contiguous and in order, so lengths give
   offsets by prefix sum. Optional — a container served without `.evu` falls back
   to whole-record fetches, which is what every client did before it existed. */
let UNITS = null, NUNITS = 0;
/* Container stream offset (0 for bare .evs; the prelude's evs_off for .tsb)
   and the lazy unit-table mode: one frame's row (nunits x 4 B at a fixed
   stride) is range-fetched on first touch instead of holding the whole
   sidecar. Rows cache; past 256 the cache clears — it re-fetches, never
   grows. */
let EVS_OFF = 0, EVU_RANGE = null;
const EVU_ROWS = new Map();

async function fetchUnitRow(t) {
  if (!EVU_RANGE || !NUNITS) return null;
  if (EVU_ROWS.has(t)) return EVU_ROWS.get(t);
  const off = EVU_RANGE.off + t * NUNITS * 4;
  if (off + NUNITS * 4 > EVU_RANGE.off + EVU_RANGE.len) return null;
  const r = await fetch(URL, { headers: { Range: `bytes=${off}-${off + NUNITS * 4 - 1}` } });
  if (!r.ok && r.status !== 206) return null;
  let b = new Uint8Array(await r.arrayBuffer());
  if (b.byteLength > NUNITS * 4) b = b.subarray(off, off + NUNITS * 4);
  FETCHED += NUNITS * 4;
  const dv = new DataView(b.buffer, b.byteOffset, NUNITS * 4);
  const out = new Array(NUNITS);
  let o = 0;
  for (let u = 0; u < NUNITS; u++) { const n = dv.getUint32(u * 4, true); out[u] = [o, n]; o += n; }
  if (EVU_ROWS.size > 256) EVU_ROWS.clear();
  EVU_ROWS.set(t, out);
  return out;
}
/* Inside `ensureUnits`: how much is CHOOSING units (a wasm call per unit) versus
   the network. 120 units means 240 JS->wasm crossings per resolve, and I have
   already been wrong twice about which half of a number was the cost. */
let SEL_MS = 0, NET_MS = 0, NET_REQ = 0;
let GAP_BYTES = 0;

const frameCount = () => (IDX ? IDX.byteLength / 12 : 0);

/* A worker fetches its OWN frames. It already knows which ones it owns
   (`t % N == id`), so nothing needs to be routed to it and nothing large is ever
   posted between threads — the fetches are parallel by construction. */
async function ensure(t) {
  if (!IDX || E.evs_frame_loaded(t)) return 0;
  if (t >= frameCount()) return -1;                   // not published yet (live)
  const dv = new DataView(IDX.buffer, IDX.byteOffset + t * 12, 12);
  const off = EVS_OFF + Number(dv.getBigUint64(0, true));
  const len = dv.getUint32(8, true);
  const r = await fetch(URL, { headers: { Range: `bytes=${off}-${off + len - 1}` } });
  if (!r.ok && r.status !== 206) throw new Error(`range fetch ${r.status} for frame ${t}`);
  const buf = new Uint8Array(await r.arrayBuffer());
  // wasm can grow on reserve, so take the pointer first and the view after
  const p = E.evs_reserve_frame(buf.length);
  new Uint8Array(E.memory.buffer, p, buf.length).set(buf);
  if (!E.evs_push_frame(t, p, buf.length)) throw new Error(`frame ${t} record rejected`);
  FETCHED += buf.length;
  return buf.length;
}

/* ── FETCH ONLY THE UNITS A WINDOW TOUCHES ────────────────────────────────────
 *
 * `ensure` pulls a whole frame record. For a window that is almost all waste:
 * measured on the 6x4-tiled clip, a window resolves out of 40,679 B while the
 * record is 398,771 B, so a whole-record fetch pays 9.8x for bytes it will never
 * read. Over 90 seconds of seven drifting windows that was 700 MB pulled to show
 * seven small pictures — the delivery path was the flat one long after the
 * resolve path stopped being.
 *
 * The split is the container's own: a unit is `(segment, tile)` and references
 * nothing outside itself, which is exactly why `evs_push_unit` can install one
 * on its own. Two things were missing and now exist: `.evu` gives each unit's
 * byte span without reading the record, and `evs_unit_role` ranks a unit from
 * geometry alone. Ranking without spans was circular — a client would have had
 * to fetch the record to learn which parts of the record it needed.
 *
 * Adjacent units are COALESCED into one range request, so a window costs a
 * couple of requests rather than one per unit. That is why `.evu` stores file
 * order: neighbours in the plan are neighbours on the wire.
 */
function unitTable(t) {                 // [offset, len] per unit, or null
  if (!UNITS || !NUNITS) return null;
  const base = t * NUNITS * 4;
  if (base + NUNITS * 4 > UNITS.byteLength) return null;
  const dv = new DataView(UNITS.buffer, UNITS.byteOffset + base, NUNITS * 4);
  const out = new Array(NUNITS);
  let off = 0;
  for (let u = 0; u < NUNITS; u++) { const n = dv.getUint32(u * 4, true); out[u] = [off, n]; off += n; }
  return out;
}

async function ensureUnits(t, level, rgn) {
  const tab = unitTable(t) || await fetchUnitRow(t);
  if (!tab || !IDX) return ensure(t);          // no sidecar: whole record, as before
  if (t >= frameCount()) return -1;
  const dv = new DataView(IDX.buffer, IDX.byteOffset + t * 12, 12);
  const fbase = EVS_OFF + Number(dv.getBigUint64(0, true));
  const [x0, y0, x1, y1] = rgn || [0, 0, 0, 0];

  // Which units this rung + this window actually read. `-1` is "finer than this
  // rung asks for" and is skipped entirely; FILL is skipped because a window is
  // by definition not looking there — an absent unit is not a failure.
  /* Presence is checked PER UNIT, not per frame. Two windows sitting on the same
     frame at different places need different units, and `evs_frame_loaded` would
     report the frame present after the first of them fetched — so the second
     would resolve against absent units and come back coarse or empty with
     nothing saying so. `evs_unit_present` is asked of the receiver rather than
     tracked here, because the receiver is the one that evicts. */
  /* WHICH UNITS. A window paints nothing outside itself, so it wants the units
     its tile touches — in every segment, including the coarsest. Taking BASE
     whole (every segment-0 tile) is right for a client showing the full field
     and wrong for one showing windows: measured, that is 36.9% of a record
     against about 10%. `evs_unit_hits` asks the tile question directly; the
     full-field path still goes by role. */
  const windowed = x1 > x0 && y1 > y0;
  const _tsel = performance.now();
  const want = [];
  for (let u = 0; u < NUNITS; u++) {
    /* NO WINDOW MEANS THE WHOLE FIELD — TAKE EVERYTHING THIS RUNG READS.
       This filtered to roles BASE|FOCUS, and with no window declared
       `evs_unit_role` calls segment 0 BASE and EVERY OTHER SEGMENT FILL. So the
       full-field view fetched segment 0 alone and resolved 47,453 addresses where
       native is ~162,000 — 29% of the frame, which paints as blocky colour
       banding at full size. Reported as "blurry", diagnosed from the panel: the
       ladder said 3840x2160 while the address count said otherwise.
       FILL is optional for a client that is LOOKING somewhere; it is not optional
       for one looking everywhere. `>= 0` is "this rung reads it at all" — the
       role ranking still decides ORDER, it must not decide inclusion here. */
    const take = windowed
      ? E.evs_unit_hits(u, level | 0, x0, y0, x1, y1)
      : E.evs_unit_role(u, level | 0, x0, y0, x1, y1) >= 0;
    if (!take) continue;
    if (tab[u][1] > 0 && !E.evs_unit_present(t, u)) want.push(u);
  }
  SEL_MS += performance.now() - _tsel;
  if (!want.length) return 0;                  // already holds everything it reads

  /* COALESCE INTO RUNS — and tolerate a small gap.
   *
   * A window's tiles are adjacent within a segment but a whole segment apart
   * across segments (`unit = segment * ntiles + tile`), so strict adjacency
   * merges almost nothing: measured, 7 windows across 2 workers issued 166 range
   * requests a second at ~7 KB each. Bytes were not the problem — request count
   * was, and on a real network each one carries a round trip that dwarfs the
   * bytes it saves.
   *
   * TRADING BYTES FOR ROUND TRIPS DOES NOT PAY HERE, and it was measured rather
   * than assumed. Merging runs separated by up to 16 KB — fetching the gap and
   * discarding it — moved the wire from 33.6 MB to 51.1 MB over the same 30 s
   * and left the request count unchanged (5,120 against 4,997). The reason is
   * geometric: a record is ~400 KB over 5 segments, so a window's tiles in
   * different segments sit tens of KB apart, past any tolerance worth having,
   * and the only gaps small enough to merge were inside a segment where there
   * was little to gain. GAP stays 0; the knob is left in place because the
   * answer depends on the tile grid and would change with it.
   */
  const GAP = GAP_BYTES;
  const runs = [];
  for (const u of want) {
    const [o, n] = tab[u];
    const last = runs[runs.length - 1];
    if (last && o - last.end <= GAP) { last.end = o + n; last.units.push(u); }
    else runs.push({ start: o, end: o + n, units: [u] });
  }

  /* THE RUNS GO OUT TOGETHER. This was a `for … await`, one round trip after
   * another: a window needs about five runs, so it paid five serialised trips
   * and measured 57.1 ms of fetch against 28.0 ms of unpack and 17.3 ms of
   * resolve — the wire was two thirds of a window's cost on a LOCAL server,
   * where the bytes take no time at all and only the round trips do.
   *
   * Nothing justified the sequencing. Units reference nothing outside
   * themselves — that is the property `evs_push_unit` exists to cash in, and the
   * same one that lets decoders split with no handshake. Awaiting them in order
   * was flattening independent reads into a chain, which is the one thing this
   * format is built not to need.
   *
   * Fetch in parallel, INSTALL in order: `evs_reserve_frame` hands back one
   * shared scratch buffer, so two installs cannot be in flight at once. The
   * network part is concurrent; the wasm part stays serial because it must.
   */
  const _tnet = performance.now();
  const bufs = await Promise.all(runs.map(async r => {
    const a = fbase + r.start, b = fbase + r.end - 1;
    const resp = await fetch(URL, { headers: { Range: `bytes=${a}-${b}` } });
    if (!resp.ok && resp.status !== 206) throw new Error(`range fetch ${resp.status} for frame ${t}`);
    return new Uint8Array(await resp.arrayBuffer());
  }));

  NET_MS += performance.now() - _tnet; NET_REQ += runs.length;
  let got = 0;
  for (let i = 0; i < runs.length; i++) {
    const r = runs[i], buf = bufs[i];
    FETCHED += buf.length; got += buf.length;
    for (const u of r.units) {
      // index by the unit's OWN offset within the run, not by a running cursor:
      // with gaps merged the units are no longer contiguous in the buffer, and a
      // cursor would hand each unit the bytes of whatever preceded it
      const [o, n] = tab[u];
      const ptr = E.evs_reserve_frame(n);        // reserve first — it can grow
      new Uint8Array(E.memory.buffer, ptr, n).set(buf.subarray(o - r.start, o - r.start + n));
      E.evs_push_unit(t, u, ptr, n);
    }
  }
  return got;
}

/* READ ONE FRAME AHEAD — THE RIGHT IDEA, BLOCKED BY THE TRANSPORT.
 *
 * The three costs are serial and that IS the problem — measured, per window
 * resolve: net 32.2 ms + unpack 12.3 + resolve 5.6 = 50.1, and 3 workers / 50.1 ms
 * / 3 windows lands on exactly the 20 fps observed. Nothing is too slow. They are
 * in a line, and overlapping them would make the cost max(fetch, decode) = ~32 ms
 * instead of the sum, then ~18 ms once the fetch stops dominating.
 *
 * Tried twice, both worse, and the second attempt says why:
 *
 *                        picture fps   net ms   requests
 *   no prefetch                 20.0     32.2        7.7
 *   prefetch after the post     14.1     57.5          —
 *   prefetch BEFORE the decode   9.2    160.9       14.7
 *
 * Starting it earlier was correct in principle and made things worse in fact,
 * because a browser opens SIX connections per origin on HTTP/1.1 and a resolve
 * already needs 7.7 requests. A speculative read does not overlap the decode; it
 * doubles the queue in front of the read that is on screen.
 *
 * This is a TRANSPORT limit, not a design one. The origin serving these clips
 * answers `HTTP/2 200`, and HTTP/2 multiplexes every range over one connection
 * with no six-way cap — so the overlap that loses here is exactly the one that
 * should win in production. Kept unwired with the numbers attached, because the
 * measurement that would settle it needs an h2 test origin this container cannot
 * offer the browser (Chromium's TLS cannot traverse the agent proxy).
 *
 * `the stream-measurement lab` §8 names this as "the obvious next step", and on
 * this harness it is not. Kicking the next frame's units off before posting the
 * current one, then awaiting that promise on the next turn:
 *
 *              picture fps    fetch ms
 *   without           20.0        39.0
 *   with              14.1        57.5     (1 window)
 *   with               8.3        83.7     (3 windows)
 *
 * It LOSES, and the reason is visible in the fetch column going up rather than
 * down: the prefetch shares one connection pool with the read that is actually
 * on screen, so it does not overlap the work — it queues in front of it. With
 * three workers each holding a speculative read, six connections are contended
 * by six sets of ranges and every window waits longer.
 *
 * Kept, unwired, because the idea is right and the implementation is what is
 * wrong: a prefetch has to be cheaper than the read it hides behind, which means
 * a lower-priority connection or a request the server can answer without a round
 * trip. Deleting it would lose the measurement that says so.
 *
 * `the stream-measurement lab` §8, after measuring the 22.5 ms/frame wire read:
 * "Reading one frame ahead in a worker is the obvious next step and has not been
 * done." It still had not been. Measured here, a window spent 39 ms fetching
 * against 27 ms unpacking and 18 ms resolving — with the fetch ON THE CRITICAL
 * PATH, so the three add instead of overlapping.
 *
 * A frame here is reachable at the same cost as any other and depends on nothing
 * before it, so the next one can be pulled while the current one resolves. That
 * is not a jitter buffer — nothing is queued and nothing waits its turn; it is one
 * outstanding read, and if the playhead moves elsewhere it is simply unused. The
 * units land in the receiver's own cache, which is bounded, so an unused prefetch
 * costs a fetch and never grows.
 *
 * Keyed and awaited rather than fired blind: two `ensureUnits` for the same frame
 * running at once would fetch the same ranges twice, so a request that finds a
 * prefetch in flight joins it instead of starting a second one.
 */
let AHEAD_KEY = null, AHEAD_PROMISE = null;

function prefetch(t, level, rgn) {
  const key = `${t}|${level}|${rgn.join(",")}`;
  if (AHEAD_KEY === key) return;
  AHEAD_KEY = key;
  // failures are swallowed HERE and not swallowed on the real path: a prefetch
  // that 404s must not take down the window that is actually being shown
  AHEAD_PROMISE = ensureUnits(t, level, rgn).catch(() => null);
}

async function ensureAhead(t, level, rgn) {
  const key = `${t}|${level}|${rgn.join(",")}`;
  if (AHEAD_KEY === key && AHEAD_PROMISE) {
    const p = AHEAD_PROMISE;
    AHEAD_KEY = null; AHEAD_PROMISE = null;
    const got = await p;
    // a prefetch that failed leaves the units absent; ensureUnits is idempotent,
    // so re-running it is correct rather than a fallback path
    return got === null ? ensureUnits(t, level, rgn) : got;
  }
  return ensureUnits(t, level, rgn);
}

/* wasm calls can grow memory, and growth detaches every view AND every
   `E.memory.buffer` already on the stack — so call first, take `.buffer` after. */
const view = (C, p, n) => new C(E.memory.buffer, p, n);

self.onmessage = async ev => {
  let m = ev.data;

  if (m.cmd === "init") {
    ID = m.id; N = m.n;
    EVS_OFF = m.evsOff || 0;
    EVU_RANGE = m.evuRange || null;
    const mod = await WebAssembly.instantiate(m.wasm, {});
    E = mod.instance.exports;
    /* A receiver missing an export must refuse to start. The alternative is the
       failure this cost a day to find: the call throws, no frame is posted, and
       the readout keeps showing its initial 0 — a wrong number that looks like a
       measurement. Name the missing symbol and stop. */
    const need = ["evs_reserve", "evs_frame_at", "evs_frame_corrupt",
                  "evs_frame_bytes", "evs_pts_n", "evs_pts_ptr", "evs_ref_luma",
                  "evs_frame_region",
                  // the streaming path: without these the worker would silently
                  // fall back to needing the whole clip, which is the failure
                  // this whole change exists to remove
                  "evs_open", "evs_push_frame", "evs_frame_loaded",
                  "evs_cache_cap", "evs_cache_len", "evs_reserve_frame",
                  // unit-granular delivery: without these a window would pull a
                  // whole record for the ~10% of it that it reads
                  "evs_push_unit", "evs_unit_role", "evs_nunits", "evs_unit_present", "evs_unit_hits"];
    const missing = need.filter(f => typeof E[f] !== "function");
    if (missing.length) {
      self.postMessage({ ok: false, id: ID, fatal: `receiver is missing ${missing.join(", ")}` });
      return;
    }
    // Header only — 36 bytes. The clip's length is irrelevant to startup now.
    const hdr = new Uint8Array(m.header);
    const hp = E.evs_reserve(hdr.length);
    new Uint8Array(E.memory.buffer, hp, hdr.length).set(hdr);
    const ok = E.evs_open(hp, hdr.length);
    IDX = new Uint8Array(m.index);
    URL = m.url;
    // Each worker holds its own bounded cache; the pool's total is N times this,
    // not N times the clip.
    E.evs_cache_cap(m.cache || 24);
    W = E.evs_w(); H = E.evs_h(); BW = E.evs_bw(); BH = E.evs_bh();
    NUNITS = E.evs_nunits();
    /* The unit table is optional by design: an older container has no `.evu`,
       and a client without one simply fetches whole records — which is what
       every client did until now. Announce which mode this worker is in, so a
       page reporting "unit-granular" can only do so when it is true. */
    if (m.units && NUNITS > 0 && m.units.byteLength >= NUNITS * 4) UNITS = new Uint8Array(m.units);
    if (EVU_RANGE && EVU_RANGE.len < NUNITS * 4) EVU_RANGE = null;
    if (m.gap !== undefined) GAP_BYTES = m.gap | 0;
    self.postMessage({ ok: !!ok, id: ID, frames: frameCount(), w: W, h: H, bw: BW, bh: BH,
                       bs: E.evs_block(), levels: E.evs_levels(),
                       nunits: NUNITS, tx: E.evs_tiles_x(), ty: E.evs_tiles_y(),
                       unitwise: !!UNITS || !!EVU_RANGE });
    return;
  }

  if (m.cmd === "grow") {           // live: the index got longer
    IDX = new Uint8Array(m.index);
    self.postMessage({ id: ID, frames: frameCount() });
    return;
  }

  if (m.cmd === "push") {
    // A record arriving on a socket is the same object a range request returns,
    // so it installs with the same call. There is no live decoder and no live
    // format — only a different way for the bytes to show up.
    const b = new Uint8Array(m.rec);
    const p = E.evs_reserve_frame(b.length);
    new Uint8Array(E.memory.buffer, p, b.length).set(b);
    E.evs_push_frame(m.t, p, b.length);
    FETCHED += b.length;
    m = { ...m, cmd: "decode" };
  }

  if (m.cmd === "decode") {
    /* THE GPU PATH FETCHES UNITS TOO.
     *
     * This said `ensure(m.t)` — the WHOLE record, 391 KB a frame — while the CPU
     * fallback had been taught to pull only the units it reads. A phone with
     * WebGL2 never enters the fallback, so it ran the old delivery path all day
     * and none of the work aimed at it applied. The owner's own panel is what
     * showed it: "DECODERS 6 locked · GPU VS CORE exact" beside "THIS FRAME
     * 391 KB · 15.47 MB pulled" and DISPLAY falling to 0.
     *
     * `ensureUnits` handles both shapes: with `rgn` it takes the units that
     * window touches, and with none it takes what the RUNG reads — segments finer
     * than this output are skipped rather than fetched and discarded. Falls back
     * to the whole record by itself when the container has no `.evu`. */
    const got = await ensureUnits(m.t, m.level | 0, m.rgn || null);
    if (got < 0) { self.postMessage({ frame: m.t, seq: m.seq, pending: true }); return; }
    // Only the segments this output scale needs are touched — a smaller output
    // does LESS WORK, not the same work followed by a discard.
    // permille of the channel destroyed, and which lane takes it. armour=1 sends
    // each index as its row4096, damages the row, and reads it back; armour=0
    // corrupts the index itself and has nothing to recover from.
    //
    // Take the count from what the call RETURNS. There is a module-level static
    // holding the same number, but an undamaged frame never writes it, so reading
    // the static cannot distinguish "no damage applied" from "nothing survived" —
    // both come back 0. `null` says the question wasn't asked.
    //
    // A region read resolves only the blocks a window touches. The cost is set by
    // the window, not by the frame, which is the only reason a device that cannot
    // afford a 4K field can hold a native-detail piece of one.
    let survived = null;
    if (m.rgn) E.evs_frame_region(m.t, m.level, m.rgn[0], m.rgn[1], m.rgn[2], m.rgn[3]);
    else if (m.permille) survived = E.evs_frame_corrupt(m.t, m.level, m.permille, m.armour);
    else E.evs_frame_at(m.t, m.level);
    const pts = [], xfer = [];
    let events = 0;
    for (let ch = 0; ch < 3; ch++) {
      const n = E.evs_pts_n(ch), p = E.evs_pts_ptr(ch);
      const a = view(Int32Array, p, n * 2).slice();   // copy out; wasm reuses the buffer
      pts.push(a); xfer.push(a.buffer); events += n;
    }
    // The frame carries the settings it was decoded under. Requests issued before
    // a dial change are still in flight when it lands, and without this they are
    // indistinguishable from fresh ones — the player would paint a recovery figure
    // measured at a damage level nobody is looking at.
    self.postMessage({ frame: m.t, level: m.level, seq: m.seq, pts,
                       survived, events, rgn: m.rgn || null, permille: m.permille | 0, armour: m.armour | 0,
                       bytes: E.evs_frame_bytes(m.t, m.level),
                       // this worker's cumulative pull; the player sums across
                       // the pool, since each worker only ever sees its own
                       id: ID, wire: FETCHED }, xfer);
    return;
  }

  if (m.cmd === "sizes") {
    await ensure(m.t);
    // What every output format costs on the wire, measured on a real frame —
    // so the ladder can state its price before you pick it.
    const out = [];
    for (let L = 0; L < E.evs_levels(); L++) out.push(E.evs_frame_bytes(m.t, L));
    self.postMessage({ sizes: out });
    return;
  }

  if (m.cmd === "rgbaBytes") {
    /* The wire decoupled from the decoder: the MAIN thread fetched this
       record (its own concurrency, its own pacing) and hands the bytes over —
       this worker only installs and resolves. The decode never waits on the
       network, which is what lets capacity mean CPU capacity.

       m.z marks a v2 container: the record crossed the wire raw-deflated
       (54.6% measured) and is inflated here BYTE-EXACT before the receiver
       indexes a single unit — every downstream law sees identical bytes.
       A corrupt stream throws, the frame reports pending, the schedule
       refetches: fail-closed, never a wrong pixel. */
    let rec = new Uint8Array(m.rec);
    if (m.z) {
      try {
        const ds = new DecompressionStream("deflate-raw");
        const w = ds.writable.getWriter(); w.write(rec); w.close();
        const chunks = []; const rd = ds.readable.getReader();
        for (;;) { const { done, value } = await rd.read(); if (done) break; chunks.push(value); }
        let n = 0; for (const c of chunks) n += c.length;
        const flat = new Uint8Array(n); let o = 0;
        for (const c of chunks) { flat.set(c, o); o += c.length; }
        rec = flat;
      } catch (e) {
        self.postMessage({ frame: m.t, seq: m.seq, pending: true }); return;
      }
    }
    const rp = E.evs_reserve_frame(rec.length);
    new Uint8Array(E.memory.buffer, rp, rec.length).set(rec);
    if (!E.evs_push_frame(m.t, rp, rec.length)) {
      self.postMessage({ frame: m.t, seq: m.seq, pending: true }); return;
    }
    const t0 = performance.now();
    E.evs_frame_at(m.t, m.level | 0);
    const p = E.evs_ref_rgba();
    const rw = E.evs_ref_w(), rh = E.evs_ref_h();
    const rgba = view(Uint8Array, p, rw * rh * 4).slice();
    self.postMessage({ rgba, rw, rh, frame: m.t, level: m.level | 0, seq: m.seq,
                       ms: performance.now() - t0 }, [rgba.buffer]);
    return;
  }

  if (m.cmd === "rgba") {
    /* The no-GPU render path. The wasm side resolves all three channels and does
       the YUV->RGB, so what comes back is an ImageData-shaped buffer and the main
       thread does NO per-pixel work — the earlier luma path cost millions of
       array writes in JS per frame, which is what made software playback stutter.
       Transferred, not copied.

       Unit-granular when the sidecar allows it: a coarse rung reads only the
       segments its scale needs (`evs_unit_role >= 0` — the whole-field
       selection), so the record's finer segments never cross the wire. That is
       the segment law cashing out on the full-frame path, not just windows. */
    const got = await ((UNITS || EVU_RANGE) ? ensureUnits(m.t, m.level | 0, null)
                                            : ensure(m.t));
    if (got < 0) { self.postMessage({ frame: m.t, seq: m.seq, pending: true }); return; }
    const t0 = performance.now();
    /* DECODE FIRST. `evs_ref_rgba` reads PTS and the rung the decode recorded; it
       does not decode. Omitting this left PTS stale and LAST_LEVEL at 0, so the
       resolve sized itself to the NATIVE field — a 32768x17280 RGBA buffer, 2.2 GB,
       which traps the wasm heap and surfaces only as "unreachable". */
    E.evs_frame_at(m.t, m.level | 0);
    const p = E.evs_ref_rgba();
    const rw = E.evs_ref_w(), rh = E.evs_ref_h();
    const rgba = view(Uint8Array, p, rw * rh * 4).slice();
    let addrs = 0;
    for (let ch = 0; ch < 3; ch++) addrs += E.evs_pts_n(ch);
    self.postMessage({ rgba, rw, rh, frame: m.t, level: m.level | 0, seq: m.seq,
                       ms: performance.now() - t0, addrs,
                       bytes: E.evs_frame_bytes(m.t, m.level | 0), wire: FETCHED },
                     [rgba.buffer]);
    return;
  }

  if (m.cmd === "win") {
    /* One window out of one frame. `evs_frame_region` limits the DECODE to the
       blocks the window touches, and `evs_ref_window_rgba` limits the RESOLVE to
       the same blocks — so a 256x256 window costs its own 1,424 addresses rather
       than a frame's worth. Windows into the same inscription are independent:
       nothing here is shared, nothing is cropped from a bigger picture. */
    /* evs_frame_region takes OUTPUT SAMPLES at this level; evs_ref_window_rgba
       takes BLOCKS. Passing block coordinates to both selected an 18x10 SAMPLE
       box instead of an 18x10 BLOCK one — 76 addresses where the window should
       see ~2,400 — so the windows came back almost entirely empty, and the few
       surviving pixels read as pure tint. Convert once, here, at the boundary,
       and the SAME sample-space rectangle drives the fetch, so what is delivered
       and what is read are decided by one number rather than two that can drift. */
    const tile = E.evs_block() >> (m.level | 0);
    const rgn = [m.bx0 * tile, m.by0 * tile, m.bx1 * tile, m.by1 * tile];
    /* SPLIT THE CLOCK THREE WAYS. One `ms` for the whole thing cannot say whether
       a slow window is the wire, the unpack, or the resolve — and I have now
       guessed wrong about which twice. Each is timed separately and reported. */
    const tf = performance.now();
    const got = await ensureUnits(m.t, m.level | 0, rgn);
    if (got < 0) { self.postMessage({ frame: m.t, seq: m.seq, pending: true }); return; }
    /* KICK THE NEXT FETCH BEFORE THE DECODE, NOT AFTER THE POST.
     *
     * The three costs are serial and that is the whole problem — measured, per
     * window resolve: net 32.2 ms + unpack 12.3 + resolve 5.6 = 50.1, and
     * 3 workers / 50.1 ms / 3 windows lands on exactly the 20 fps we see. Nothing
     * is too slow; they are in a line.
     *
     * My first attempt fired the prefetch after posting the result, which hides
     * nothing — by then the worker is idle anyway. Started HERE it overlaps the
     * ~18 ms of decode and resolve that follow, so the cost per frame becomes
     * max(fetch, decode) instead of their sum. The fetch is not awaited; the next
     * `win` message joins the in-flight promise through `ensureAhead`. */
    const t0 = performance.now();
    E.evs_frame_region(m.t, m.level | 0, rgn[0], rgn[1], rgn[2], rgn[3]);
    const t1 = performance.now();
    const p = E.evs_ref_window_rgba(m.bx0, m.by0, m.bx1, m.by1);
    const ww = E.evs_win_w(), wh = E.evs_win_h();
    const rgba = view(Uint8Array, p, ww * wh * 4).slice();
    let addrs = 0;
    for (let ch = 0; ch < 3; ch++) addrs += E.evs_pts_n(ch);
    self.postMessage({ rgba, ww, wh, id: m.id, frame: m.t, seq: m.seq,
                       ms: performance.now() - t0, addrs, wire: FETCHED,
                       msFetch: t0 - tf, msUnpack: t1 - t0,
                       selMs: SEL_MS, netMs: NET_MS, netReq: NET_REQ,
                       msResolve: performance.now() - t1,
                       hits: E.evs_decode_hits ? E.evs_decode_hits() : 0,
                       misses: E.evs_decode_misses ? E.evs_decode_misses() : 0,
                       // what this receiver is actually holding right now — the
                       // page reports the sum, so "1-3 frames resident" is a
                       // measurement rather than a claim about the code
                       resident: E.evs_cache_len() }, [rgba.buffer]);
    return;
  }

  if (m.cmd === "ref") {                    // the CPU reference, for the GPU check
    await ensure(m.t);
    const L = m.level | 0;
    E.evs_frame_at(m.t, L);
    const rp = E.evs_ref_luma();
    const ref = view(Uint8Array, rp, W * H).slice();
    /* `evs_ref_luma` writes into a buffer strided by the FULL frame width, so at
       a coarse rung only the top-left (bw·tile)x(bh·tile) of it is written. The
       caller needs those dimensions to read it correctly — without them a coarse
       CPU frame paints as a small image in the corner of a large black one. */
    const tile = E.evs_block() >> L;
    self.postMessage({ ref, refW: BW * tile, refH: BH * tile, refStride: W,
                       frame: m.t, level: L, seq: m.seq }, [ref.buffer]);
  }
};
