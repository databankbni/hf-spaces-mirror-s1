import {makeEVSGL} from "./evsgl.js";

const $=i=>document.getElementById(i);
const nf=n=>n.toLocaleString();
const kb=b=>b<1024?b+" B":b<1048576?(b/1024).toFixed(0)+" KB":(b/1048576).toFixed(2)+" MB";

/* HOW MANY DECODERS. The 6 was a cap I typed, not a measurement, and on a phone
   reporting 8 hardware threads it left two idle. Frames are order-independent, so
   decoder `i` taking `t mod N == i` needs no handshake and scales with cores until
   the cores run out — which is the only ceiling that is real here. `?pool=` forces
   a count so the ceiling can be FOUND rather than assumed: if 8 is no faster than
   6, the device is saturated and more decoders is the wrong lever. */
/* Default 6, not 16: the note above is a MEASUREMENT — past six the device is
   saturated and more decoders buy contention, wasm heaps, and (on phones)
   thermal decay that reads as "degrading fps". `?pool=` still forces any count
   so the ceiling can be found on a given device. */
const POOL = Math.max(2, Math.min(
  +(new URLSearchParams(location.search).get("pool")) || 6,
  (navigator.hardwareConcurrency||4) - 1));
/* FRAMES IN FLIGHT. Three was right when three decoders could each hold one; with
   a pool sized to the machine it starves them — `pump()` stops at
   `buf.size+inflight < depth()`, so a pool of eight has five workers idle waiting
   for a slot that never opens. In flight must be at least the pool, or the extra
   decoders are decoration. Still not a jitter buffer: nothing is held for later,
   it is the number that can be WORKED ON at once. */
const AHEAD = 3;                  // floor; the real depth follows the pool
/* DECODE WHAT YOU WILL SHOW, ONE OR TWO AHEAD — NOT TWENTY-FOUR.
   A deep jitter buffer is a legacy assumption from formats where reaching a
   frame is expensive: you buffer because a seek costs a group of pictures. Here
   every frame costs the same to reach, so buffering ahead protects nothing. It
   multiplies work in flight and memory, and every frame decoded past the
   playhead is thrown away when the dial moves or the feed skips. */
/* THE RATE IS 60, AND THE CONTAINER OUGHT TO BE TELLING US.
   This was 24 — a cinema convention, typed in, justified by nothing. It was wrong
   twice: the source is `F60:1` (crowd_run is `F50:1`), so 60 fps footage was
   playing at 40% speed and a clip billed as 90 seconds was 36 seconds of material
   stretched by a wrong divisor.

   60 is also the substrate's own number: the tower's periods are {4,12,60}, the
   orbit is 240 = 4·lcm(4,12,60), and 60 is the UNIQUE full return
   (TOTAL_FINDINGS §3.3). One orbit is therefore exactly four seconds of playback,
   which is what the narration beats are paced on.

   THE REAL DEFECT IS THAT THIS IS A CONSTANT AT ALL. The .evs header carries
   magic + w, h, frames, block, ky, segs — and no frame rate, so a player CANNOT
   read it and every consumer must guess. Pinning it to the tower's full return is
   defensible where a movie convention was not, but the format should carry the
   rate the source declared. Recorded rather than papered over. */
/* `let`, not `const`: a `.tsb` clip carries the rate the SOURCE declared in
   its prelude and the player reads it there. The four-file layout has no rate
   field — the recorded defect stands for it, and 60 stays the default. */
let RATE  = 60;

/* Three playheads: the 3x3 tower grid runs A/B/C = FORWARD_GENERATIVE (past) /
   RETURN (now) / REVERSE (future), three chiral streams on one conductor spine
   (mechanics note 01, section 3). Three windows onto three moments of a single
   inscription is that grid. It also sets how many frames a receiver can need at
   once, which is why the cache cap is this and not a constant. */
const CPU_GROUPS = 3;

/* Windows onto one inscription. Seven is the Klein channel count and I want to be
   straight that I picked it before noticing that, so it is a chosen number, not a
   derived one. It is here rather than beside the window construction because the
   decoder pool is sized against it — a decoder past the last window has nothing
   to do. */
/* ONE WINDOW PER CHIRAL STREAM. THREE.
 *
 * This was 7, and 7 was the whole reason the picture crawled. Measured on this
 * hardware by sweeping the count, everything else held fixed:
 *
 *     windows   picture fps/window   total resolves/s
 *           1                 40.0               40.0
 *           2                 20.0               40.0
 *           3                 21.7               65.1
 *           5                  9.0               45.0
 *           7                  7.9               55.3
 *
 * The TOTAL is flat. The budget is per RESOLVE, not per window and not per pixel
 * — which is the same law 7069073 recorded ("cost here is per-address and
 * per-frame, not per-pixel, so shrinking the output is the wrong lever") seen
 * from the other side. Seven windows does not cost seven times less each; it
 * divides one budget seven ways, and 7.9 fps is a slideshow.
 *
 * 141ee08 measured the configuration that WAS smooth — one full-frame view of
 * the 4K clip at 17.2 fps display / 9.7 decode — and recorded the rule: "the
 * default is therefore the clip a phone can play." I then made seven windows the
 * default and broke that rule without re-measuring.
 *
 * Three is not a compromise between 1 and 7. It is the 3x3 tower grid's three
 * chiral streams — FORWARD_GENERATIVE (past) / RETURN (now) / REVERSE (future)
 * (mechanics note 01 section 3) — which is already the number of playheads this
 * player runs. One window per stream, each showing its own moment of the one
 * inscription, at a rate that is video rather than a slideshow.
 */
/* HOW BIG A GAP IS WORTH FETCHING TO SAVE A REQUEST — AND WHY THE ANSWER IS ZERO.
 *
 * A window's units coalesced strictly need ~11.8 range requests. On HTTP/1.1 a
 * browser opens SIX connections per origin, so they queue in two rounds: the
 * network read 38.8 ms while unit SELECTION took 0.0 ms and the server answered
 * ten parallel ranges in 6.5 ms. Merging across a gap collapses the request
 * count and doubles the speed:
 *
 *     gap      picture fps/window   net ms   reqs   MB / 30 s
 *       0                    15.7     33.6    7.7        98.5
 *   16 KB                    15.7     22.4    4.6           —
 *   64 KB                    29.2     12.6    1.7       535.8
 *  256 KB                    30.0     10.0    1.0           —
 *
 * 5.4x the bytes for 1.9x the speed. On a phone that is the wrong way round, and
 * it throws away the whole reason `.evu` exists.
 *
 * THE LIMIT IS HTTP/1.1, NOT THE FORMAT. The origin serving these clips answers
 * `HTTP/2 200` (checked, `storage.googleapis.com`), and HTTP/2 multiplexes every
 * range over ONE connection with no six-way cap — so in production the requests
 * do not queue and the lean setting is also the fast one. The queueing was my
 * local test server being HTTP/1.1.
 *
 * I HAD THE TRADE BACKWARDS. Setting it to 0 was "lean" only in bytes, and bytes
 * were never the scarce thing — ROUND TRIPS were. Re-measured with the whole
 * pipeline fixed (no per-frame allocation storm, no t-planes, no discarded
 * points), collapsing the fetch to ONE request per resolve:
 *
 *     windows   gap     picture fps/window   net ms   reqs   unpack ms
 *           3     0                   20.0     32.2    7.7        12.3
 *           3   64 KB                 60.0     10.2    1.7         7.2
 *           3  256 KB                 66.7      7.6    1.0         6.2
 *           1  256 KB                 80.0      5.7    1.0        13.8
 *
 * Net falls 32.2 -> 7.6 ms and the picture rate triples. The decode does NOT get
 * heavier, which is the part that matters: the gap merges only the RANGE
 * REQUESTS, so bytes that fall in a gap are fetched and dropped, while the units
 * actually INSTALLED and DECODED are still only the ones `evs_unit_hits` selects.
 * Fetch coarsely, decode finely.
 *
 * `?gap=0` restores strict unit-granular fetching for a link where bytes cost
 * more than latency; the readout reports what was pulled either way, so the trade
 * is visible rather than assumed.
 */
/* WHY THE DEFAULT WENT BACK TO 0, AFTER I SHIPPED 262144 AND MADE IT WORSE.
 *
 * The run that measured 66.7 fps per window also pulled 693.7 MB in 20 seconds —
 * 35 MB a second. On a local server bytes are free and that is invisible; on a
 * phone it saturates the link, buffers, and stops. Which is exactly the "slows
 * down and stops" report the change was meant to fix.
 *
 * The choice between round trips and bytes was NEVER REAL. It is an artefact of a
 * test server speaking HTTP/1.1, where six connections per origin force parallel
 * ranges to queue. The origin serving these clips answers HTTP/2, which
 * multiplexes every range over ONE connection — one round trip AND the small byte
 * count. Merging gaps buys nothing there and costs the whole link.
 *
 * `?gap=` stays for an HTTP/1.1 origin, where the trade is real and should be made
 * by someone who knows the link — not by me, from a harness that is not the
 * deployment.
 */
const GAP_BYTES = Math.max(0, +(new URLSearchParams(location.search).get("gap") ?? 0));

/* Read at module scope: `cpuFallback` is called before its own body is reached,
   so a `const` declared beside it sits in the temporal dead zone and the whole
   fallback throws before it draws anything. */
/* PHONES GET THE PROVEN MODE. The full-field GPU butterfly is the working
   demo's path and the one this device demonstrably runs (its own boot check:
   GPU VS CORE exact); the windowed multiplexer measured 0 fps display and
   1 fps/window on the same phone (owner screenshot, 2026-08-05). Touch
   devices therefore default to the full view; `?view=win` forces windows,
   `?view=full` forces full, desktop default is unchanged. */
const windowedWanted = (() => {
  const v = new URLSearchParams(location.search).get("view");
  if (v === "full") return false;
  if (v === "win" || v === "windows") return true;
  return (navigator.maxTouchPoints || 0) === 0;
})();

/* ONE DEMO PER DEVICE CLASS. On the owner's phone the GPU lane does not run
   (measured: 0 fps display while GPU==CPU passes its one-shot check), and the
   CPU edge page does. So touch devices get the receiver that works on them:
   main is the desktop/GPU demo, edge is the phone/CPU demo. `?stay=1` keeps a
   phone on this page deliberately. (corrections ledger W8/W9) */
if ((navigator.maxTouchPoints || 0) > 0
    && !new URLSearchParams(location.search).get("stay")
    && !new URLSearchParams(location.search).get("view")) {
  location.replace("edge.html" + location.search);
}

/* `?stage=none` — the display-stall probe. Fetch, decode, and every counter run
   exactly as they do live; only the presentation stage (bitmap creation and the
   canvas paint) is skipped. On a device that reports 0 fps display with healthy
   delivery, this one reading splits the fault: a healthy loop rate here means
   the stall is the paint/bitmap stage; a dead one means the main thread is
   starved before paint was ever asked to run. A probe, not a mode — it draws
   nothing by design. */
const STAGE_NONE = new URLSearchParams(location.search).get("stage") === "none";

/* `?paint=cpu` — CPU-pure presentation. The decode was never the GPU's: the
   workers' wasm core resolves every pixel in integer arithmetic (the same law
   the reference microdecode holds byte-exact at 6 int ops/pixel). What
   still rode the GPU pipeline was PRESENTATION: one `createImageBitmap` per
   window per frame — an external allocation with an explicit lifecycle — plus
   a 28px shadow blur per window per paint. On devices where that pipeline
   stalls or leaks, the picture degrades to a stop while delivery stays
   healthy. This mode presents through reused per-window 2D canvases via
   `putImageData`: no ImageBitmap objects, no shadow filter, zero per-frame
   allocation — the parity claim (as good on CPU as GPU) made operational. */
const PAINT_CPU = (() => {
  const p = new URLSearchParams(location.search).get("paint");
  if (p === "cpu") return true;
  if (p === "bitmap") return false;         // the explicit way back to the old path
  /* Touch devices default to the CPU-present path: the same device that
     degraded-to-a-stop on the bitmap pipeline runs the reused-canvas path
     acceptably (owner report, 2026-08-05) — per-frame external allocations and
     a 28px shadow filter are exactly what a phone compositor punishes. */
  return (navigator.maxTouchPoints || 0) > 0;
})();

const WINDOWS_MAX = Math.max(1, Math.min(12,
  +(new URLSearchParams(location.search).get("windows")) || 3));

/* Mean record size from the index, and the live window cost measured off the
   wire. Both feed the headline figures, which is why they are module-level: the
   estimate is written at boot and the measurement replaces it while playing. */
let MEAN_FRAME = 0;
function setWindowCost(bytesPerWindow, rate){
  if(!(bytesPerWindow > 0) || !(MEAN_FRAME > 0)) return;
  const mbps = b => (b * 8 * rate) / 1e6;
  const frac = bytesPerWindow / MEAN_FRAME;
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("cWin", `${mbps(bytesPerWindow).toFixed(2)} Mb/s`);
  set("rWin", `${mbps(bytesPerWindow).toFixed(2)} Mb/s`);
  set("cRest", `${(100 * (1 - Math.min(1, frac))).toFixed(2)}%`);
}

(async()=>{
  const boot=$("boot"), bootMsg=$("bootmsg"), bootBar=$("bootbar");
  const say=s=>{ if(bootMsg) bootMsg.textContent=s; };

  say("fetching receiver");
  const wasmBytes = await (await fetch("oham.wasm",{cache:"no-cache"})).arrayBuffer();

  /* THE CLIP IS NEVER DOWNLOADED. Two small files describe it: the header says
     what geometry it has, and the index says where every frame starts. A 135 MB
     clip and a 135 GB one cost the same to open. */
  /* WHERE THE CLIP LIVES IS NOT WHERE THE PAGE LIVES.
     The three files can sit on any origin that honours Range and sends CORS —
     object storage, a CDN, a laptop. `?src=` wins so a stream can be pointed at
     without redeploying; otherwise a <meta name="evs-base"> in the page; otherwise
     alongside the page, which is what a local checkout wants. Relative default
     keeps `python3 -m http.server`-style local use working unchanged. */
  const BASE = new URLSearchParams(location.search).get("src")
            || document.querySelector('meta[name="evs-base"]')?.content
            || "";
  const U = n => BASE ? new URL(n, BASE).href : n;

  /* `.tsb` — THE SEALED SINGLE-FILE FORM. An 88-byte prelude (magic, version,
     the frame rate the source declared, section table) followed by the four
     wire sections verbatim; the receiver wasm sees exactly the bytes it always
     saw. Fail-closed on every violation. The unit table is NOT fetched whole —
     workers range-fetch one frame's row on demand (its fixed stride is the
     design), so opening costs prelude + header + index. */
  const IS_TSB = /\.tsb([?#]|$)/.test(BASE);
  let headerBytes, indexBytes, unitBytes = null, EVS_OFF = 0, TSB_URL = null, EVU_RANGE = null;
  if (IS_TSB) {
    say("fetching container prelude");
    TSB_URL = BASE;
    const rangeOf = async (off, len) => {
      if (!len) return null;
      const r = await fetch(TSB_URL, {headers: {Range: `bytes=${off}-${off + len - 1}`},
                                      cache: "no-cache"});
      if (!r.ok && r.status !== 206) throw new Error(`range ${r.status} on container`);
      const b = await r.arrayBuffer();
      return b.byteLength === len ? b : b.slice(off, off + len);   // Range-blind server
    };
    /* The prelude is 88 B (flags==0, four sections) or 104 B (flags bit 0 =
       the evd integrity lane: a fifth section of 8-byte per-record corruption
       checksums, 2026-08-13). The lane is additive — decode ignores it — so a
       reader that knows both forms opens every container the sealers emit.
       Any OTHER flag bit still refuses: unknown bits are unknown laws. */
    const pre = new DataView(await rangeOf(0, 104));
    const magic = String.fromCharCode(pre.getUint8(0), pre.getUint8(1),
                                      pre.getUint8(2), pre.getUint8(3));
    if (magic !== "TSB1") { say(`not a .tsb container (magic ${magic})`); return; }
    if (pre.getUint32(4, true) !== 1) { say("unknown .tsb version"); return; }
    const fpsN = pre.getUint32(8, true), fpsD = pre.getUint32(12, true);
    if (!fpsN || !fpsD) { say(".tsb declares no frame rate — refused"); return; }
    const FLAGS = pre.getUint32(16, true);
    if (FLAGS & ~1) { say(".tsb unknown flag bits — refused"); return; }
    if (pre.getUint32(20, true)) { say(".tsb reserved field nonzero — refused"); return; }
    const NSEC = (FLAGS & 1) ? 5 : 4;
    const sec = i => ({ off: Number(pre.getBigUint64(24 + 16 * i, true)),
                        len: Number(pre.getBigUint64(32 + 16 * i, true)) });
    const SECS = [...Array(NSEC).keys()].map(sec);
    const [sevh, sevi, sevu, sevs] = SECS;
    let cursor = 24 + 16 * NSEC;
    for (const sc of SECS) {
      if (sc.off !== cursor) { say(".tsb sections do not tile — refused"); return; }
      cursor = sc.off + sc.len;
    }
    RATE = fpsN / fpsD;
    say("fetching header");
    headerBytes = await rangeOf(sevh.off, sevh.len);
    say("fetching index");
    indexBytes  = await rangeOf(sevi.off, sevi.len);
    /* the working demo preloads its whole 2.6 MB unit table and pays zero
       per-frame table requests; a 22 MB table would poison the open. Preload
       when small, lazy rows when large — the threshold is the open cost we
       accept, not a guess about the clip. */
    if (sevu.len && sevu.len <= (4 << 20)) {
      say("fetching unit table");
      unitBytes = await rangeOf(sevu.off, sevu.len);
      EVU_RANGE = null;
    } else {
      unitBytes = null;
      EVU_RANGE = sevu.len ? { off: sevu.off, len: sevu.len } : null;
    }
    EVS_OFF     = sevs.off;
  } else {
  say("fetching header");
  /* The two small files are fetched no-cache and the stream is tagged with the
     index's own length, so replacing the clip on the origin actually replaces it
     in the browser. Without this a viewer keeps playing the previous clip out of
     cache and every readout describes a file that is no longer there — which is
     exactly what happened when the default changed. */
  headerBytes = await (await fetch(U("clip.evh"),{cache:"no-cache"})).arrayBuffer();
  say("fetching index");
  indexBytes  = await (await fetch(U("clip.evi"),{cache:"no-cache"})).arrayBuffer();
  /* `.evu` — THE UNIT TABLE. `.evi` says where a FRAME starts so a client can
     fetch one frame instead of the file; `.evu` says where each UNIT starts
     inside that frame so a window can fetch what it reads instead of the frame.
     Measured on the 6x4-tiled clip: a window reads 40,679 B out of a 398,771 B
     record, so a whole-record fetch was paying 9.8x for bytes it never touched.

     OPTIONAL BY DESIGN. A container published before this sidecar existed simply
     does not have one, and a client without it fetches whole records exactly as
     before — which is why this is a `.catch(()=>null)` and not a hard failure.
     Whether it is in use is REPORTED, never assumed: a page claiming
     unit-granular delivery while falling back would be a false readout. */
  unitBytes = await fetch(U("clip.evu"),{cache:"no-cache"})
    .then(r=>r.ok?r.arrayBuffer():null).catch(()=>null);
  }
  /* THE CACHE TAG MUST FOLLOW THE INDEX'S CONTENT, NOT ITS LENGTH.
     It was `?v=${indexBytes.byteLength}`, which is the frame count times twelve —
     so replacing a 5,400-frame clip with a DIFFERENT 5,400-frame clip produced the
     identical tag, and a viewer inside the object store's 300 s window would pull
     the new index against the cached old stream. Every offset would then point
     into the wrong file. That is not a subtle failure — the receiver rejects the
     records — but it is an avoidable one, and the tag it needs is a fold of the
     bytes rather than a count of them. FNV-1a over the index and the header, which
     between them determine every offset a client will use. */
  const tagOf = (...bufs) => {
    let x = 0x811c9dc5;
    for (const b of bufs) {
      const a = new Uint8Array(b);
      for (let i = 0; i < a.length; i++) { x ^= a[i]; x = Math.imul(x, 0x01000193) >>> 0; }
    }
    return x.toString(36);
  };
  const STREAM_URL  = (IS_TSB ? TSB_URL : U("clip.evs")) + `?v=${tagOf(headerBytes, indexBytes)}`;
  /* The index has a fixed 12-byte stride, so ITS OWN LENGTH is the frame count.
     Following a live feed is one HEAD request — there is no manifest to publish
     and nothing to rewrite when a frame is appended. */
  const frameCountOf = b => b.byteLength / 12;

  /* The receiver and the worker that drives it must always be the same vintage.
     Deriving the cache-buster from the wasm's own bytes makes that structural: a
     rebuilt receiver mints a new worker URL by construction, so there is no build
     step to remember and no way to serve a mismatched pair. */
  const BUILD=[...new Uint8Array(await crypto.subtle.digest("SHA-256",wasmBytes.slice(0,1<<16)))]
    .slice(0,6).map(b=>b.toString(16).padStart(2,"0")).join("");

  // ── the pool: N identical receivers, locked to one clock ─────────────────
  say(`starting ${POOL} decoders`);
  const workers=[], ready=[];
  let META=null;
  for(let i=0;i<POOL;i++){
    const wk=new Worker(`decoder.js?v=${BUILD}`,{type:"module"});
    workers.push(wk);
    /* A worker that throws does so silently: the frame never posts, the player
       keeps drawing the last one it has, and every readout holds its stale value.
       Say it out loud instead. */
    wk.onerror=ev=>{ say(`decoder ${i} failed: ${ev.message||ev.type}`); console.error(ev); };
    wk.onmessageerror=ev=>{ say(`decoder ${i} sent something unreadable`); console.error(ev); };
    ready.push(new Promise(res=>{
      wk.addEventListener("message",function once(e){
        if(e.data && e.data.id===i){ META=META||e.data; wk.removeEventListener("message",once); res(e.data); }
      });
    }));
    /* Each worker gets the header and the index — 36 B and a few KB — not a copy
       of the clip. It fetches its own frames, so the fetches are parallel and
       nothing large ever crosses a thread boundary. */
    wk.postMessage({cmd:"init",id:i,n:POOL,wasm:wasmBytes,evsOff:EVS_OFF,evuRange:EVU_RANGE,
                    header:headerBytes.slice(0),index:indexBytes.slice(0),
                    units:unitBytes?unitBytes.slice(0):null,
                    url:new URL(STREAM_URL,location.href).href,
                    // resident records per worker: it must hold what it has in
                    // flight, or it evicts a frame it is still working on
                    cache:Math.max(8,Math.ceil(POOL*2/POOL)+6)});
  }
  const metas=await Promise.all(ready);
  const fatal=metas.find(m=>m.fatal);
  if(fatal){ say(fatal.fatal); return; }
  if(!metas.every(m=>m.ok)){ say("stream rejected: bad container"); return; }
  const {frames,w,h,bw,bh,bs,levels}=META;

  /* The canvas is the FIELD's size. Sizing it to the viewport was a guess that
     cost more than it saved: an empty WebGL2 canvas measures 60 fps at 1280x720
     and at 80x45 alike, so the final pass was never the bottleneck — and shrinking
     it broke the boot check, which reads back w*h and then compared the right
     reference against the wrong pixels. Reverted: it bought nothing measurable
     and broke a verifier, which is the worst trade available. */
  const cv=$("cv"); cv.width=w; cv.height=h;
  const G=makeEVSGL(cv);
  if(!G){
    /* NO WEBGL2 — RESOLVE ON THE CPU RATHER THAN SHOWING NOTHING.
       This used to print "this browser has no WebGL2" and stop, which is honest
       and useless: the whole demo is a black page on any machine whose Chrome
       has WebGL2 disabled, blocklisted, or missing a driver. The receiver does
       not need a GPU to resolve a frame — `evs_ref_luma` is a full CPU resolve,
       integer throughout, and the page already calls it every load to check the
       GPU against it. So the fallback is the verifier, promoted to renderer.

       It resolves in COLOUR via `evs_ref_rgba`, using the shader's own integer
       coefficients, so this is the same picture the GPU would draw rather than an
       approximation of it. It is slower than the GPU path, and the page says so
       rather than leaving the viewer to wonder — a silent fallback that quietly
       looks worse is its own bug. */
    await cpuFallback();
    return;
  }

  function fillFigures(w, h, frames){
    const idxDV = new DataView(indexBytes);
    let total = 0;
    for (let t = 0; t < frames; t++) total += idxDV.getUint32(t * 12 + 8, true);
    const meanFrame = total / Math.max(1, frames);
    const mbps = b => (b * 8 * RATE) / 1e6;
    /* THE WINDOW COST STARTS AS AN ESTIMATE AND IS REPLACED BY A MEASUREMENT.
       `winFrac` is pure geometry — a 256^2 window's share of the field area,
       multiplied by the mean frame size. That was the only figure available when
       a window still pulled a whole record, and it was never what the wire did:
       it assumed the fetch was proportional to the area, which was exactly the
       thing that was not true. It stands in until the first window resolves, and
       `setWindowCost` overwrites it with what this client actually pulled — see
       the readout. A page whose strip says "measured, not quoted" must not quote. */
    const winFrac = (256 * 256) / (w * h);
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    set("cMp", (w * h / 1e6).toFixed(1));
    set("cFull", `${mbps(meanFrame).toFixed(0)} Mb/s`);
    set("cWin", `${mbps(meanFrame * winFrac).toFixed(2)} Mb/s`);
    set("cRest", `${(100 * (1 - winFrac)).toFixed(2)}%`);
    set("rFull", `${mbps(meanFrame).toFixed(0)} Mb/s`);
    set("rWin", `${mbps(meanFrame * winFrac).toFixed(2)} Mb/s`);
    MEAN_FRAME = meanFrame;
    set("rOpen", kb(headerBytes.byteLength + indexBytes.byteLength
                    + (unitBytes ? unitBytes.byteLength : 0)));
    /* The receiver's size was typed as "76 KB" and is now 108,586 B — a figure
       that goes stale on every rebuild and that nobody would ever check. It is
       the length of the wasm we just fetched. */
    set("rWasm", kb(wasmBytes.byteLength));
    /* THE TITLE IS DERIVED TOO. The <head> cannot know the clip, so it says
       nothing specific about one; the moment the header is read we do know, and
       the tab should say so. A typed title is the same defect as a typed figure
       — it just fails somewhere nobody looks, which is why the page shipped
       claiming "35 Megapixels" while serving an 8.3 megapixel field. */
    document.title = `${(w * h / 1e6).toFixed(1)} Megapixels On A Phone Connection`;
  }

  async function cpuFallback(){
    const ctx = cv.getContext("2d");
    if(!ctx){ say("no WebGL2 and no 2D canvas — nothing can draw here"); return; }
    /* Do NOT restyle the canvas. The stylesheet already gives it
       `position:fixed; inset:0; object-fit:cover`, which is exactly right: the
       backing store is whatever rung we resolve at, and the browser scales it to
       fill. An earlier version set width/height/object-fit inline here and turned
       a full-bleed video into a letterboxed strip wedged between the copy and the
       readouts — visible on a phone, invisible on a desktop where the aspect
       happened to match. Setting only the backing store leaves layout to CSS. */
    const boot=$("boot"); if(boot) boot.style.display="none";
    const note=document.createElement("div");
    note.style.cssText="position:fixed;left:12px;top:12px;z-index:99;padding:6px 10px;"+
      "background:#3a1d00;color:#ffb454;font:11px/1.5 ui-monospace,monospace;border:1px solid #7a3d00";
    note.textContent="no WebGL2 — resolving on the CPU. check chrome://gpu for the GPU path";
    document.body.appendChild(note);

    const wk=new Worker("decoder.js",{type:"module"});
    /* RESIDENCY IS THE PLAYHEAD COUNT, not a number I liked. There are three
       playheads (the 3x3 grid's A/B/C streams), so a worker never needs a fourth
       frame — and `cache:4` per worker across two workers measured 8 resident,
       which is not the "holds the present, nothing else" this pipeline claims.
       With unit-granular assembly a resident record is also no longer a 400 KB
       object: it holds only the units that were actually fetched, ~7 KB. */
    wk.postMessage({cmd:"init",id:0,n:1,wasm:wasmBytes,evsOff:EVS_OFF,evuRange:EVU_RANGE,
                    header:headerBytes.slice(0),index:indexBytes.slice(0),
                    units:unitBytes?unitBytes.slice(0):null, gap:GAP_BYTES,
                    url:STREAM_URL,cache:CPU_GROUPS});
    const ready=await new Promise(r=>{wk.onmessage=e=>r(e.data);});
    if(!ready.ok){ say("receiver refused the stream: "+(ready.fatal||"bad container")); return; }

    /* The page's figures live on the GPU path, which this branch never reaches,
       so without this the headline reads "… megapixels" and the receipts strip
       reads "…" — a page that renders a picture while claiming to know nothing
       about it. Same derivation, same two files. */
    fillFigures(ready.w, ready.h, ready.frames);
    $("eyebrow").textContent =
      `${ready.w}×${ready.h} · ${nf(ready.frames)} frames · opened with `+
      `${kb(headerBytes.byteLength+indexBytes.byteLength)} · CPU resolve`;
    $("mpool").textContent = "1 cpu";
    /* "greyscale" stopped being true when `evs_ref_rgba` landed — this path
       resolves all three planes with the shader's own integer coefficients. A
       readout that describes a previous version of the code is a false readout,
       so it now says what the delivery actually is, which is the thing a viewer
       cannot otherwise see. `unitwise` comes from the WORKER, which knows whether
       it got a unit table, rather than from whether we tried to fetch one. */
    $("mmode").textContent = ready.unitwise
      ? `colour · ${ready.tx}×${ready.ty} tiles, unit-granular`
      : "colour · whole-record fetch";

    /* PICK THE COARSEST RUNG THAT STILL COVERS THE SCREEN.
       Not a guessed "CPU budget" — an earlier version of this used an invented
       1.5-Mpx constant, which both degraded the picture and hid a real defect in
       the coarse-rung resolve behind a plausible-sounding excuse. The rule here
       needs no constant: resolving more pixels than the display can show is
       waste, so take the smallest output that still fills the viewport.

       This is only usable because the coarse rungs now resolve correctly. They
       did not before (see `evs_ref_luma`): the grid followed the native block
       edge while the points were on a coarser one, giving a sparse black field,
       and pinning the scale-back to the coarse area instead saturated it white.
       Measured on one clip and frame, at 1024x544:

         before        27,957 / 160,000 non-black, mean luma  21.2   (sparse)
         wrong shift  160,000 / 160,000 non-black, mean luma 255.0   (white)
         fixed        160,000 / 160,000 non-black, mean luma  87.3   (picture)

       So a 566-megapixel field is watchable on a CPU: it lands on a coarse rung
       that costs a fraction of native and shows the same picture, which is the
       ladder doing exactly what it is for. */
    /* THE RUNG FOLLOWS WHAT IS ACTUALLY ON SCREEN — and in windowed mode that is
       a WINDOW, not the viewport.
       Sizing to the viewport picks rung 1 (a 1920-wide output) so that the whole
       field would cover a phone. But the windows are drawn at a few hundred CSS
       pixels each, so every one of them was resolving a 1920-scale output and
       throwing most of it away. The ladder is the format's central claim —
       "a smaller size reads FEWER addresses, never other ones" — and it is the
       one lever I never pulled:
           rung 0  162,126 addresses   396,740 B
           rung 1  151,230             359,642
           rung 3   75,397             185,504
           rung 4   42,460             107,966
       So: target the size a window is PAINTED at, times the device ratio, and
       take the coarsest rung that still covers it. `?level=` forces one. */
    const winFrac = windowedWanted ? 1 / (WINDOWS_MAX + 1) : 1;
    /* The CSS size this thing is actually painted at, in device pixels. In
       windowed mode that is one window, not the field. */
    const want = Math.max((window.innerWidth || 1280) * winFrac, 96)
               * (window.devicePixelRatio || 1);
    const outAt = l => ready.bw * (ready.bs >> l) * winFrac;
    let L = 0;
    for (let l = ready.levels - 1; l >= 0; l--) {
      if (outAt(l) >= want) { L = l; break; }
    }
    /* NEVER COARSER THAN WHAT IS SHOWN. The sweep is tempting and it is a trap:
           rung 1  480x272   16.7 fps
           rung 2  240x136   21.7
           rung 3  120x68    33.8
           rung 4   60x34    71.7
       Going below the covering rung doubles the counter by making the picture
       worse, which is degrading the product to flatter a readout. 7069073 wrote
       this down already — "it throws away the resolution that is the entire
       product" — and the whole page is an argument that a field nothing can carry
       is watchable at DETAIL. A blurry 60 fps proves the opposite of the claim.
       The rung covers what is painted and stops there; resolving a 1920-scale
       output into a 200-pixel box was waste, resolving less than the box is loss,
       and only the first is worth removing. */
    const forced = new URLSearchParams(location.search).get("level");
    if (forced !== null) L = Math.max(0, Math.min(ready.levels - 1, +forced));
    /* TWO WORKERS, ALTERNATING — decode the next frame while the current one is
       on screen. One worker cannot: the resolve and the draw would serialise and
       every frame would cost decode + present instead of max(decode, present).
       Frames are independent here, so the split needs no coordination at all —
       the same property the GPU pool already uses. */
    /* AS MANY DECODERS AS THE MACHINE HAS, not two.
       This said `const N = 2` while the GPU path already scaled its pool to
       `hardwareConcurrency - 1`. A worker serialises FETCH then RESOLVE — the
       wasm sits idle during the fetch and the network sits idle during the
       resolve — so the number of workers IS the number of windows that can be in
       flight at once. Seven windows on two workers means every window waits
       behind three and a half others, which is what a 0-resolves-in-ten-seconds
       sample looks like from the inside.

       Capped at the window count, because an eighth decoder would have nothing to
       do, and each one holds its own receiver. */
    const N = Math.max(2, Math.min(WINDOWS_MAX, (navigator.hardwareConcurrency || 4) - 1));
    const pool = [wk];
    for (let i = 1; i < N; i++) {
      const w2 = new Worker("decoder.js", { type: "module" });
      w2.postMessage({ cmd:"init", id:i, n:N, wasm:wasmBytes, evsOff:EVS_OFF, evuRange:EVU_RANGE,
                       header:headerBytes.slice(0), index:indexBytes.slice(0),
                       units:unitBytes?unitBytes.slice(0):null, gap:GAP_BYTES,
                       url:STREAM_URL, cache:CPU_GROUPS });
      await new Promise(r => { w2.onmessage = e => r(e.data); });
      pool.push(w2);
    }
    const ask = (w, t) => new Promise(r => { w.onmessage = e => r(e.data); w.postMessage({cmd:"rgba", t, level:L, seq:t}); });

    const frames = frameCountOf(indexBytes);
    const size = `${ready.bw*(ready.bs>>L)}×${ready.bh*(ready.bs>>L)}`;
    /* Write to the IDs the page actually has. Setting a name that does not exist
       fails silently, which on a readout panel is indistinguishable from a stalled
       decoder — the dashes in the screenshot that started this. */
    const set = (id,v) => { const e=$(id); if(e) e.textContent=v; };
    set("mfocus", `${size} · rung ${L}`);
    set("mframes", nf(frames));

    /* The readouts are the point of this page — a dashboard of dashes reads as a
       broken player, and the CPU path used to populate none of them. Everything
       below is measured on this path, not carried over from the GPU one. */
    /* ── THE PIPELINE, STATED FOR EVERY INSTANT ─────────────────────────────
       At any moment: each worker holds AT MOST ONE outstanding request, and
       exactly one resolved buffer exists per worker — transferred in, blitted,
       released. Nothing queues. Nothing accumulates. There is no jitter buffer
       and no frame ever waits its turn.

       WHY THERE IS NO QUEUE. Buffering ahead is a defence against expensive
       seeks: conventional codecs buffer because reaching frame N means decoding
       the ones before it. Here every frame costs the same to reach and nothing
       references anything, so a queue would only add latency and memory — and
       every frame decoded past the playhead is thrown away the moment the clock
       moves. So the pipeline holds the present, never the future.

       WHAT DRIVES IT. A wall clock, not decode completion. The previous loop
       awaited a decode, drew it, and awaited the next — which makes decode rate
       and playback rate the same number, so a 1 fps decode became a 1 fps
       slideshow instead of real-time video with frames missing. Each worker now
       asks for the frame the CLOCK wants at the instant it becomes free. If a
       resolve takes 800 ms, the next request is for the frame 800 ms later in
       the clip, and the ones between are never decoded at all.

       DROPPING IS FREE HERE, AND THAT IS THE POINT. No reference frames means a
       skipped frame costs nothing downstream — no drift, no artefacts, no
       recovery. A codec with a prediction chain cannot do this; it must decode
       what it intends to discard.

       STALE FRAMES ARE DISCARDED, NOT DRAWN. Two workers can return out of
       order. Presenting an older frame after a newer one is visible backwards
       motion, so a result whose frame is behind what is already on screen is
       dropped — counted, not hidden. */
    /* ── THE PLAYHEAD IS THE SUBSTRATE'S CLOCK, NOT A WALL CLOCK ────────────
       The tower's delays are theorems, not tuning parameters
       (TOTAL_FINDINGS §3.3, promoted to delay.rs, all tau in 1..=60 searched):

         LOCK        6   smallest joint L0+L1 frame landing   (smallest, not unique)
         realign    12   smallest joint L0+L1 identity return (smallest, not unique)
         ROLE_FLIP  30   UNIQUE — the only tau landing all three levels on +-f
         full return 60  UNIQUE — the only full return of the whole tower

       and the nested-cyclone theorem holds 240/240:
         t mod 4 == (t mod 12) mod 4 == (t mod 60) mod 4.

       So the pipeline counts TICKS. The readout refreshes on `realign` and the
       orbit position is reported against `full return`, instead of the 250 ms
       interval I had invented — the paper's own line is that "any protocol
       picking its own timeout here is leaving a theorem on the table", and a
       250 ms refresh was exactly that. One orbit is 240 ticks (4·lcm(4,12,60)). */
    const LOCK=6, REALIGN=12, ROLE_FLIP=30, FULL_RETURN=60, ORBIT=240;
    let shown=0, dropped=0, decMs=0, decN=0;
    /* EACH WORKER ONLY EVER SEES ITS OWN PULL, so the client's figure is the SUM
       across the pool. This was `wire = d.wire || wire` — one worker's cumulative
       total, presented as the whole client's. Measured on a 90 s run: the page
       read 349.30 MB against a browser-observed 700.01 MB, understated by exactly
       the pool size, which is the same defect 27e029e fixed on the GPU path
       ("2.67 MB against a real 9.69 MB") and which I reintroduced here.
       Keyed by WORKER index, not by anything in the message: the `win` reply
       carries `id` = the WINDOW it filled, so trusting `d.id` would collapse
       several workers onto one key and undercount again. */
    const wireBy=new Map();
    const wireTotal=()=>{ let s=0; for(const v of wireBy.values()) s+=v; return s; };
    /* RESIDENT RECORDS, TAKEN FROM THE RECEIVER. The pipeline is supposed to hold
       the present and nothing else — one to three frames, opened and destroyed in
       step with the tick. That was asserted in a comment and never measured, and
       a cap that is never checked is not a bound. `evs_cache_len()` is the
       receiver's own count, so eviction is reflected rather than assumed. */
    const resBy=new Map();
    const resTotal=()=>{ let s=0; for(const v of resBy.values()) s+=v; return s; };
    const resMax=()=>{ let m=0; for(const v of resBy.values()) m=Math.max(m,v); return m; };
    /* Window resolves completed, so the wire total can be divided by them. This
       is the figure the page's whole claim rests on — "a native-detail window out
       of it costs X" — and until now it was an area ratio, not a measurement. */
    let winResolves=0, msF=0, msU=0, msR=0;
    const hitBy=new Map(), missBy=new Map();
    const selBy=new Map(), netBy=new Map(), reqBy=new Map();
    const sumOf=m=>{ let s=0; for(const v of m.values()) s+=v; return s; };
    /* Exposed so a probe can read the split without scraping the panel. */
    globalThis.__split=()=>({resolves:winResolves,
      fetch:msF/Math.max(1,winResolves), unpack:msU/Math.max(1,winResolves),
      resolve:msR/Math.max(1,winResolves),
      hits:sumOf(hitBy), misses:sumOf(missBy),
      sel:sumOf(selBy)/Math.max(1,winResolves), net:sumOf(netBy)/Math.max(1,winResolves),
      req:sumOf(reqBy)/Math.max(1,winResolves)});
    let presented=-1, lastTick=0;
    const t0=performance.now();
    const tickNow=()=>Math.floor((performance.now()-t0)/1000*RATE);
    const wanted=()=>tickNow()%frames;

    const present=(d,k)=>{
      if(!d||!d.rgba||!d.rw) return;
      // behind the playhead, or older than what is already up: drop it
      const ahead=(d.frame-presented+frames)%frames;
      if(presented>=0 && (ahead===0||ahead>frames/2)){ dropped++; return; }
      if(cv.width!==d.rw||cv.height!==d.rh){ cv.width=d.rw; cv.height=d.rh; }
      ctx.putImageData(new ImageData(new Uint8ClampedArray(d.rgba.buffer),d.rw,d.rh),0,0);
      presented=d.frame; shown++;
      decMs+=d.ms||0; decN++; if(d.wire!==undefined) wireBy.set(k,d.wire);
      set("mt",`${d.frame}`); set("maddr",nf(d.addrs||0)); set("mbytes",kb(d.bytes||0));
    };

    /* ── THE NARRATION IS ON THE SAME CLOCK AS THE PICTURE ──────────────────
       Beat boundaries are ORBITS (240 ticks = 4·lcm(4,12,60)), not seconds, so
       the copy advances on the tower's full return rather than on a second timer
       running beside it. Everything a beat asserts is either a number this page
       measured on THIS clip, or a result with a gate behind it — placeholders are
       filled at run time from the header and index, never typed in. */
    const BEATS=[
      ["what you are watching",
       f=>`A ${f.mp} megapixel field, opened by fetching ${f.open}. Not a download — `+
          `a header and an index, and then only the frames on screen.`],
      ["the wire carries addresses",
       f=>`Every event is one 64-bit word: tick, lane, block, index, magnitude, sign. `+
          `The carriers are built here, in your device, never sent.`],
      ["what it costs you",
       f=>`${f.frameKB} per frame at ${f.rate} frames a second — ${f.mbps}. `+
          `The whole field would be ${f.full}, which is why nobody streams one.`],
      ["resolution is a dial",
       f=>`This is rung ${f.rung}, ${f.size}. A smaller size reads FEWER addresses, `+
          `never other ones. No re-encode, no second file, same inscription.`],
      ["any frame, cold, same cost",
       ()=>`There are no reference frames. Nothing here depends on anything before `+
          `it, so a dropped frame costs nothing and a seek costs one fetch.`],
      ["your device is deciding",
       f=>`${f.pool} decoders, each holding one frame. No queue, no read-ahead: `+
          `buffering ahead only protects against expensive seeks, and there are none.`],
      ["this one is running without a GPU",
       f=>`No WebGL2 here, so the resolve is running on the CPU — integer arithmetic, `+
          `in colour, the same routine that verifies the GPU when there is one. `+
          `${f.dfps} frames a second.`],
      ["the clock is the substrate's",
       ()=>`Playback counts ticks on a 240-tick orbit. The delays it uses — 6, 12, `+
          `30, 60 — are theorems about this tower, not timeouts someone picked.`],
    ];
    const facts=()=>{
      const idxDV=new DataView(indexBytes);
      let total=0; for(let i=0;i<frames;i++) total+=idxDV.getUint32(i*12+8,true);
      const mean=total/Math.max(1,frames);
      return { mp:(ready.w*ready.h/1e6).toFixed(1),
               open:kb(headerBytes.byteLength+indexBytes.byteLength),
               frameKB:kb(mean), rate:RATE,
               mbps:`${(mean*8*RATE/1e6).toFixed(0)} Mb/s`,
               full:`${(ready.w*ready.h*3*8*RATE/1e9).toFixed(0)} Gb/s uncompressed`,
               rung:L, size, pool:pool.length, dfps:lastDfps.toFixed(0) };
    };
    let lastBeat=-1, lastDfps=0;
    const narrate=tk=>{
      const b=Math.floor(tk/ORBIT)%BEATS.length;
      if(b===lastBeat) return;
      lastBeat=b;
      const [head,body]=BEATS[b];
      const h=$("beathead"), t=$("beatbody");
      if(!h||!t) return;
      const wrap=$("beat"); if(wrap) wrap.style.opacity="0";
      setTimeout(()=>{ h.textContent=head; t.textContent=body(facts());
                       if(wrap) wrap.style.opacity="1"; }, 180);
    };

    const readout=()=>{
      const tk=tickNow();
      narrate(tk);
      const elapsed=tk-lastTick;
      if(elapsed<REALIGN) return;               // refresh on `realign`, not on a made-up ms
      const secs=elapsed/RATE;
      lastDfps=shown/secs;
      // in windowed mode the paint loop owns mfps; here it would overwrite it
      if(!windowed) set("mfps",lastDfps.toFixed(1));
      /* PICTURE RATE, PER WINDOW — the number a viewer actually experiences.
         This used to be `1000/(decMs/decN)`, the inverse of one resolve's cost,
         which measures how fast a resolve runs and NOT how often anything on
         screen changes. Those differ by everything that is not resolving: the
         fetch, the queue behind other windows, a stall. A run that showed
         "display 60" while ten seconds passed with no new picture is exactly the
         gap between them, and the honest figure is arrivals divided by windows
         divided by elapsed. */
      set("mdps",(shown/Math.max(1,WINDOWS)/secs).toFixed(1));
      set("mwire",kb(wireTotal()));
      /* "6 resident" against a pipeline that claims to hold one to three frames
         reads as a miss; it is three per RECEIVER across two independent
         receivers, which is exactly the bound. Say which, because a number
         without its denominator is the kind of readout that starts an
         investigation into a thing that is working. */
      set("mbuf",`${resMax()}/receiver × ${resBy.size||pool.length} · ${dropped} skipped`);
      // the headline window cost, replaced by what this client actually pulled
      if(winResolves > 0) setWindowCost(wireTotal()/winResolves, RATE);
      /* THE SPLIT, ON SCREEN. Every number I have tuned against came from a
         local server whose transport and bandwidth are nothing like a phone's,
         and the readout could not tell the owner WHICH of the three costs was
         hurting. Now it can: net / unpack / resolve in milliseconds per window,
         plus requests per resolve. A photograph of this line is a diagnosis. */
      set("mver", winResolves
        ? `net ${(sumOf(netBy)/winResolves).toFixed(0)} · unp ${(msU/winResolves).toFixed(0)}`
          + ` · res ${(msR/winResolves).toFixed(0)} ms · ${(sumOf(reqBy)/winResolves).toFixed(1)} req`
        : "cpu resolve");
      /* Where the playhead sits on the tower: position in the 240-tick orbit, and
         the phase of the two UNIQUE delays. A full return is the only tau at which
         the whole tower realigns; a role flip the only one landing all three
         levels on their even frame. Both are worth showing on a clock this page
         is actually driven by. */
      const orbit=tk%ORBIT;
      set("mlane", orbit%FULL_RETURN===0 ? "full return"
                 : orbit%ROLE_FLIP===0   ? "role flip"
                 : orbit%LOCK===0        ? "lock"
                 : `tick ${orbit}/${ORBIT}`);
      shown=0; dropped=0; decMs=0; decN=0; lastTick=tk;
    };

    /* Each worker runs its own loop: ask for whatever the clock wants NOW, wait,
       present or drop, repeat. No scheduler, no shared queue, no coordination —
       the same order-independence the GPU pool relies on. */
    /* ── FLYING WINDOWS ─────────────────────────────────────────────────────
       Several windows onto ONE inscription, drifting, each reading only its own
       addresses. This is not a visual trick layered on top of the format — it is
       the format's own arithmetic made visible: a 256x256 window resolves 1,424
       addresses, 0.02% of a frame, so a dozen of them cost a fraction of the one
       picture they are cut from. Nothing is cropped and nothing is re-encoded;
       each window is an independent read of the same addresses.

       Every window also holds its OWN playhead, offset around the clip, so they
       show different moments at once. Any frame costs the same to reach, so a
       window seeking somewhere else is free — a codec with a prediction chain
       could not do this at all. */
    const WINDOWS = WINDOWS_MAX;
    /* Three, from the 3x3 tower grid's three chiral streams (A/B/C =
       past/now/future), not from a preference for thirds. */
    const GROUPS = CPU_GROUPS;
    const bwB = ready.bw, bhB = ready.bh, tile = ready.bs >> L;
    const win = Array.from({length:WINDOWS},(_,i)=>{
      /* Edge follows the COUNT, not a fixed seventh — three windows at a
         seventh of the field each would leave the screen mostly empty. */
      const wb = Math.max(3, Math.round(bwB / (WINDOWS + 1)));
      const hb = Math.max(2, Math.round(wb*9/16));
      return { i, wb, hb,
               x: Math.random()*(bwB-wb), y: Math.random()*(bhB-hb),
               vx:(Math.random()-.5)*0.18, vy:(Math.random()-.5)*0.12,  // per TICK, not per decode
               /* The playhead lives on the GROUP, not on the window — see
                  `heads` below. Keeping one per window meant they drifted apart
                  on their own completions within a few seconds, so the sharing
                  that was supposed to amortise fetching stopped holding almost
                  immediately and the residency cap thrashed against seven
                  distinct frames. */
               g: i % GROUPS,
               img:null, px:0, py:0 };
    });

    /* ── THREE PLAYHEADS, AND THE THREE ARE NOT ARBITRARY ────────────────────
       I picked "thirds" out of nothing and it turns out to be the substrate's
       own count: the 3x3 tower grid runs A/B/C = FORWARD_GENERATIVE (past) /
       RETURN (now) / REVERSE (future) — three chiral streams sharing one
       conductor spine (mechanics note 01, section 3, run-verified). Three
       windows onto three moments of one inscription is that grid, not a layout
       choice.

       A GROUP'S HEAD ADVANCES ONCE PER ROUND, not once per completion. Advancing
       per completion is what let the groups drift apart: window 0 and window 3
       start on the same frame, finish at different times, and are two frames
       apart by the next round. The head now moves when every window in the group
       has taken delivery of the current one, so the group genuinely shares a
       frame and the receiver's cache is holding three frames rather than seven.

       RESIDENCY IS THEN BOUNDED BY THE CLOCK, not by a cap nobody checks: three
       playheads, one frame each in flight, is the 1-3 frames this pipeline is
       supposed to hold. It is REPORTED from `evs_cache_len()` rather than
       asserted in a comment — "instantly deleted" is a measurement or it is
       nothing. */
    const heads = Array.from({length:GROUPS},(_,g)=>Math.floor(g * frames / GROUPS));
    const owed  = Array.from({length:GROUPS},(_,g)=>win.filter(w=>w.g===g).length);
    const takeHead = g => heads[g];
    const doneWith = g => { if(--owed[g] <= 0){ heads[g]=(heads[g]+1)%frames;
                                                owed[g]=win.filter(w=>w.g===g).length; } };
    /* Windows are the default view; `?view=full` gives the single full frame.
       The tint that held this back was never a chroma bug: evs_frame_region takes
       OUTPUT SAMPLES and evs_ref_window_rgba takes BLOCKS, and I was passing block
       coordinates to both — so the region was an 18x10 SAMPLE box, 76 addresses
       instead of ~2,400, and the near-empty result read as pure colour. */
    let rr = 0;
    let windowed = windowedWanted;   // one law, module scope — see its comment

    const drift=w=>{
      w.x+=w.vx; w.y+=w.vy;
      if(w.x<0||w.x>bwB-w.wb){ w.vx*=-1; w.x=Math.min(Math.max(w.x,0),bwB-w.wb); }
      if(w.y<0||w.y>bhB-w.hb){ w.vy*=-1; w.y=Math.min(Math.max(w.y,0),bhB-w.hb); }
    };

    const paint=()=>{
      const W=bwB*tile, H=bhB*tile;
      if(cv.width!==W||cv.height!==H){ cv.width=W; cv.height=H; }
      ctx.fillStyle="#07070a"; ctx.fillRect(0,0,W,H);
      for(const w of win){
        if(!w.img) continue;
        if(PAINT_CPU){
          /* no shadow filter: a 28px blur per window per paint is a real cost
             on exactly the devices this mode exists for */
          ctx.drawImage(w.img, w.px*tile, w.py*tile);
        } else {
          ctx.save();
          ctx.shadowColor="rgba(0,0,0,.85)"; ctx.shadowBlur=28;
          ctx.drawImage(w.img, w.px*tile, w.py*tile);
          ctx.restore();
        }
        ctx.strokeStyle="rgba(255,180,84,.55)"; ctx.lineWidth=Math.max(1,tile/12);
        ctx.strokeRect(w.px*tile, w.py*tile, w.wb*tile, w.hb*tile);
      }
    };

    if(windowed){
      const winPx = `${win[0].wb*tile}×${win[0].hb*tile}`;
      set("mfocus", `${WINDOWS} windows · ${winPx}`);
      /* The prose said "256x256" for windows that are nothing of the sort. The
         size is the one the windows are actually cut at, at the rung actually in
         use — otherwise the sentence quotes a cost for a window nobody is
         looking at. */
      { const e=$("cWinPx"); if(e) e.textContent = winPx; }
      pool.forEach(async (wk2,k)=>{
        for(;;){
          /* Round-robin by worker index only. Selecting with performance.now()
             meant two workers could pick the SAME window and race on w.img,
             closing a bitmap the other had just published. Deterministic. */
          const w = win[(k + rr++) % WINDOWS];
          const bx0=Math.round(w.x), by0=Math.round(w.y);
          /* FOLLOW ARRIVALS — do not chase an index on a local clock.
             Settled earlier today in 7069073 and measured then: a playhead that
             walks a clock index "walked past frames that had not arrived, missed,
             and painted nothing — 5 fps while decode held 24. A feed has no
             future to seek into." The fix was to take the next frame actually
             obtainable and bound latency by BUFFER SIZE rather than index
             arithmetic, and it measured zero misses, every tick paints.

             I reintroduced the bug with `(tickNow()+off) % frames`. The head
             still moves only on COMPLETED work, so a window asks only for what it
             can take delivery of — but it is the GROUP's head now, advanced once
             the whole group has been served rather than once per window. Latency
             is bounded by the one request in flight per worker, and residency by
             the three group heads. */
          const t=takeHead(w.g);
          const d=await new Promise(r=>{ wk2.onmessage=e=>r(e.data);
            wk2.postMessage({cmd:"win", t, level:L, id:w.i,
                             bx0, by0, bx1:bx0+w.wb, by1:by0+w.hb, seq:t,
                             // where this group's playhead goes next, so the
                             // worker can pull it while this one resolves
                             nextT:(t+1)%frames}); });
          if(d&&d.rgba&&d.ww){
            /* Update CONTENT only. Painting belongs to the 60 Hz loop below —
               calling paint() here made the display rate equal the decode rate,
               which is the same mistake as driving the playhead off decode
               completion. The clock is 60; the picture inside a window arrives
               when it arrives. */
            /* AN ImageBitmap IS NOT GARBAGE COLLECTED ON REASSIGNMENT.
               It holds an external allocation and must be closed explicitly.
               Overwriting w.img without closing leaked one bitmap per window per
               frame — at ~20 fps across 7 windows that is 140 live bitmaps a
               second, never released, and the page degrades from slow to stopped
               rather than settling at a low rate. That decay is exactly the
               signature: a leak, not a throughput limit.

               This is also why the short clip looked fine and the long one did
               not — the same leak, but the short clip had far fewer distinct
               frames to hold before it looped. */
            if(PAINT_CPU){
              /* reuse one canvas per window; putImageData copies straight from
                 the transferred worker buffer — nothing allocated per frame */
              if(!w.cvs || w.cvs.width!==d.ww || w.cvs.height!==d.wh){
                w.cvs=document.createElement("canvas");
                w.cvs.width=d.ww; w.cvs.height=d.wh;
                w.cctx=w.cvs.getContext("2d");
              }
              w.cctx.putImageData(
                new ImageData(new Uint8ClampedArray(d.rgba.buffer), d.ww, d.wh),0,0);
              w.img=w.cvs;
            } else if(!STAGE_NONE){
              const prev = w.img;
              w.img = await createImageBitmap(
                new ImageData(new Uint8ClampedArray(d.rgba.buffer), d.ww, d.wh));
              if (prev) prev.close();
            }
            w.px=bx0; w.py=by0;
            shown++; decMs+=d.ms||0; decN++;
            if(d.wire!==undefined) wireBy.set(k,d.wire);   // per WORKER, summed later
            if(d.resident!==undefined) resBy.set(k,d.resident);
            winResolves++;
            msF+=d.msFetch||0; msU+=d.msUnpack||0; msR+=d.msResolve||0;
            if(d.selMs!==undefined){ selBy.set(k,d.selMs); netBy.set(k,d.netMs); reqBy.set(k,d.netReq); }
            if(d.hits!==undefined){ hitBy.set(k,d.hits); missBy.set(k,d.misses); }
            set("mt",`${d.frame}`); set("maddr",nf(d.addrs||0));
          }
          /* The group's head moves only once every window in it has been served,
             so the three heads stay together instead of fanning out into seven.
             Outside the `if`, because a dropped or pending result must still
             release the group — otherwise one failure stalls that playhead for
             good. */
          doneWith(w.g);
        }
      });

      /* ── PAINT ON THE CLOCK, NOT ON THE DECODER ────────────────────────────
         The composition runs flat at the tick rate; window CONTENTS refresh
         whenever a resolve lands. Painting inside the worker loop made display
         rate equal decode rate, which is the same error as driving the playhead
         off decode completion — I fixed that once for the full-frame path and
         then reintroduced it here.

         Drift happens here too, so the motion is smooth at 60 even while the
         pictures inside arrive at 8-20. That separation is the whole reason it
         can look fluid on a CPU: geometry is cheap and on the clock, content is
         expensive and asynchronous. */
      let painted=0, lastPaintT=performance.now();
      const frameLoop=()=>{
        for(const w of win) drift(w);
        if(!STAGE_NONE) paint();
        painted++;
        const now=performance.now();
        if(now-lastPaintT>=1000){
          set("mfps",(painted*1000/(now-lastPaintT)).toFixed(0)); // paint: flat
          painted=0; lastPaintT=now;
        }
        requestAnimationFrame(frameLoop);
      };
      requestAnimationFrame(frameLoop);

      for(;;){ readout(); await new Promise(r=>setTimeout(r,LOCK*1000/RATE)); }
    }

    pool.forEach(async (w,k)=>{ for(;;){ present(await ask(w,wanted()),k); } });
    // the readout samples on the clock too, at LOCK cadence, refreshing on REALIGN
    for(;;){ readout(); await new Promise(r=>setTimeout(r,LOCK*1000/RATE)); }
  }
  /* Ask the device what it can actually hold before allocating anything. The
     resolve costs 32 bytes per pixel of VRAM (an RGBA32I accumulator, ping-ponged
     for the butterfly), so a field the GPU cannot fit does not run slowly — it
     runs at zero frames a second with no error, which is the worst way for a
     limit to announce itself. Starting at the finest rung this GPU agreed to is
     not a degraded picture: it is a smaller output, which the format produces
     natively from the same addresses. */
  const LIM=G.limits(bw,bh,bs,levels);
  G.setup(w,h,bw,bh,bs,LIM.level);

  /* SMOOTHNESS IS A RUNG CHOICE, and the only honest way to make it is to
     measure. A 35-megapixel field resolved natively is heavy on any GPU; the
     same addresses resolved one rung down are a quarter of the work and look
     identical on a screen that is not 8K anyway.
     So the player times its own resolve and settles on the finest rung it can
     actually sustain, instead of opening at native and stuttering. This is not a
     fallback — it is what the format is for: one inscription, the output the
     device can afford, chosen at play time. */
  /* MEASURE THE OUTCOME, NOT A PROXY.
     The first version of this timed `resolvePaint` and read 0.3 ms while the page
     was managing 5.9 frames a second — because GL calls RETURN on submission and
     the GPU does the work later. Timing submission measures how fast we can ask,
     not how fast it is done, so the adaptor never stepped down and an 8K field
     just crawled.
     The achieved frame interval is the only number that cannot lie about this:
     it already contains decode, submission, execution and present. */
  let settled = false, sinceStep = 0, achieved = RATE;

  // ── the jitter buffer ────────────────────────────────────────────────────
  // Workers return out of order — that is fine and is the point. Frames are
  // order-independent, so the buffer reorders by index with nothing to reconcile.
  /* Bytes this client has actually pulled off the wire, counted by the workers
     that pulled them — not inferred from the container. Each worker fetches its
     own frames and so only knows its own total; the client's figure is the sum,
     and reporting one worker's share as the whole would understate it by the
     pool size. */
  const wireBy=new Map();
  const wireTotal=()=>{ let s=0; for(const v of wireBy.values()) s+=v; return s; };
  const buf=new Map();              // t -> {pts, bytes, survived}
  let mosaic=false;
  /* FOCUS. The window a constrained receiver actually holds. Expressed in output
     samples at the current rung, centred, and sent with every request so the
     worker resolves only the blocks it touches — the addresses outside it are
     never read and never transmitted. */
  let focus=0;                       // 0 = whole field, else the window edge
  /* THE OPENING VIEW IS THE ONE THE WIRE CAN CARRY. Whole-field native 4K60
     needs ~284 Mb/s; a native-detail window needs ~2.3 Mb/s — the page's own
     panel prices both. The 566 MP public clip never faces this choice: no GPU
     opens it native, so it is FORCED coarse; a 4K clip opens native and
     drowns a home line at 9 fps (owner report, twice). So the page opens at
     the 1024 window AFTER the boot self-check has its verdict at whole field
     (the check's CPU reference is whole-field; comparing it against a
     windowed canvas mistakes a view change for corruption). `?focus=0` opens
     whole-field; F cycles as ever. */
  let START_FOCUS = 1024;
  {
    const f = new URLSearchParams(location.search).get("focus");
    if (f !== null) START_FOCUS = Math.max(0, +f | 0);
  }
  const focusRgn=()=>{
    if(!focus) return null;
    const ow=w>>level, oh=h>>level;
    const s=Math.min(focus,ow,oh);
    const x0=(ow-s)>>1, y0=(oh-s)>>1;
    return [x0,y0,x0+s,y0+s];
  };
  /* how much of the channel is being destroyed, and which lane takes it */
  let permille=0, armour=1;
  /* Open one rung below native when the field is very large. The adaptor will
     climb if the device can take it; starting heavy and stuttering makes a first
     impression that no later recovery undoes. */
  let level=LIM.level;                     // open at the finest the GPU can hold
  const openLevel=level;
  let decodedInWindow=0, decWindowT=performance.now();
  /* the mosaic shows sixteen playheads at once, so it needs sixteen frames
     resident rather than one — the buffer grows to match the view */
  /* IN FLIGHT = TWO PER DECODER. `POOL+1` keeps every worker busy exactly once and
     leaves a hole the size of one round trip between finishing a frame and being
     handed the next: the worker goes idle while the main thread notices. One
     queued behind each in-progress frame removes that hole. Still nothing held
     back for display — this is the number being WORKED ON, and the paint step
     drops anything older than what it shows. */
  const depth=()=>mosaic?Math.max(AHEAD,40):Math.max(AHEAD,POOL*2);
  let head=0;                        // next frame to request
  let play=0;                        // next frame to show
  let inflight=0, seq=0;
  const LIVE=!!new URLSearchParams(location.search).get("live");
  let skipped=0;

  /* WHERE THE CLOCK SAYS WE ARE. Playback is 60 ticks a second whatever the
     decoder manages; this is the frame that SHOULD be on screen now. */
  const wallT0 = performance.now();
  const clockFrame = () => Math.floor((performance.now() - wallT0) / 1000 * RATE) % frames;

  function pump(){
    if(LIVE) return;                 // frames arrive when the feed sends them
    /* REQUEST WHAT THE CLOCK WANTS, NOT THE NEXT ONE IN LINE.
       `head` walked `head++` from zero, so a decoder running at 10 fps against a
       60 fps clock spent its whole life on frames the playhead passed minutes ago
       — it was not dropping, it was playing in slow motion and calling the
       backlog a buffer. Every frame here costs the same to reach and depends on
       nothing before it, so jumping the request head to the clock is free; a
       codec with a prediction chain could not do it at all.
       Anything already behind the clock is discarded rather than decoded. */
    /* DO NOT PRUNE ON ARRIVAL AGE. I did, and it deadlocked at 0/3 frames: a
       decode takes ~100 ms, which is six frames at 60 Hz, so EVERY arrival is
       already "behind the clock" and was deleted before it could be painted. The
       buffer could never fill and nothing ever drew.
       Being behind the clock is the normal state of a decoder — it is latency,
       not staleness. What must not accumulate is frames older than the one
       already SHOWN, and those are dropped at paint time where the comparison is
       meaningful. Here the clock does one job: aim the REQUESTS. */
    /* FOLLOW ARRIVALS, DO NOT CHASE THE CLOCK.
       Jumping the request head to the wall clock is correct real-time playback and
       it LOOKS WRONG: a device decoding ~10 fps against a 59.94 fps source paints
       every sixth frame, which reads as fast, jerky motion rather than as video.
       The owner's report — "skips ahead, too fast, not smooth" — is that trade
       showing on screen, and smooth is what has been asked for every time.
       So the head walks, and playback is continuous at whatever rate the decoder
       sustains. It is slower than real time when the device cannot keep up, and
       that is the honest failure mode for this medium: every frame here is
       independent, so nothing drifts or tears — it simply runs at the speed the
       hardware can resolve. Closing the gap to 60 is decode throughput, not
       scheduling, and no amount of playhead cleverness substitutes for it. */
    while(inflight<POOL*2 && buf.size+inflight<depth()){
      const t=head%frames; head++;
      workers[t%POOL].postMessage({cmd:"decode",t,level,seq:++seq,permille,armour,rgn:focusRgn()});
      inflight++;
    }
  }
  /* How far behind the live edge the playhead is allowed to sit. Small, because
     latency IS the product here — a live feed that lets its buffer grow is a
     recording with extra steps, and that is a criticism of the client as much as
     of the ingest. */
  const LIVE_LEAD = 3;

  for(const wk of workers) wk.addEventListener("message",e=>{
    const d=e.data; if(d.frame===undefined) return;
    inflight--;
    if(d.wire!==undefined) wireBy.set(d.id,d.wire);
    if(d.pending){ pump(); return; }   // live: that frame does not exist yet
    buf.set(d.frame,d);   // a frame carries its own level; no need to discard on a switch
    decodedInWindow++;
    if(LIVE){
      /* DROP, do not queue. If the display cannot keep up with the feed the
         answer is to skip to the edge, not to fall further behind holding every
         frame in between. Skipping costs exactly one frame here, because no
         frame is defined in terms of any other — there is nothing to resync to. */
      /* Bound latency by size, not by index arithmetic: keep the newest few and
         drop the rest. Dropping costs exactly one frame each, because no frame is
         defined in terms of any other — there is nothing to resync to. */
      if(buf.size>LIVE_LEAD){
        const ks=[...buf.keys()].sort((a,b)=>a-b);
        for(const t of ks.slice(0,ks.length-LIVE_LEAD)){ buf.delete(t); skipped++; }
      }
    }
    pump();
  });

  /* Moving the damage dial invalidates every frame already decoded AND the figure
     they produced. Frames requested at the old setting are still in flight and
     will land in the same slots; dropping the figure here means the readout says
     "measuring…" until one decoded at the new setting arrives, instead of quietly
     showing the old one. */
  function redial(){ lastSurv=null; buf.clear(); head=play; pump(); }

  /* Step toward the finest rung this device sustains. Hysteresis is wide on the
     way back up so it cannot oscillate between two rungs — a picture that keeps
     changing size is worse than one that settled on the wrong rung. */
  function adapt(){
    if(userPinned) return;
    if(++sinceStep < 36) return;               // ~1.5 s of evidence per decision
    /* AT MOST ONE RUNG BELOW WHERE WE OPENED.
       Cost here is per-ADDRESS and per-frame, not per-pixel: measured, 3,600
       output pixels ran no faster than 14,400, and an empty frame costs the same
       as one with 3,000 addresses. So shrinking the OUTPUT buys almost nothing —
       it just throws away the resolution that is the entire point. Anything past
       one rung is the adaptor solving the wrong problem loudly. */
    /* DROP FRAMES, DO NOT DROP RESOLUTION. Stepping DOWN is removed.
       The measurement that settles it is this codebase's own (7069073): 1280x720
       / 160x90 / 80x45 ran at 5.9, 14, 14 fps — FOUR TIMES fewer pixels bought
       NOTHING, because the cost is per-address and per-frame, not per-pixel. So
       the down-step cannot buy rate; all it does is make the picture blurry,
       which is what the owner saw and reported as "it got blurry and did the same
       thing". A stall answered by degrading the one thing the page exists to
       demonstrate is the worst available trade.
       When the device cannot sustain the rate it now SKIPS FRAMES instead —
       nothing here is a difference from another frame, so a dropped frame costs
       nothing downstream and the next one arrives at full detail. Stepping UP is
       kept: that is the adaptor finding detail it can afford, not hiding from a
       problem. */
    if(false){
      sinceStep=0; settled=false; setLevel(level+1);
    } else if(achieved > RATE*0.95 && level > LIM.level && !settled){
      sinceStep=0; setLevel(level-1);
      // if stepping up costs us the rate we come straight back down, and that
      // round trip is what tells us the previous rung was already the right one
      settled=true;
    }
  }
  function setLevel(L){ level=L; sinceStep=0; head=play; pump(); paintLadder(); }

  let userPinned=false;
  function changeLevel(L){
    if(L===level) return;
    userPinned=true;              // a hand on the dial outranks the heuristic
    setLevel(L);
  }

  // ── prove the GPU path, then start ───────────────────────────────────────
  //
  // The reference resolve is NATIVE — `evs_ref_luma` places addresses at full
  // scale — so it can only be compared against a GPU resolve at the same scale.
  // When the device could not hold a native accumulator the two are different
  // pictures, and comparing them reports a failure that is really a scale
  // mismatch. Say the check did not run rather than print a number that means
  // nothing; a verifier that lies about its own applicability is worse than one
  // that abstains.
  if(LIM.level>0){
    $("mver").textContent=`n/a · GPU caps at ${w>>LIM.level}×${h>>LIM.level}`;
    $("mver").className="v";
    say(`this GPU holds ${LIM.acc} — opening at that rung`);
  } else
  await new Promise(res=>{
    workers[0].addEventListener("message",function once(e){
      if(!e.data || !e.data.ref) return;
      workers[0].removeEventListener("message",once);
      const ref=e.data.ref;
      inflight++;                       // the shared listener decrements for this one too
      workers[0].postMessage({cmd:"decode",t:0,level:0,seq:0,permille:0,armour:1});
      const h2=ev=>{ const d=ev.data; if(d.frame!==0) return;
        workers[0].removeEventListener("message",h2);
        G.resolvePaint(d.pts,0,0,0,w,h,0);
        const v=G.verifyLuma(ref,w,h);
        $("mver").textContent = v.bad===0 ? `exact · ${nf(v.checked)} px checked`
                                          : `${v.bad}/${v.checked} differ (max ${v.worst})`;
        $("mver").className = v.bad===0 ? "v ok" : "v bad";
        res();
      };
      workers[0].addEventListener("message",h2);
    });
    workers[0].postMessage({cmd:"ref",t:0});
  });

  /* verdict in — open at the window the wire can carry */
  if(START_FOCUS !== 0) focus = START_FOCUS;

  // ── the format ladder ────────────────────────────────────────────────────
  const LADDER=Array.from({length:levels},(_,i)=>i);
  const ladderEl=$("ladder");
  const rows=LADDER.map(L=>{
    const el=document.createElement("button");
    el.className="lrow"; el.dataset.level=L;
    el.innerHTML=`<span class="ln">${w>>L}<i>×</i>${h>>L}</span><span class="lb">—</span>`;
    if(L<LIM.level){ el.disabled=true; el.style.opacity=.35;
      el.title=`needs a ${(2*(bw*(bs>>L))*(bh*(bs>>L))*16/1048576)|0} MB accumulator — this GPU caps at ${(LIM.vram/1048576)|0} MB`; }
    else el.onclick=()=>changeLevel(L);
    ladderEl.appendChild(el); return el;
  });
  function paintLadder(){ rows.forEach((el,i)=>el.classList.toggle("on",LADDER[i]===level)); }
  paintLadder();
  // state each format's wire cost before it is chosen, measured on a real frame
  await new Promise(res=>{
    workers[0].addEventListener("message",function once(e){
      if(!e.data||!e.data.sizes) return;
      workers[0].removeEventListener("message",once);
      e.data.sizes.forEach((b,i)=>{ rows[i].querySelector(".lb").textContent=kb(b); });
      res();
    });
    workers[0].postMessage({cmd:"sizes",t:Math.min(20,frames-1)});
  });

  // ── playback: a fixed clock, independent of decode ───────────────────────
  let running=true, shown=0, fpsT=performance.now(), fpsN=0;
  let acc=0, lastT=performance.now(), lastBytes=0, effRate=RATE, thru=RATE;
  /* The recovery figure belongs to the settings it was measured under, so it is
     held as the whole frame's report — count, total, and the dial it was decoded
     at — and discarded the moment the dial moves. Showing a number from a frame
     damaged at some other level is worse than showing nothing. */
  let lastSurv=null, lastEvents=0, lastFull=0;
  /* addresses a whole frame carries at each rung, measured once, so the focus
     window's cost can be stated as a share rather than a bare count */
  const fullEvents={};

  function draw(now){
    requestAnimationFrame(draw);
    const dt=now-lastT; lastT=now;
    if(running) acc+=dt;

    /* Play at the rate the decoders actually sustain. A buffer that is draining
       means the machine cannot hold 50 fps, and slowing the clock looks like
       slower motion; refusing to slow it looks broken. */
    const step=1000/effRate;
    if(acc>=step){
      acc=Math.min(acc-step, step*3);
      /* A FILE has a future; a FEED does not. Driving the playhead off a local
         clock is a sequential-media assumption: it walks `play` forward into
         frames that have not arrived, misses, and paints nothing — measured at
         5 fps while the GPU sat at 0.5 ms and decode held 24 fps.
         So in live the playhead follows ARRIVALS. Take the oldest frame at or
         after `play`; if none has come yet, wait rather than running ahead.
         Nothing is lost by waiting, because no frame is defined in terms of any
         other — there is no chain to fall out of. */
      let key=null;
      /* TAKE THE OLDEST FRAME PRESENT — IN BOTH MODES.
         7069073 established this for a live feed: "it chased an index on a local
         clock, walked past frames that had not arrived, missed, and painted
         nothing — 5 fps while decode held 24." The fix was to show the oldest
         thing actually in hand. It was never applied to PLAYBACK, and playback
         had the identical bug in a quieter form: `key = play % frames` paints only
         if THAT exact frame is present, and `play` only advances when it paints.
         So a decoder that falls behind leaves the playhead waiting on one frame
         while newer ones sit in the buffer unshown — it does not drop, it stalls.
         That is the stall being reported.
         Nothing here is defined in terms of another frame, so a skipped frame
         costs nothing downstream: no drift, no artefacts, no recovery. Taking the
         oldest present and moving `play` past it means the picture keeps up by
         DROPPING rather than by waiting — and at full detail, because the rung is
         no longer what gives way. */
      /* PAINT THE NEWEST FRAME THAT IS NOT AHEAD OF THE CLOCK, not the oldest
         thing in hand — the oldest is the most stale, and showing it is how a
         backlog becomes slow motion. Ahead-of-clock frames are kept for their
         tick; everything behind is already gone from the buffer above. */
      if(LIVE){
        let best=Infinity;
        for(const t of buf.keys()) if(t<best) best=t;
        if(best!==Infinity) key=best;
      } else {
        // the oldest frame in hand — continuous motion, one paint per arrival
        let best=Infinity;
        for(const t of buf.keys()) if(t<best) best=t;
        if(best!==Infinity) key=best;
      }
      const f=key===null?null:buf.get(key);
      if(f){
        buf.delete(key);
        /* Everything OLDER than what we just showed is unshowable — dropping it
           here is what keeps a backlog from forming, and it is safe because the
           comparison is against a frame that actually reached the screen. */
        for(const t of [...buf.keys()]){
          const d=(key-t+frames)%frames;
          if(d>0 && d<frames/2){ buf.delete(t); skipped++; }
        }
        if(LIVE) play=key;   // report where we are; nothing reads it back
        if(STAGE_NONE){
          /* probe: retire the frame without presenting it — counters stay live */
        } else if(mosaic){
          G.clear();
          const cols=4,rows_=4,pw=(cv.width/cols)|0,ph=(cv.height/rows_)|0;
          for(let i=0;i<16;i++){
            const g=buf.get((play+Math.floor(i*frames/16))%frames)||f;
            const gl_=Math.max(2,g.level);
            G.resolvePaint(g.pts,gl_,(i%cols)*pw,cv.height-((i/cols|0)+1)*ph,pw,ph,-1);
          }
        } else {
          G.resolvePaint(f.pts,f.level,0,0,cv.width,cv.height,-1);
          adapt();
        }
        lastBytes=f.bytes; lastEvents=f.events;
        if(!f.rgn) fullEvents[f.level]=f.events;
        lastFull=fullEvents[f.level]||f.events;
        // only a frame decoded at the CURRENT dial may speak for the current dial
        if(f.permille===permille && f.armour===armour && f.survived!==null)
          lastSurv={n:f.survived, of:f.events, armour:f.armour};
        // move PAST what was shown, so frames the decoder never delivered are
        // skipped instead of waited on
        if(!LIVE) play=(key+1)%frames;
        shown++; fpsN++;
      }
      pump();
    }

    if(now-fpsT>500){
      const s=(now-fpsT)/1000;
      thru=0.6*thru + 0.4*(decodedInWindow/((now-decWindowT)/1000));
      effRate=Math.max(6, Math.min(RATE, buf.size>depth()*0.6 ? RATE : thru*0.92));
      achieved = achieved*0.5 + (fpsN/s)*0.5;
      $("mfps").textContent=(fpsN/s).toFixed(0);
      $("mdps").textContent=thru.toFixed(0);
      $("mbuf").textContent=buf.size;
      $("mt").textContent=nf(play%frames);
      $("mbytes").textContent=kb(lastBytes);
      const fo=$("mfocus");
      if(fo) fo.textContent = focus
        ? `${focus}² · ${(100*lastEvents/Math.max(1,lastFull)).toFixed(2)}% of addresses`
        : "whole field";
      const ad=$("maddr"); if(ad) ad.textContent=nf(lastEvents);
      /* Bytes are reported beside addresses and never derived from them. A window
         resolves a fraction of the addresses but still costs the whole segment
         range on the wire, so showing one figure where a reader assumes the other
         is the overstatement this pair exists to prevent. */
      const wi=$("mwire"); if(wi) wi.textContent=`${kb(lastBytes)} · ${kb(wireTotal())} pulled`;
      const dial=$("mdestroy"), lane=$("mlane"), surv=$("msurv");
      if(dial) dial.textContent=(permille/10).toFixed(1)+"%";
      if(lane) lane.textContent=armour?"armoured":"bare";
      if(surv){
        if(!permille){ surv.textContent="—"; surv.className="v ok"; }
        else if(!lastSurv){ surv.textContent="measuring…"; surv.className="v"; }
        else{
          const all=lastSurv.n===lastSurv.of;
          surv.textContent=all ? `${nf(lastSurv.n)} / ${nf(lastSurv.of)} exact`
                               : `${nf(lastSurv.n)} of ${nf(lastSurv.of)}`;
          surv.className="v "+(all?"ok":"bad");
        }
      }

      fpsN=0; fpsT=now; decodedInWindow=0; decWindowT=now;
    }
  }

  $("eyebrow").textContent=
    `${w}×${h} · ${nf(frames)} frames · opened with ${kb(headerBytes.byteLength+indexBytes.byteLength)}`;

  /* THE HEADLINE NUMBERS ARE DERIVED, NOT TYPED.
     They used to be literals in the HTML, which was fine until the clip changed:
     a 566-megapixel field was still advertised as "35.4 megapixels" at "185 Mb/s",
     numbers computed for a different clip entirely. A page that states a figure
     the file contradicts is worse than a page that states none, so these now come
     from the header and the index — the same two files the receiver opens with.

     Rates are per-second at the clip's rate, from the MEASURED mean frame length
     (the index is the authority: its stride is fixed, so total/frames is exact).
     The window figure scales by area, which is the honest first-order estimate —
     a 256² window is not guaranteed to be exactly its area share of the bytes,
     so it is labelled as the area share it is. */
  fillFigures(w, h, frames);
  /* The GPU path's "native-detail window" is the F-key focus, and the copy must
     name the one the ring actually starts a viewer on rather than a size typed
     into the prose. Set here and again on every F press, so the sentence and the
     view never disagree. */
  const setWinPx = () => { const e=$("cWinPx"); if(e) e.textContent =
    focus ? `${focus}×${focus}` : `${w}×${h}`; };
  setWinPx();
  $("mframes").textContent=nf(frames);
  $("mpool").textContent=`${POOL} locked`;
  $("mmode").textContent="";

  addEventListener("keydown",e=>{
    if(e.code==="Space"){e.preventDefault(); running=!running;}
    if(e.key==="m"||e.key==="M"){ mosaic=!mosaic; $("mmode").textContent=mosaic?"16 live views":"single"; }
    if(e.key>="1"&&e.key<="9"&&+e.key<=levels&&(+e.key-1)>=LIM.level) changeLevel(+e.key-1);
    if(e.key==="f"||e.key==="F"){
      const ring=[0,1024,512,256,128];
      focus=ring[(ring.indexOf(focus)+1)%ring.length];
      setWinPx();
      buf.clear(); head=play; pump();
    }
    if(e.key==="a"||e.key==="A"){ armour=armour?0:1; redial(); }
    if(e.key==="ArrowRight"||e.key==="ArrowUp"){ e.preventDefault();
      permille=Math.min(500,permille+25); redial(); }
    if(e.key==="ArrowLeft"||e.key==="ArrowDown"){ e.preventDefault();
      permille=Math.max(0,permille-25); redial(); }
    if(e.key==="s"||e.key==="S"){
      const t0=performance.now();
      play=Math.floor(Math.random()*frames); head=play; buf.clear(); pump();
      $("mseek").textContent=`frame ${nf(play)} · ${(performance.now()-t0).toFixed(1)} ms to reset`;
    }
  });
  cv.addEventListener("pointerdown",()=>{running=!running});

  /* ── THE ACTS — the OMNIWALL choreography (?acts=1) ──────────────────────
     A state machine that dispatches the page's OWN controls on ORBIT
     boundaries (240 ticks = 4.000 s at 60 fps — the tower's full return times
     four). Nothing here is simulated: every act is a real keypress on the real
     handlers, so what the audience sees is exactly what a hand on the keys
     would get. Acts and their claims are the gated ones only (the plan doc's
     honesty ledger); the act titles overwrite the narration beat, which is the
     display surface already paced on this clock.
       I    the field            — one inscription, full bleed
       II   THE SHATTER          — M: sixteen live views of the same inscription
       III  resolution in motion — down the ladder and back, no re-encode
       IV   TIME SHATTER         — S: a new moment at the same cost, in mosaic
       V    destruction          — armour on, a quarter of the channel destroyed
       VI   recovery             — clean channel, back to the single field   */
  const ACTS = new URLSearchParams(location.search).get("acts");
  if (ACTS) {
    const press = k => dispatchEvent(new KeyboardEvent("keydown",
      k === " " ? {code: "Space"} : {key: k}));
    const SCRIPT = [
      ["ACT I — the field",
       "One inscription, full bleed. Every figure on this panel is derived " +
       "from the container's own prelude and index — nothing typed.", []],
      ["ACT II — THE SHATTER",
       "Sixteen live views of the SAME inscription, each reading only its own " +
       "addresses. No stream switch, no re-encode: different byte ranges of " +
       "one file.", ["m"]],
      ["ACT III — resolution in motion",
       "Down the ladder while playing: a smaller output reads FEWER " +
       "addresses, never other ones.", ["3"]],
      ["ACT III — and back up",
       "Native detail again. The size dial cost no re-encode and no second " +
       "download — the same inscription serves every rung.", ["1"]],
      ["ACT IV — TIME SHATTER",
       "A new moment, cold, at the same cost: there are no reference frames, " +
       "so a seek is one fetch, not a group of pictures.", ["s"]],
      ["ACT V — destruction",
       "Armour on; a quarter of the channel destroyed, live. The carrier " +
       "decodes exactly through 1,023 flips per row — the readout counts what " +
       "survived.", ["a", "ArrowRight", "ArrowRight", "ArrowRight",
                     "ArrowRight", "ArrowRight", "ArrowRight", "ArrowRight",
                     "ArrowRight", "ArrowRight", "ArrowRight"]],
      ["ACT VI — recovery",
       "The channel clean again, the field whole. Any frame, cold, same cost " +
       "— stored once, as addresses.",
       ["ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft",
        "ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft",
        "a", "m"]],
    ];
    const ORBIT_MS = 240 * 1000 / RATE;
    let act = -1;
    const stage = () => {
      act = (act + 1) % SCRIPT.length;
      const [head, body, keys] = SCRIPT[act];
      // keys spread across the first half of the orbit, one per LOCK delay
      keys.forEach((k, i) => setTimeout(() => press(k), i * (6 * 1000 / RATE)));
      // overwrite the narration beat after its own fade settles
      setTimeout(() => {
        const h = $("beathead"), b = $("beatbody");
        if (h) h.textContent = head;
        if (b) b.textContent = body;
      }, 600);
    };
    stage();
    setInterval(stage, ORBIT_MS);
  }

  /* ── LIVE ────────────────────────────────────────────────────────────────
     `?live=<ws url>` follows a feed instead of a file. The server pushes each
     frame record as it is appended; the client installs it with the SAME call it
     uses for a range fetch, because a record is a record.
     A joiner starts at whatever frame exists now. There is no keyframe to wait
     for — no frame is defined in terms of any other — so "tune in" costs one
     frame, not one group of pictures. */
  const liveURL=new URLSearchParams(location.search).get("live");
  if(liveURL){
    const ws=new WebSocket(liveURL); ws.binaryType="arraybuffer";
    let liveT=-1, got=0;
    ws.onmessage=ev=>{
      const d=new Uint8Array(ev.data);
      if(d.byteLength<8) return;
      const dv=new DataView(ev.data), tag=dv.getUint32(0,true);
      if(tag===0xE7C40000){ liveT=dv.getUint32(4,true); play=liveT; head=liveT;
        say(`live · joined at frame ${nf(liveT)}`); return; }
      if(tag!==0xE7C40001) return;                 // the header frame, already known
      const t=dv.getUint32(4,true), rec=ev.data.slice(8);
      workers[t%POOL].postMessage({cmd:"push",t,rec,level,seq:++seq,
                                   permille,armour,rgn:focusRgn()},[rec]);
      inflight++; got++;
      if(got===1){ play=t; head=t; }
    };
    ws.onclose=()=>say("live feed closed");
    ws.onerror=()=>say("live feed unreachable");
    $("mseek").textContent="live";
  }

  // fill the buffer before the first frame, so it opens smooth rather than stuttering
  if(!liveURL) pump();
  const t0=performance.now();
  while(!LIVE && buf.size<Math.min(AHEAD,frames) && performance.now()-t0<20000){
    bootBar.style.width=(100*buf.size/Math.min(AHEAD,frames))+"%";
    say(`buffering · ${buf.size}/${Math.min(AHEAD,frames)} frames · ${POOL} decoders locked`);
    await new Promise(r=>setTimeout(r,60));
  }
  boot.style.opacity=0; setTimeout(()=>boot.remove(),500);
  requestAnimationFrame(n=>{lastT=n;draw(n)});
})().catch(e=>{ const b=$("bootmsg"); if(b) b.textContent="failed: "+e.message; console.error(e); });
