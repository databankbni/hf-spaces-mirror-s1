/* LilyScript FluidSynth audio backend — vanilla-JS port of lilylet-live-editor's
 * src/lib/audio/fluidAudio.ts, exposed as window.LilyFluidAudio.
 *
 * Replaces the legacy single-piano MIDI.js soundfont with FluidSynth (js-synthesizer
 * WASM) playing a General MIDI gm.sf3 (128 instruments), so each track sounds with
 * its own program instead of everything-as-piano.
 *
 * Shaped to match the subset of music-widgets' MidiAudio API that score-player.js
 * drives: empty / loadPlugin / resume / noteOn / noteOff / programChange /
 * controlChange / stopAllNotes. score-player.js sends noteOn/noteOff with an absolute
 * performance.now()-based timestamp; we forward to FluidSynth's Sequencer via
 * sendEventAt(event, dtMs, isAbsolute=false) ("play in dtMs ms"), preserving the
 * look-ahead timing without reconciling against the sequencer's own tick origin.
 *
 * Fallback: gm.sf3 is ~40 MB and takes a moment to fetch + decode. While it loads we
 * fall back to the legacy MIDI.js WebAudio piano (the small, locally-bundled
 * acoustic-grand-piano soundfont) so playback is audible immediately; once FluidSynth
 * is ready we switch to it transparently.
 *
 * Globals consumed (loaded via <script src> in <head> by app.py build_head):
 *   window.JSSynth                     js-synthesizer UMD { AudioWorkletNodeSynthesizer, ... }
 *   window.musicWidgetsBrowser.MidiAudio   legacy MIDI.js WebAudio piano (fallback)
 *   window.__LILYSCRIPT_FLUID_URL      base URL of web/fluid/ (libfluidsynth + worklet)
 *   window.__LILYSCRIPT_SOUNDFONT_URL  base URL of web/soundfont/ (gm.sf3 + piano)
 */
(function () {
	'use strict';

	function log (msg) { console.log('[LilyFluid]', msg); }

	// URLs (with trailing slash) injected by app.py; fall back to relative paths.
	var FLUID_URL = (window.__LILYSCRIPT_FLUID_URL || './fluid/');
	var SOUNDFONT_URL = (window.__LILYSCRIPT_SOUNDFONT_URL || './soundfont/');

	// DEBUG TOGGLE: when true, skip loading gm.sf3 / FluidSynth entirely and keep
	// playing through the legacy ogg.js piano fallback. Lets us isolate whether the
	// fallback path alone is audible, independent of the FluidSynth handoff. Set via
	// window.__LILYSCRIPT_DISABLE_FLUID before this script runs, or flip the default.
	var DISABLE_FLUID = !!window.__LILYSCRIPT_DISABLE_FLUID;

	// The with-libsndfile build is required to decode .sf3 (ogg-compressed) fonts;
	// it also reads .sf2. Both modules load into the AudioWorklet scope.
	var LIBFLUIDSYNTH_FILE = FLUID_URL + 'libfluidsynth-2.4.6-with-libsndfile.js';
	var WORKLET_FILE = FLUID_URL + 'js-synthesizer.worklet.js';
	var SOUNDFONT_FILE = SOUNDFONT_URL + 'gm.sf3';

	var audioCtx = null;
	var synth = null;
	var seq = null;
	var node = null;          // the synth's AudioNode (kept for diagnostics)
	var loaded = false;
	var loadingPromise = null;
	var failed = false;        // true if the last gm.sf3 load attempt errored (network etc.)

	// Legacy MIDI.js fallback (single-piano), used until FluidSynth finishes loading.
	var legacy = null;
	var legacyReady = false;

	// Inject the legacy UMD MidiAudio (fallback). Must be called before loadPlugin().
	function init (legacyMidiAudio) {
		legacy = legacyMidiAudio || null;
	}

	// True once the (preferred) FluidSynth backend has finished loading.
	function ready () { return loaded; }

	// True while FluidSynth is still loading (the fallback may already be audible).
	function loading () { return !loaded && !!loadingPromise; }

	// Whether any backend can produce sound yet (FluidSynth or the legacy fallback).
	function empty () { return !loaded && !legacyReady; }

	function delayFromNow (timestamp) { return Math.max(0, timestamp - performance.now()); }

	function loadPlugin () {
		if (loaded) return Promise.resolve();
		if (loadingPromise) return loadingPromise;

		// 1) Load the lightweight legacy piano fallback FIRST and prioritise it, so
		// playback is audible as soon as possible. The large GM soundfont (gm.sf3,
		// ~40MB) only starts downloading once the fallback is ready — we don't want
		// the 40MB fetch competing for bandwidth with the small fallback font.
		var legacyPromise;
		if (legacy && legacy.WebAudio && legacy.WebAudio.empty && legacy.WebAudio.empty()) {
			legacyPromise = legacy.loadPlugin({ soundfontUrl: SOUNDFONT_URL, api: 'webaudio' })
				.then(function () { legacyReady = true; log('legacy piano fallback ready'); })
				.catch(function (err) { console.warn('[LilyFluid] legacy fallback failed:', err); });
		} else {
			if (legacy) legacyReady = true;
			legacyPromise = Promise.resolve();
		}

		loadingPromise = (async function () {
			// 2) Wait for the fallback to finish before kicking off the heavy GM load.
			try { await legacyPromise; } catch (e) {}

			// DEBUG: gm.sf3/FluidSynth disabled — stay on the legacy ogg.js fallback.
			if (DISABLE_FLUID) {
				log('FluidSynth DISABLED (DISABLE_FLUID) — using legacy ogg.js fallback only');
				return;
			}

			try {
			// 3) Fetch the 40MB gm.sf3 bytes FIRST, before touching any AudioContext.
			// This is the key to keeping the fallback audible the whole time: if we
			// instead created FluidSynth's AudioContext (+ worklet modules) up-front and
			// only then downloaded the soundfont, TWO suspended AudioContexts (the legacy
			// fallback's and FluidSynth's) would coexist during the long download window.
			// The browser autoplay policy only lets us resume a suspended context
			// synchronously inside a user gesture, and with two of them the single
			// in-gesture resume() couldn't reliably warm BOTH — the legacy one lost and
			// stayed silent (the "fallback plays but no sound until gm.sf3 loads" bug).
			// By deferring all FluidSynth context creation until the bytes are in hand,
			// exactly ONE AudioContext (the legacy fallback) is alive for the whole
			// download, so its in-gesture resume is unambiguous and it actually sounds.
			var sfResp = await fetch(SOUNDFONT_FILE);
			if (!sfResp.ok) throw new Error('gm.sf3 HTTP ' + sfResp.status);
			var sfontBuffer = await sfResp.arrayBuffer();
			log('gm.sf3 fetched (' + sfontBuffer.byteLength + ' bytes); building FluidSynth');

			// Now build the FluidSynth AudioContext + worklet graph and load the font.
			audioCtx = new (window.AudioContext || window.webkitAudioContext)();
			// libfluidsynth must be added before the worklet module.
			await audioCtx.audioWorklet.addModule(LIBFLUIDSYNTH_FILE);
			await audioCtx.audioWorklet.addModule(WORKLET_FILE);

			synth = new window.JSSynth.AudioWorkletNodeSynthesizer();
			synth.init(audioCtx.sampleRate);
			// createAudioNode MUST be called before any other synth method.
			node = synth.createAudioNode(audioCtx);
			node.connect(audioCtx.destination);

			await synth.loadSFont(sfontBuffer);

			seq = await synth.createSequencer();
			await seq.registerSynthesizer(synth);
			seq.setTimeScale(1000);   // 1 tick = 1 ms, matching performance.now()

			// FluidSynth's context is created fresh here, AFTER the user has likely
			// already pressed play (gm.sf3 takes seconds to fetch+decode). Its context
			// therefore starts suspended with no pending user gesture to resume it. Try
			// to resume right away; if the autoplay policy blocks it, the next play()
			// click resumes it synchronously in-gesture and the handoff completes then.
			if (audioCtx.state === 'suspended') { try { await audioCtx.resume(); } catch (e) {} }

			// Hand off from the fallback: silence any lingering notes.
			if (legacyReady && legacy && legacy.stopAllNotes) legacy.stopAllNotes();

			loaded = true;
			failed = false;
			log('FluidSynth soundfont loaded (gm.sf3)');
			} catch (err) {
				// gm.sf3 / FluidSynth load failed (network etc.). Flag it and clear the
				// in-flight promise so retryLoad() can start a fresh attempt. The legacy
				// piano fallback (if it loaded) stays audible regardless.
				failed = true;
				loadingPromise = null;
				console.warn('[LilyFluid] gm.sf3 / FluidSynth load failed:', err);
			}
		})();
		return loadingPromise;
	}

	// Resume audio output; must be called from a user gesture (autoplay policy).
	// A suspended AudioContext can only be resumed *synchronously within a user
	// gesture*, so we fire all resume()/awaitWarmup() calls BEFORE the first await.
	// During the fallback window `audioCtx` is null (FluidSynth's context isn't
	// created until gm.sf3 is fetched — see loadPlugin), so only the legacy WebAudio
	// context exists and gets warmed up here; there's no second context to contend
	// with. Once gm.sf3 has loaded, audioCtx exists and is resumed too.
	function resume () {
		var promises = [];
		if (audioCtx && audioCtx.state === 'suspended') {
			try { promises.push(audioCtx.resume()); } catch (e) {}
		}
		var WA = legacy && legacy.WebAudio;
		if (legacyReady && WA && WA.awaitWarmup) {
			try { promises.push(WA.awaitWarmup()); } catch (e) {}
		}
		return Promise.all(promises).catch(function () {});
	}

	function noteOn (channel, note, velocity, timestamp) {
		if (seq) { seq.sendEventAt({ type: 'noteon', channel: channel, key: note, vel: velocity }, delayFromNow(timestamp), false); return; }
		if (legacyReady && legacy) legacy.noteOn(channel, note, velocity, timestamp);
	}

	function noteOff (channel, note, timestamp) {
		if (seq) { seq.sendEventAt({ type: 'noteoff', channel: channel, key: note }, delayFromNow(timestamp), false); return; }
		if (legacyReady && legacy) legacy.noteOff(channel, note, timestamp);
	}

	function programChange (channel, program) {
		if (seq) { seq.sendEventAt({ type: 'programchange', channel: channel, preset: program }, 0, false); return; }
		if (legacyReady && legacy) legacy.programChange(channel, program);
	}

	// Forward a MIDI control-change event (sustain pedal CC64, volume CC7, pan CC10,
	// expression CC11, etc.) to FluidSynth, which honours them per-channel. Verovio
	// emits these from MEI <pedal>/dynamics, so e.g. sustain-pedal spans play back
	// correctly. The legacy MIDI.js fallback has no CC support, so CC is dropped
	// while it is the active backend (only during the brief soundfont load).
	function controlChange (channel, control, value, timestamp) {
		if (seq) { seq.sendEventAt({ type: 'controlchange', channel: channel, control: control, value: value }, delayFromNow(timestamp), false); return; }
		if (legacyReady && legacy && legacy.controlChange) legacy.controlChange(channel, control, value, timestamp);
	}

	function stopAllNotes () {
		if (seq) seq.removeAllEvents();   // drop the in-flight look-ahead window
		if (synth) {
			for (var ch = 0; ch < 16; ++ch) {
				// Reset the hold pedals BEFORE silencing: removeAllEvents() above may
				// have discarded a not-yet-played pedal-off (CC64=0) that was waiting
				// in the look-ahead window, leaving the channel stuck "sustain on".
				// Any note played afterwards would then hang forever under the phantom
				// pedal. Explicitly lift sustain (CC64), sostenuto (CC66) and soft
				// (CC67) so the channel starts clean.
				synth.midiControl(ch, 64, 0);
				synth.midiControl(ch, 66, 0);
				synth.midiControl(ch, 67, 0);
				synth.midiAllSoundsOff(ch);
			}
		}
		if (legacyReady && legacy && legacy.stopAllNotes) legacy.stopAllNotes();
	}

	window.LilyFluidAudio = {
		init: init,
		empty: empty,
		ready: ready,
		loading: loading,
		failed: function () { return failed; },
		// Retry a previously-failed gm.sf3 load. Clears the failed flag and re-runs
		// loadPlugin (loadingPromise was reset to null in the catch, so this starts fresh).
		retryLoad: function () { failed = false; return loadPlugin(); },
		loadPlugin: loadPlugin,
		resume: resume,
		noteOn: noteOn,
		noteOff: noteOff,
		programChange: programChange,
		controlChange: controlChange,
		stopAllNotes: stopAllNotes,
		// Lightweight diagnostics: backend/AudioContext state. (A scheduled note with
		// no thrown error does NOT prove audio output — for that, tap node with an
		// AnalyserNode in the console.) Handy when troubleshooting "no sound".
		_debug: function () {
			return {
				loaded: loaded, legacyReady: legacyReady,
				ctxState: audioCtx ? audioCtx.state : 'no-ctx',
				hasSeq: !!seq, hasSynth: !!synth, hasNode: !!node,
			};
		},
	};
	log('fluid-audio.js loaded');
})();
