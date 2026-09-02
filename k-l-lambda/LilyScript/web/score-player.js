/* LilyScript score player — client-side bridge to the lilylet-live-editor pipeline.
 *
 * Pipeline (all in the browser, no server round-trip):
 *   lyl text  --LilyletLib.parseCode + meiEncoder-->  MEI XML
 *   MEI       --Verovio WASM toolkit-->               SVG (preview) + MIDI (playback)
 *   MIDI      --music-widgets MidiPlayer + soundfont-->  audio + note highlight
 *
 * Globals provided by the vendored scripts (loaded via <script src> in <head>):
 *   window.LilyletLib   { parseCode, meiEncoder, serializeLilyletDoc }
 *   window.verovio      Verovio module factory (verovio-toolkit-wasm.js)
 *   window.musicWidgetsBrowser  { MIDI, MidiPlayer, MusicNotation, MidiAudio }
 *
 * Generation gate (the key UX rule): while the model is generating, we render
 * SVG-only and the MIDI player is hidden/disabled. The player is built + shown
 * only once generation has finished (LilyScore.setGenerating(false)). This keeps
 * the live preview cheap during streaming and avoids re-initialising the MIDI
 * engine on every measure-boundary editor sync.
 */
(function () {
	'use strict';

	const SOUNDFONT_URL = window.__LILYSCRIPT_SOUNDFONT_URL || './soundfont/';
	// Label for the in-panel renderer-loading spinner. app.py sets the i18n'd string on
	// window.__LILYSCRIPT_LOADING_RENDERER (matches the static placeholder's T('loading_renderer'));
	// fall back to English if it's absent (e.g. score-player.js loaded standalone).
	const LOADING_RENDERER_TEXT = window.__LILYSCRIPT_LOADING_RENDERER || 'Loading score renderer…';
	// Empty-state prompt shown when the renderer is ready but no score is loaded yet.
	const EMPTY_SCORE_TEXT = window.__LILYSCRIPT_EMPTY_SCORE || 'Generate a score, or click one from the Score List to view and play it here.';
	// Shown in the panel when verovio (the renderer) fails to load (network error). Clickable to retry.
	const RENDERER_FAILED_TEXT = window.__LILYSCRIPT_RENDERER_FAILED || 'Failed to load the score renderer. Click to retry.';
	// Large staff + treble-clef glyph for the empty-state placeholder. Inline SVG (no
	// asset fetch); currentColor so it inherits the muted placeholder color. The five
	// horizontal lines are the staff; the ♪/clef is rendered as a centered text glyph.
	const STAFF_ICON_SVG =
		'<svg class="ls-empty-icon" viewBox="0 0 120 80" width="120" height="80" aria-hidden="true" fill="none" stroke="currentColor">' +
		'<g stroke-width="2">' +
		'<line x1="8" y1="20" x2="112" y2="20"/>' +
		'<line x1="8" y1="32" x2="112" y2="32"/>' +
		'<line x1="8" y1="44" x2="112" y2="44"/>' +
		'<line x1="8" y1="56" x2="112" y2="56"/>' +
		'<line x1="8" y1="68" x2="112" y2="68"/>' +
		'</g>' +
		'<text x="22" y="60" font-size="56" stroke="none" fill="currentColor" font-family="serif">𝄞</text>' +
		'<g fill="currentColor" stroke="none">' +
		'<ellipse cx="74" cy="56" rx="7" ry="5" transform="rotate(-20 74 56)"/>' +
		'<rect x="80" y="26" width="2.4" height="30"/>' +
		'<ellipse cx="96" cy="44" rx="7" ry="5" transform="rotate(-20 96 44)"/>' +
		'<rect x="102" y="14" width="2.4" height="30"/>' +
		'<rect x="80" y="14" width="24" height="6" transform="skewX(-12)"/>' +
		'</g>' +
		'</svg>';

	const state = {
		toolkit: null,        // Verovio toolkit
		verovioReady: false,
		audio: null,          // { MIDI, MidiPlayer, MusicNotation, MidiAudio }
		audioReady: false,
		player: null,         // MidiPlayer instance
		midiData: null,
		generating: false,    // gate: true while the model streams
		lastCode: '',         // last lyl rendered (dedupe)
		lastMei: null,
		// playback
		isPlaying: false,
		currentTime: 0,
		duration: 0,
		playStartTime: 0,
		lastEventIndex: 0,
		pausedTime: 0,
		updateInterval: null,
		highlighted: new Set(),
	};

	const els = {};   // cached DOM nodes, filled by mount()

	const HIGHLIGHT_THROTTLE_MS = 50;
	let lastHighlightUpdate = 0;
	let lastAutoScroll = 0;

	function log (msg) { console.log('[LilyScore]', msg); }

	// Wait for a global (set by a vendored <script>) to appear. Resolves with the
	// value, or null on timeout. Needed because score-player.js now loads BEFORE the
	// 7.6MB verovio.bundle.js in <head> (so LilyScore is defined — and the player
	// mounts — early on a cold/slow load, instead of being blocked behind verovio's
	// download). The verovio-dependent paths therefore can't assume window.VerovioInit
	// exists yet; they await it here. Poll is cheap (100ms) and self-clearing.
	function waitForGlobal (name, timeoutMs) {
		if (window[name]) return Promise.resolve(window[name]);
		return new Promise(function (resolve) {
			var start = Date.now();
			var iv = setInterval(function () {
				if (window[name]) { clearInterval(iv); resolve(window[name]); }
				else if (timeoutMs && Date.now() - start > timeoutMs) { clearInterval(iv); resolve(null); }
			}, 100);
		});
	}

	// ---- Verovio init -------------------------------------------------------

	async function initVerovio () {
		if (state.verovioReady) return state.toolkit;
		if (state._verovioInitPromise) return state._verovioInitPromise;
		// Set the promise BEFORE the first await so concurrent callers (the mount-time
		// warmup + the first render) share ONE init and we never construct verovio twice.
		state._verovioInitPromise = (async function () {
			// verovio.bundle.js now loads after us; wait (up to 60s) for its global. On a
			// network error the <script> never defines VerovioInit, so this times out → null,
			// and the caller shows a retry prompt rather than spinning forever.
			const VInit = await waitForGlobal('VerovioInit', 60000);
			if (!VInit) { log('VerovioInit global missing (timeout)'); state._verovioInitPromise = null; return null; }
			// VerovioInit() awaits the Emscripten WASM module's readyPromise, then
			// returns a constructed toolkit — the path proven by lilylet-live-editor.
			try {
				const tk = await VInit();
				tk.setOptions({ scale: 40, adjustPageHeight: true, breaks: 'auto', pageWidth: 2100, pageHeight: 2970 });
				state.toolkit = tk;
				state.verovioReady = true;
				log('verovio ready ' + (tk.getVersion ? tk.getVersion() : '?'));
				return tk;
			} catch (e) {
				log('verovio init failed: ' + (e && e.message ? e.message : e));
				state._verovioInitPromise = null;
				return null;
			}
		})();
		return state._verovioInitPromise;
	}

	// ---- lyl -> MEI -> SVG --------------------------------------------------

	function lylToMei (code) {
		if (!window.LilyletLib) throw new Error('LilyletLib not loaded');
		const doc = window.LilyletLib.parseCode(code);
		const mei = window.LilyletLib.meiEncoder.encode(doc);
		let staffCount = 1;
		if (doc.measures && doc.measures.length) {
			const m0 = doc.measures[0];
			staffCount = m0.parts.reduce((tot, part) => {
				const maxStaff = part.voices.reduce((mx, v) => Math.max(mx, v.staff || 1), 1);
				return tot + maxStaff;
			}, 0) || 1;
		}
		return { mei, measureCount: (doc.measures && doc.measures.length) || 1, staffCount };
	}

	// Inject one or more page SVGs, stacked vertically. Verovio paginates a long score
	// into multiple pages (getPageCount); rendering only page 1 truncates the score, so
	// we render every page and append them all. Element IDs are unique across pages, so
	// the playback cursor/highlight lookups (getElementById) still work.
	function injectSvg (svgStrings) {
		if (typeof svgStrings === 'string') svgStrings = [svgStrings];
		const parser = new DOMParser();
		els.svg.innerHTML = '';
		for (let i = 0; i < svgStrings.length; i++) {
			const doc = parser.parseFromString(svgStrings[i], 'image/svg+xml');
			if (doc.querySelector('parsererror')) { log('svg parse error on page ' + (i + 1)); continue; }
			const svg = doc.querySelector('svg');
			if (!svg) continue;
			const page = document.importNode(svg, true);
			page.classList.add('ls-svg-page');
			page.style.display = 'block';
			els.svg.appendChild(page);
		}
		// re-attach the playback cursor (innerHTML reset above removed it)
		if (els.cursor) { els.cursor.style.display = 'none'; els.svg.appendChild(els.cursor); }
	}

	function setStatus (text, kind) {
		if (!els.status) return;
		els.status.className = 'ls-status' + (kind ? ' ls-' + kind : '');
		// Errors (esp. lilylet parse errors) are multi-line with a `^` caret aligned
		// under the offending token — wrap them in <pre> so the whitespace/newlines
		// are preserved (a plain div collapses them). textContent keeps it XSS-safe.
		if (kind === 'err' && text) {
			els.status.innerHTML = '';
			const pre = document.createElement('pre');
			pre.className = 'ls-err-pre';
			pre.textContent = text;
			els.status.appendChild(pre);
		} else {
			els.status.textContent = text || '';
		}
	}

	// Render lyl -> SVG. Returns true on success. Does NOT touch the MIDI player
	// (that is gated separately on generation state).
	async function render (code) {
		// Guard: render may be called (e.g. by the page's initial-render poll on
		// reload/deep-link) before mount() has built the player DOM, so els.svg is
		// still undefined. Bail quietly — the caller's poll retries until mount is
		// done. (Without this, injectSvg's `els.svg.innerHTML = ''` throws
		// "Cannot set properties of undefined".)
		if (!els.svg) { log('render before mount — skipping'); return false; }
		const tk = await initVerovio();
		if (!tk) { setStatus('Verovio not ready', 'err'); return false; }
		code = (code || '').trim();
		if (!code) { els.svg.innerHTML = ''; state.lastCode = ''; state.lastMei = null; updatePlayerVisibility(); updateEmptyState(); return false; }
		if (code === state.lastCode) return true;
		setStatus('Rendering…', 'busy');
		try {
			const { mei, measureCount, staffCount } = lylToMei(code);
			// Use a normal A4-ish page so Verovio lays the score out across pages; we then
			// render ALL pages and stack them (see injectSvg). adjustPageHeight trims each
			// page to its content so there are no big gaps between pages.
			tk.setOptions({ scale: 40, adjustPageHeight: true, breaks: 'auto', pageWidth: 2100, pageHeight: 2970 });
			if (!tk.loadData(mei)) { setStatus('Verovio load failed', 'err'); return false; }
			const pageCount = (tk.getPageCount && tk.getPageCount()) || 1;
			const pages = [];
			for (let pg = 1; pg <= pageCount; pg++) pages.push(tk.renderToSVG(pg));
			injectSvg(pages);
			setRendererLoading(false);   // score is now visible — ensure the loading spinner is gone
			state.lastCode = code;
			state.lastMei = mei;
			setStatus('', '');
			// new score -> existing MIDI is stale
			state.midiData = null;
			if (state.player) { try { state.player.dispose(); } catch (e) {} state.player = null; }
			stop();
			updatePlayerVisibility();
			return true;
		} catch (e) {
			setStatus('Parse error: ' + (e && e.message ? e.message : e), 'err');
			log('render error: ' + (e && e.stack ? e.stack : e));
			return false;
		}
	}

	// ---- MIDI audio + player (gated: only when NOT generating) ---------------

	async function initAudio () {
		if (state.audioReady) return true;
		// music-widgets + the FluidSynth adapter (js-synthesizer.min.js + fluid-audio.js)
		// load after us in <head>; wait for the music-widgets global to appear.
		const mw = await waitForGlobal('musicWidgetsBrowser', 300000);
		if (!mw) { log('musicWidgetsBrowser missing (timeout)'); return false; }
		// MIDI/MidiPlayer/MusicNotation come from music-widgets; the *audio backend* is
		// FluidSynth (js-synthesizer + gm.sf3, 128 GM instruments) via LilyFluidAudio,
		// which falls back to music-widgets' single-piano MidiAudio while the large GM
		// soundfont downloads. score-player drives MidiAudio.{noteOn,noteOff,
		// programChange,stopAllNotes,resume}, all forwarded by LilyFluidAudio.
		var backend = window.LilyFluidAudio;
		if (backend && backend.init) {
			backend.init(mw.MidiAudio);                 // inject the legacy piano fallback
		} else {
			log('LilyFluidAudio missing; using music-widgets MidiAudio directly');
			backend = mw.MidiAudio;
		}
		state.audio = { MIDI: mw.MIDI, MidiPlayer: mw.MidiPlayer, MusicNotation: mw.MusicNotation, MidiAudio: backend };
		startSfStatus();   // show the sound-library loading badge while the GM font downloads
		try {
			// Kick off loading; resolves only when the full GM soundfont is decoded.
			// Don't block playback on it — the legacy piano fallback becomes audible
			// much earlier, so report ready as soon as any backend can sound.
			var fullLoad = backend.loadPlugin ? backend.loadPlugin({ soundfontUrl: SOUNDFONT_URL, api: 'webaudio' }) : Promise.resolve();
			if (backend.empty) {
				for (var i = 0; i < 100 && backend.empty(); i++) { await new Promise(function (r) { setTimeout(r, 100); }); }
			} else {
				await fullLoad;
			}
			if (backend.empty && backend.empty()) { log('audio not ready (no backend audible)'); return false; }
			state.audioReady = true;
			// NOTE: do NOT warm up / resume the audio context here. This runs at page
			// load, outside any user gesture, so the browser autoplay policy won't
			// actually resume a suspended context. Worse, the legacy WebAudio backend's
			// awaitWarmup() *caches* the in-flight resume() promise — calling it
			// out-of-gesture starts a resume() that never settles (no gesture) and
			// caches that permanently-pending promise. Every later in-gesture warmup
			// then returns the same hung promise, so play()'s `await resumeP` blocks
			// forever and the transport freezes ("no reaction"). The in-gesture
			// resume() inside play() is the ONLY place we resume.
			log('audio ready (fluid=' + (backend.ready ? backend.ready() : '?') + ')');
			return true;
		} catch (e) {
			log('audio load failed: ' + (e && e.message ? e.message : e));
			return false;
		}
	}

	// Build a MidiPlayer for the current score's MEI. Idempotent per MEI.
	async function buildPlayer () {
		if (!state.lastMei || !state.toolkit) return false;
		if (!(await initAudio())) return false;
		if (state.player && state.midiData) return true;   // already built for this MEI
		try {
			const midiBase64 = state.toolkit.renderToMIDI();
			const bin = atob(midiBase64);
			const bytes = new Uint8Array(bin.length);
			for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
			const raw = state.audio.MIDI.parseMidiData(bytes.buffer);
			const notation = state.audio.MusicNotation.Notation.parseMidi(raw);
			if (!notation.tempos || !notation.tempos.length) notation.tempos = [{ tempo: 500000, tick: 0, time: 0 }];
			state.midiData = notation;
			state.duration = notation.endTime;
			if (state.player) { try { state.player.dispose(); } catch (e) {} }
			state.player = new state.audio.MidiPlayer(notation, { cacheSpan: 400, onMidi: function () {} });
			stop();
			return true;
		} catch (e) {
			log('buildPlayer error: ' + (e && e.message ? e.message : e));
			return false;
		}
	}

	function findEventIndexAtTime (time) {
		if (!state.midiData) return 0;
		const ev = state.midiData.events;
		let lo = 0, hi = ev.length;
		while (lo < hi) { const mid = (lo + hi) >>> 1; if (ev[mid].time < time) lo = mid + 1; else hi = mid; }
		return lo;
	}

	async function play () {
		if (state.isPlaying || state.generating) return;
		// Don't start a silent walk-through: if no audio backend can sound yet (neither
		// the legacy piano fallback nor the full GM soundfont is ready), bail. The play
		// button is normally disabled in this state, but guard here too.
		var Af = state.audio && state.audio.MidiAudio;
		if (Af && Af.empty && Af.empty()) { return; }
		// Resume the audio backend FIRST, synchronously within the click gesture. The
		// browser's autoplay policy only lets us resume a suspended AudioContext while a
		// user-activation is in scope; if we first `await buildPlayer()` (async), the
		// activation is gone by the time we'd resume, so the context stays suspended and
		// no sound comes out. So kick resume() off now (don't await it yet).
		var A0 = state.audio && state.audio.MidiAudio;
		var resumeP = null;
		if (A0 && A0.resume) { try { resumeP = A0.resume(); } catch (e) {} }
		else { var WA = A0 && A0.WebAudio; if (WA && WA.awaitWarmup) { try { resumeP = WA.awaitWarmup(); } catch (e) {} } }
		// The player may not be built yet: on a deep-link load the first render can run
		// before the audio backend finished initialising, so updatePlayerVisibility's
		// buildPlayer() returned early and was never retried (the editor text didn't
		// change afterwards to re-trigger render). Build it on demand here.
		if (!state.player || !state.midiData) {
			if (!(await buildPlayer())) return;   // still can't build (no MEI/toolkit) → nothing to play
		}
		if (!state.player || !state.midiData) return;
		// Make sure the resume completed before scheduling notes — but never let a hung
		// resume freeze the transport. (The legacy backend can return a resume promise
		// that never settles; see the awaitWarmup note in initAudio.) Race it against a
		// short timeout: notes start scheduling regardless, and sound follows as soon as
		// the context actually resumes. Resuming is in-gesture above, so this is just a
		// safety valve, not the thing that satisfies autoplay.
		if (resumeP) {
			try {
				await Promise.race([
					Promise.resolve(resumeP).catch(function () {}),
					new Promise(function (r) { setTimeout(r, 250); }),
				]);
			} catch (e) {}
		}
		state.isPlaying = true;
		if (state.pausedTime > 0) {
			state.playStartTime = performance.now() - state.pausedTime;
			state.lastEventIndex = findEventIndexAtTime(state.pausedTime);
		} else {
			state.playStartTime = performance.now();
			state.lastEventIndex = 0;
		}
		updateTransport();
		state.updateInterval = setInterval(function () {
			if (!state.isPlaying || !state.midiData) return;
			const elapsed = performance.now() - state.playStartTime;
			state.currentTime = elapsed;
			const ev = state.midiData.events;
			const A = state.audio.MidiAudio;
			for (; state.lastEventIndex < ev.length; state.lastEventIndex++) {
				const e = ev[state.lastEventIndex];
				if (e.time > elapsed) break;
				if (e.data.type === 'channel') {
					const ts = state.playStartTime + e.time;
					if (e.data.subtype === 'noteOn') A.noteOn(e.data.channel, e.data.noteNumber, e.data.velocity, ts);
					else if (e.data.subtype === 'noteOff') A.noteOff(e.data.channel, e.data.noteNumber, ts);
					else if (e.data.subtype === 'programChange') A.programChange(e.data.channel, e.data.programNumber);
					else if (e.data.subtype === 'controller' && A.controlChange) A.controlChange(e.data.channel, e.data.controllerType, e.data.value, ts);
				}
			}
			updateHighlightsThrottled(state.currentTime);
			updateProgress();
			if (elapsed >= state.duration) stop();
		}, 30);
	}

	function pause () {
		if (state.updateInterval) { clearInterval(state.updateInterval); state.updateInterval = null; }
		state.pausedTime = state.currentTime;
		state.isPlaying = false;
		state.audio && state.audio.MidiAudio.stopAllNotes && state.audio.MidiAudio.stopAllNotes();
		updateTransport();
	}

	function stop () {
		if (state.updateInterval) { clearInterval(state.updateInterval); state.updateInterval = null; }
		state.isPlaying = false;
		state.currentTime = 0;
		state.pausedTime = 0;
		state.lastEventIndex = 0;
		clearHighlights();
		state.audio && state.audio.MidiAudio.stopAllNotes && state.audio.MidiAudio.stopAllNotes();
		updateTransport();
		updateProgress();
	}

	function seekTo (t) {
		if (!state.midiData) return;
		t = Math.max(0, Math.min(t, state.duration));
		state.audio && state.audio.MidiAudio.stopAllNotes && state.audio.MidiAudio.stopAllNotes();
		state.currentTime = t;
		state.pausedTime = t;
		state.lastEventIndex = findEventIndexAtTime(t);
		if (state.isPlaying) state.playStartTime = performance.now() - t;
		updateHighlights(t);
		updateProgress();
	}

	// ---- highlight + cursor -------------------------------------------------

	function updateHighlightsThrottled (time) {
		const now = performance.now();
		if (now - lastHighlightUpdate < HIGHLIGHT_THROTTLE_MS) return;
		lastHighlightUpdate = now;
		updateHighlights(time);
	}

	// When a score has repeats, verovio unfolds the MEI <expansion> for MIDI and
	// the time-map, minting a fresh id with a "-rendN" suffix (N >= 2) for every
	// note replayed on a later pass. The rendered SVG, however, only draws each
	// notated note once (the un-suffixed id). So on the 2nd+ pass the time-map id
	// has no element in the DOM and the highlight/cursor would vanish. Strip the
	// suffix to map every replay back onto the single drawn note — the cursor
	// re-walks the same bars on each pass. (Mirrors lilylet-live-editor's
	// normalizeRepeatId in Player.svelte.)
	function normalizeRepeatId (id) { return id.replace(/-rend\d+$/, ''); }

	function updateHighlights (time) {
		if (!state.toolkit) return;
		try {
			const res = state.toolkit.getElementsAtTime(time);
			const now = new Set((res.notes || []).map(normalizeRepeatId));
			state.highlighted.forEach(function (id) {
				if (!now.has(id)) { const el = document.getElementById(id); if (el) el.classList.remove('ls-hl'); }
			});
			now.forEach(function (id) {
				if (!state.highlighted.has(id)) { const el = document.getElementById(id); if (el) el.classList.add('ls-hl'); }
			});
			state.highlighted = now;
			// move the playback cursor to the first currently-sounding note
			const ids = res.notes || [];
			if (ids.length) updateCursor(normalizeRepeatId(ids[0]));
		} catch (e) { /* ignore */ }
	}

	// Position the vertical cursor at a note element, spanning its system's height.
	function updateCursor (noteId) {
		if (!els.cursor || !els.svg) return;
		const note = document.getElementById(noteId);
		if (!note) { els.cursor.style.display = 'none'; return; }
		const sysOrStaff = note.closest('.system') || note.closest('.staff');
		const boxRect = els.svg.getBoundingClientRect();
		const noteRect = note.getBoundingClientRect();
		const x = noteRect.left + noteRect.width / 2 - boxRect.left;
		let top = 0, height = boxRect.height;
		if (sysOrStaff) {
			const sr = sysOrStaff.getBoundingClientRect();
			top = sr.top - boxRect.top;
			height = sr.height;
		}
		els.cursor.style.left = x + 'px';
		els.cursor.style.top = top + 'px';
		els.cursor.style.height = height + 'px';
		els.cursor.style.display = 'block';
		// keep the cursor in view while playing
		scrollCursorIntoView(noteRect, boxRect);
	}

	// Auto-scroll the preview so the cursor stays visible (throttled, gentle).
	function scrollCursorIntoView (noteRect, boxRect) {
		if (!els.preview) return;
		const now = performance.now();
		if (now - lastAutoScroll < 300) return;
		const pr = els.preview.getBoundingClientRect();
		const above = noteRect.top < pr.top + 60;
		const below = noteRect.bottom > pr.bottom - 60;
		if (!above && !below) return;
		lastAutoScroll = now;
		const target = els.preview.scrollTop + (noteRect.top - pr.top) - els.preview.clientHeight * 0.35;
		els.preview.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
	}

	function hideCursor () {
		if (els.cursor) els.cursor.style.display = 'none';
	}

	function clearHighlights () {
		state.highlighted.forEach(function (id) { const el = document.getElementById(id); if (el) el.classList.remove('ls-hl'); });
		state.highlighted = new Set();
		hideCursor();
	}

	// ---- transport UI -------------------------------------------------------

	function fmt (ms) {
		const s = Math.floor(ms / 1000), m = Math.floor(s / 60);
		return m + ':' + String(s % 60).padStart(2, '0');
	}

	function updateProgress () {
		if (els.fill) els.fill.style.width = (state.duration > 0 ? (state.currentTime / state.duration) * 100 : 0) + '%';
		if (els.time) els.time.textContent = fmt(state.currentTime) + ' / ' + fmt(state.duration);
	}

	function updateTransport () {
		if (!els.playBtn) return;
		els.playBtn.style.display = state.isPlaying ? 'none' : '';
		els.pauseBtn.style.display = state.isPlaying ? '' : 'none';
	}

	// ---- sound-library (soundfont) status badge -----------------------------
	// Mirrors live-editor's Preview.svelte sf-status: pulsing/grayscale 🎹 while the
	// GM soundfont loads (grand-piano fallback active), then a steady green 🎹✓ once
	// ready (left in place, no fade). FluidSynth-only; if the backend lacks the
	// loading/ready introspection (plain music-widgets MidiAudio) the badge stays hidden.
	//
	// This also gates the play button: until SOME backend can sound (the legacy piano
	// fallback OR the full GM soundfont — i.e. !empty()), play is disabled so the user
	// can't trigger a silent walk-through. The button enables the moment a backend is
	// audible and the badge turns green once the full GM font is ready.
	function startSfStatus () {
		var F = state.audio && state.audio.MidiAudio;
		if (!els.sf || !F || !F.ready || !F.loading) return;   // not the fluid backend
		if (state._sfInterval) return;                          // already tracking
		els.sf.style.display = '';
		els.sf.classList.remove('ready');
		function markReady () {
			els.sf.classList.add('ready');
			els.sf.classList.remove('ls-sf-err');
			els.sf.title = 'Sound library ready — full instrument timbres';
		}
		// gm.sf3 failed to load: turn the 🎹 badge into a clickable retry (⟳ overlay).
		// The legacy piano fallback (if loaded) stays audible, so play still works — this
		// only signals the full GM timbres are unavailable until retried.
		function markFailed () {
			els.sf.classList.remove('ready');
			els.sf.classList.add('ls-sf-err');
			els.sf.style.cursor = 'pointer';
			els.sf.title = 'Sound library failed to load — click to retry';
		}
		// reflect current backend-audible state on the play button, and recover from a
		// build race: if a backend is now audible but the player wasn't built yet (the
		// first buildPlayer ran before audio was ready), build it now so play enables.
		function syncPlayEnabled () {
			if (!els.playBtn) return;
			var audible = F.empty ? !F.empty() : true;   // any backend can sound
			if (audible && state.lastMei && !(state.player && state.midiData) && !state._buildingPlayer) {
				state._buildingPlayer = true;
				buildPlayer().then(function (ok) {
					state._buildingPlayer = false;
					if (ok) updateProgress();
				});
			}
			els.playBtn.disabled = !(audible && state.player && state.midiData);
			els.playBtn.title = audible ? 'Play' : 'Loading sound library…';
			// While no backend can sound yet (or the player is still building), show an
			// animated spinner on the play button instead of ▶, so the loading state
			// reads clearly rather than as a plain greyed button. (CSS: .ls-btn.ls-loading)
			var loading = !(audible && state.player && state.midiData);
			els.playBtn.classList.toggle('ls-loading', loading);
		}
		syncPlayEnabled();
		// keep polling until BOTH a backend is audible and the player is built (covers
		// the legacy-fallback window and the build race), and until the GM font is ready
		// (for the badge). Stop once everything's settled.
		var iv = setInterval(function () {
			syncPlayEnabled();
			if (F.ready()) markReady();
			else if (F.failed && F.failed()) markFailed();
			if (F.ready() && state.player && state.midiData) { clearInterval(iv); state._sfInterval = null; }
		}, 200);
		state._sfInterval = iv;
		// safety: never poll forever
		setTimeout(function () { if (state._sfInterval) { clearInterval(state._sfInterval); state._sfInterval = null; } }, 60000);
	}

	// Retry a failed gm.sf3 / soundfont load (driven by clicking the 🎹 badge in its
	// error state). Clears the badge error, kicks a fresh load via the backend's
	// retryLoad(), and restarts the status poller so the badge tracks the new attempt.
	function retrySoundfont () {
		var F = state.audio && state.audio.MidiAudio;
		if (!F || !F.retryLoad) return;
		els.sf.classList.remove('ls-sf-err');
		els.sf.title = 'Loading sound library…';
		// stop the current poller so startSfStatus re-arms cleanly
		if (state._sfInterval) { clearInterval(state._sfInterval); state._sfInterval = null; }
		F.retryLoad();
		startSfStatus();
	}

	// Show the player bar only when: not generating, a score is rendered, audio
	// available. While generating we keep SVG visible but hide the transport.
	function updatePlayerVisibility () {
		if (!els.player) return;
		const show = !state.generating && !!state.lastMei;
		els.player.style.display = show ? '' : 'none';
		if (show) {
			// disable play until a backend is audible AND the player is built; the
			// sf-status poller (startSfStatus) keeps this in sync as soundfonts load.
			if (els.playBtn) { els.playBtn.disabled = true; els.playBtn.classList.add('ls-loading'); }
			buildPlayer().then(function (ok) {
				if (ok) updateProgress();
				var F = state.audio && state.audio.MidiAudio;
				var audible = (F && F.empty) ? !F.empty() : true;
				var ready = ok && audible;
				els.playBtn.disabled = !ready;
				els.playBtn.classList.toggle('ls-loading', !ready);
				startSfStatus();   // keep enabling/badge in sync while soundfonts finish loading
			});
		}
	}

	// ---- mount + public API -------------------------------------------------

	function mount (root) {
		if (els.root === root && els.svg) return;   // already mounted here
		root.innerHTML = '';
		root.classList.add('ls-score-root');

		const wrap = document.createElement('div'); wrap.className = 'ls-preview';
		const status = document.createElement('div'); status.className = 'ls-status';
		const svgBox = document.createElement('div'); svgBox.className = 'ls-svg';
		const cursor = document.createElement('div'); cursor.className = 'ls-cursor';
		svgBox.appendChild(cursor);
		// Renderer-loading overlay: a spinner shown INSIDE the freshly-mounted panel while
		// the 7.6MB verovio bundle is still downloading. Since score-player.js now mounts
		// early (before verovio finishes — see app.py head order), without this the panel
		// would sit blank with no feedback during the wait (the static placeholder is gone,
		// replaced by this mount). Removed once verovio is ready (setRendererLoading(false)).
		const loading = document.createElement('div'); loading.className = 'ls-renderer-loading';
		loading.innerHTML =
			'<div class="ls-loading-spinner" aria-hidden="true"></div>' +
			'<div class="ls-loading-text">' + LOADING_RENDERER_TEXT + '</div>' +
			// error/retry block (hidden until verovio fails to load). The ⟳ icon + text are
			// clickable to retry; see setRendererError() / retryVerovio().
			'<div class="ls-renderer-error" style="display:none">' +
				'<button type="button" class="ls-retry-btn" title="Retry"><span class="ls-retry-icon" aria-hidden="true">⟳</span></button>' +
				'<div class="ls-retry-text">' + RENDERER_FAILED_TEXT + '</div>' +
			'</div>';
		// Empty-state placeholder: a large staff/treble-clef icon + prompt, shown when the
		// renderer is ready but no score is loaded (fresh page, or editor cleared). Without
		// it the panel would be blank once the loading spinner clears. Hidden when a score
		// renders or while generating. Icon is inline SVG so it needs no extra asset fetch.
		const empty = document.createElement('div'); empty.className = 'ls-empty'; empty.style.display = 'none';
		empty.innerHTML = STAFF_ICON_SVG + '<div class="ls-empty-text">' + EMPTY_SCORE_TEXT + '</div>';
		wrap.appendChild(status); wrap.appendChild(svgBox); wrap.appendChild(loading); wrap.appendChild(empty);

		// transport bar (above the score)
		const player = document.createElement('div'); player.className = 'ls-player'; player.style.display = 'none';
		player.innerHTML =
			'<button class="ls-btn ls-play" title="Play">▶</button>' +
			'<button class="ls-btn ls-pause" title="Pause" style="display:none">⏸</button>' +
			'<button class="ls-btn ls-stop" title="Stop">■</button>' +
			'<span class="ls-time">0:00 / 0:00</span>' +
			'<div class="ls-progress"><div class="ls-fill"></div></div>' +
			// sound-library status: pulsing 🎹 while the GM soundfont loads (piano
			// fallback audible), green 🎹✓ once ready (shown 2s, then faded; hover reveals).
			// On load failure it becomes a clickable retry (⟳ overlay, .ls-sf-err); see
			// startSfStatus() / retrySoundfont().
			'<span class="ls-sf" style="display:none" title="Loading sound library… (grand-piano fallback active)">🎹<span class="ls-sf-check">✓</span><span class="ls-sf-retry" aria-hidden="true">⟳</span></span>';

		root.appendChild(player); root.appendChild(wrap);

		els.root = root; els.svg = svgBox; els.preview = wrap; els.status = status; els.player = player; els.cursor = cursor;
		els.loading = loading; els.empty = empty;
		els.rendererError = loading.querySelector('.ls-renderer-error');
		els.playBtn = player.querySelector('.ls-play');
		els.pauseBtn = player.querySelector('.ls-pause');
		els.stopBtn = player.querySelector('.ls-stop');
		els.time = player.querySelector('.ls-time');
		els.progress = player.querySelector('.ls-progress');
		els.fill = player.querySelector('.ls-fill');
		els.sf = player.querySelector('.ls-sf');

		els.playBtn.addEventListener('click', play);
		els.pauseBtn.addEventListener('click', pause);
		els.stopBtn.addEventListener('click', stop);
		// retry verovio (renderer) on click of the in-panel error prompt
		els.rendererError.querySelector('.ls-retry-btn').addEventListener('click', retryVerovio);
		// retry the soundfont when the 🎹 badge is in its error state (clickable then)
		els.sf.addEventListener('click', function () { if (els.sf.classList.contains('ls-sf-err')) retrySoundfont(); });
		els.progress.addEventListener('click', function (e) {
			if (!state.midiData) return;
			const r = els.progress.getBoundingClientRect();
			seekTo(state.duration * ((e.clientX - r.left) / r.width));
		});
		// click in the score -> seek to the nearest note/rest. We don't rely on the
		// click target (elementFromPoint often lands on the bare <svg> between
		// noteheads, or on a staff line): instead find the .note/.chord/.rest whose
		// on-screen box is closest to the click, then seek to its time.
		els.svg.addEventListener('click', function (e) {
			if (!state.toolkit || state.generating || !state.midiData) return;
			const svg = els.svg.querySelector('svg');
			if (!svg) return;
			const cands = svg.querySelectorAll('.note, .chord, .rest, .mRest');
			let best = null, bestD = Infinity;
			for (var i = 0; i < cands.length; i++) {
				if (!cands[i].id) continue;
				const r = cands[i].getBoundingClientRect();
				const dx = e.clientX - (r.left + r.width / 2);
				const dy = e.clientY - (r.top + r.height / 2);
				const d = dx * dx + dy * dy;
				if (d < bestD) { bestD = d; best = cands[i]; }
			}
			if (!best) return;
			const time = state.toolkit.getTimeForElement(best.id);
			if (typeof time === 'number' && !isNaN(time) && time >= 0) seekTo(time);
		});

		// Show the renderer-loading spinner until verovio is ready; initVerovio() resolves
		// when the (possibly still-downloading) verovio bundle has constructed its toolkit,
		// or null on failure/timeout (network error) — in which case show a retry prompt.
		setRendererLoading(!state.verovioReady);
		initVerovio().then(function (tk) {
			if (tk) setRendererLoading(false);
			else setRendererError();   // network/load failure → offer a retry (not a blank/empty state)
		});
		// Start loading the sound library (FluidSynth GM soundfont, ~40MB) right away
		// at page mount rather than deferring to the first play — the AudioContext is
		// created suspended (no autoplay-policy violation) and the fetch/worklet load
		// proceed in the background, so the library is usually ready before the user
		// hits play. initAudio() is idempotent; buildPlayer() later just reuses it.
		initAudio();
	}

	// Toggle the in-panel renderer-loading spinner (verovio still downloading). Hidden
	// once a score has actually rendered (an SVG is present) so it never overlaps content.
	function setRendererLoading (flag) {
		if (!els.loading) return;
		var hasSvg = els.svg && els.svg.querySelector('svg');
		els.loading.style.display = (flag && !hasSvg) ? '' : 'none';
		// leaving the loading state (success) clears any prior error UI
		if (!flag) showRendererErrorBlock(false);
		updateEmptyState();
	}

	// Toggle just the spinner-vs-error contents inside the loading overlay.
	function showRendererErrorBlock (isError) {
		if (els.rendererError) els.rendererError.style.display = isError ? '' : 'none';
		var spinner = els.loading && els.loading.querySelector('.ls-loading-spinner');
		var ltext = els.loading && els.loading.querySelector('.ls-loading-text');
		if (spinner) spinner.style.display = isError ? 'none' : '';
		if (ltext) ltext.style.display = isError ? 'none' : '';
	}

	// Renderer (verovio) failed to load — keep the overlay up but swap the spinner for a
	// clickable retry prompt. state.verovioReady stays false, so the empty-state stays
	// suppressed (we must not show "click a score to play" when the renderer is dead).
	function setRendererError () {
		state._rendererError = true;
		if (!els.loading) return;
		els.loading.style.display = '';        // keep overlay visible
		showRendererErrorBlock(true);
		updateEmptyState();
	}

	// Retry loading verovio: re-fetch the bundle <script> (a failed network load left no
	// VerovioInit), reset the cached init promise, and re-run initVerovio. Driven by the
	// retry button in the renderer-error block.
	function retryVerovio () {
		if (state.verovioReady) { setRendererLoading(false); return; }
		state._rendererError = false;
		state._verovioInitPromise = null;
		showRendererErrorBlock(false);        // back to spinner while retrying
		setRendererLoading(true);
		reloadVendorScript('verovio.bundle.js');
		initVerovio().then(function (tk) {
			if (tk) { setRendererLoading(false); if (state.lastCode) render(state.lastCode); }
			else setRendererError();
		});
	}

	// Re-inject a vendored <script> by URL fragment (e.g. 'verovio.bundle.js') so a retry
	// actually re-downloads it. Reuses the original tag's src; appends a cache-buster so a
	// previously-failed (and possibly negatively-cached) response isn't served again.
	function reloadVendorScript (frag) {
		var orig = null, tags = document.querySelectorAll('script[src]');
		for (var i = 0; i < tags.length; i++) { if (tags[i].src.indexOf(frag) !== -1) { orig = tags[i]; break; } }
		var base = orig ? orig.src.split('?')[0] : null;
		if (!base) { log('retry: original <script> for ' + frag + ' not found'); return; }
		var s = document.createElement('script');
		s.src = base + '?retry=' + Date.now();
		s.async = false;
		document.head.appendChild(s);
	}

	// Show the empty-state placeholder (staff icon + prompt) exactly when there is
	// nothing else to show: renderer ready, no score rendered, not generating, and the
	// loading spinner isn't up. Keeps the panel from sitting blank before the user picks
	// or generates a score. Called from every state transition that can change it.
	function updateEmptyState () {
		if (!els.empty) return;
		var hasSvg = els.svg && els.svg.querySelector('svg');
		var loadingShown = els.loading && els.loading.style.display !== 'none';
		var show = state.verovioReady && !hasSvg && !loadingShown && !state.generating && !state._rendererError;
		els.empty.style.display = show ? '' : 'none';
	}

	// Public API consumed by app.py's injected glue.
	window.LilyScore = {
		mount: mount,
		// Render lyl text to the SVG preview. Safe to call repeatedly (deduped).
		render: function (code) { return render(code); },
		// Generation gate. While generating: SVG-only, transport hidden, playback
		// stopped. On finish: re-render final text and reveal the player.
		setGenerating: function (flag) {
			flag = !!flag;
			if (flag === state.generating) return;
			state.generating = flag;
			// faint yellow score background only while generating
			if (els.svg) els.svg.classList.toggle('ls-generating-bg', flag);
			if (flag) { stop(); }
			updatePlayerVisibility();
			updateEmptyState();
		},
		isReady: function () { return state.verovioReady; },
	};
	log('score-player.js loaded');

	// ---- self-mount (event-driven) ------------------------------------------
	// Mount as soon as BOTH this script has executed (window.LilyScore defined —
	// which only happens after the 7.6MB verovio.bundle.js ahead of us in <head>
	// finishes downloading + parsing) AND Gradio has inserted the #ls-score node.
	// We own the mounting here rather than relying on app.py's injected poller:
	// on a cold load over a slow link, verovio can take well over a minute, so any
	// fixed-deadline poll on the app side would have already given up by the time
	// we run, leaving the loading spinner stuck forever (the bug this replaces).
	// A MutationObserver has no deadline, so it cannot expire early.
	function selfMount () {
		const root = document.getElementById('ls-score');
		if (root) { mount(root); return true; }
		return false;
	}
	if (!selfMount()) {
		// #ls-score not in the DOM yet (Gradio still building the UI). Watch for it.
		const mo = new MutationObserver(function () {
			if (selfMount()) mo.disconnect();
		});
		const startObserving = function () {
			mo.observe(document.documentElement, { childList: true, subtree: true });
			selfMount();   // re-check in case it appeared between the miss and observe()
		};
		if (document.documentElement) startObserving();
		else document.addEventListener('DOMContentLoaded', startObserving);
	}
})();
