/* LilyScript editor mount + state bridge.
 *
 * Mounts our own CodeMirror 6 editor (window.LilyEditor, from lyl-editor.bundle.js)
 * into #ls-editor-mount and bridges it to a hidden Gradio Textbox (#ls-editor-state),
 * which is the canonical text Gradio reads/writes:
 *
 *   CM edit      -> write hidden <textarea>.value + dispatch native 'input'  -> Gradio
 *                   updates the Python value and fires its .change -> SVG render.
 *   Gradio write -> generation stream / file load set the <textarea>.value; we poll
 *                   for external changes and push them into CM via setValue().
 *
 * An `applyingExternal` flag prevents the echo loop (CM.setValue must not re-emit a
 * change back to the textarea), mirroring live-editor's `isEditorUpdate` guard.
 */
(function () {
	'use strict';

	var MOUNT_ID = 'ls-editor-mount';
	var STATE_ID = 'ls-editor-state';
	var DEBOUNCE_MS = 300;

	var handle = null;        // { getValue, setValue, destroy }
	var textarea = null;
	var lastTextareaValue = null;   // last value we've seen on the textarea
	var applyingExternal = false;   // true while pushing a Gradio value into CM
	var debounceTimer = null;

	function log (msg) { console.log('[lyl-editor]', msg); }

	function ready () {
		return window.LilyEditor && typeof window.LilyEditor.mount === 'function';
	}

	// Write text into the hidden textarea using the native setter (so Svelte/Gradio's
	// controlled <textarea> actually registers it) and dispatch a bubbling 'input'.
	function pushToGradio (text) {
		if (!textarea) return;
		var proto = window.HTMLTextAreaElement && window.HTMLTextAreaElement.prototype;
		var setter = proto && Object.getOwnPropertyDescriptor(proto, 'value');
		if (setter && setter.set) setter.set.call(textarea, text);
		else textarea.value = text;
		lastTextareaValue = text;
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		textarea.dispatchEvent(new Event('change', { bubbles: true }));
	}

	// CM editor -> Gradio (debounced). Skipped while we're applying an external value.
	function onEditorChange (text) {
		if (applyingExternal) return;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(function () { pushToGradio(text); }, DEBOUNCE_MS);
	}

	// Gradio -> CM: when the textarea value changes from OUTSIDE (generation stream,
	// file load), push it into the editor. We diff against lastTextareaValue so our
	// own pushToGradio writes don't bounce back.
	function pollExternal () {
		if (!textarea || !handle) return;
		var v = textarea.value;
		if (v === lastTextareaValue) return;   // unchanged, or our own write
		lastTextareaValue = v;
		applyingExternal = true;
		handle.setValue(v);                    // no-op guarded inside if equal
		applyingExternal = false;
	}

	function attach () {
		var mountEl = document.getElementById(MOUNT_ID);
		var stateWrap = document.getElementById(STATE_ID);
		if (!mountEl || !stateWrap || !ready()) return false;
		// gr.Textbox renders a <textarea> inside its elem_id wrapper.
		var ta = stateWrap.querySelector('textarea');
		if (!ta) return false;
		if (handle && textarea === ta && mountEl.firstChild) return true; // already mounted

		textarea = ta;
		lastTextareaValue = textarea.value;
		// Gradio wraps gr.HTML content in a `.prose` block whose global rule
		// `.gradio-container .prose * { color: var(--body-text-color) }` overrides
		// CodeMirror's per-token syntax colours (it out-specifies CM's atomic class
		// rules). Strip `prose` from the editor's wrapper so CM's oneDark highlight
		// colours win. (Scoped to the editor; the score panel keeps its own.)
		var proseWrap = mountEl.closest('.prose');
		if (proseWrap) proseWrap.classList.remove('prose');
		mountEl.innerHTML = '';
		handle = window.LilyEditor.mount(mountEl, {
			value: textarea.value || '',
			onChange: onEditorChange,
		});
		log('mounted CM editor; initial ' + (textarea.value || '').length + ' chars');
		return true;
	}

	function boot () {
		var mounted = attach();
		if (!mounted) {
			var iv = setInterval(function () { if (attach()) clearInterval(iv); }, 300);
			setTimeout(function () { clearInterval(iv); }, 30000);
		}
		// poll the hidden textarea for external (Gradio-driven) value changes, and
		// re-attach if Gradio re-renders the editor DOM (mount/textarea swapped).
		setInterval(function () {
			var mountEl = document.getElementById(MOUNT_ID);
			var stateWrap = document.getElementById(STATE_ID);
			var ta = stateWrap && stateWrap.querySelector('textarea');
			if (mountEl && ta && (ta !== textarea || !mountEl.firstChild)) { attach(); return; }
			pollExternal();
		}, 200);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}
	log('lyl-editor-mount.js loaded');
})();
