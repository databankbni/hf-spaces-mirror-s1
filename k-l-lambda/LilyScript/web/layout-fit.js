/* LilyScript layout fitter.
 *
 * Sets two CSS variables on :root that drive the workspace panel heights:
 *   --ls-fill-h   height of the bottom "Score List | editor" row (left column)
 *   --ls-sheet-h  height of the right "Sheet music" preview panel
 *
 * Two modes, because the embedding context decides what "fill the screen" means:
 *
 *  • Standalone (the app is the top-level page): size to the real viewport, so the
 *    bottom row fills the space under Compose + Logs and the sheet panel fills the
 *    window. Recompute on resize + when the left column changes (ResizeObserver).
 *
 *  • Embedded in an auto-height iframe (Hugging Face Spaces wraps the Gradio app in
 *    an iframe that grows to fit its content): here window.innerHeight / 100vh are
 *    NOT stable — they track the iframe, which tracks the content, which we'd be
 *    sizing from the viewport… an unbounded feedback loop (the page scroll height
 *    grows forever). So when embedded we use FIXED pixel heights and install no
 *    viewport/resize observers. Nothing references the viewport, so nothing loops.
 */
(function () {
	'use strict';

	var BOTTOM_GAP = 16;       // breathing room below the fill row (standalone)
	var MIN_FILL = 360;        // floor for the bottom row
	// Fixed heights used when embedded (no viewport to measure against).
	var EMBED_FILL_H = 460;    // Score List | editor row
	var EMBED_SHEET_H = 720;   // Sheet music preview

	// True when running inside an iframe (HF Spaces, blog embeds, etc.). Accessing
	// window.top across origins throws — treat that as "embedded" too.
	var embedded = (function () {
		try { return window.self !== window.top; } catch (e) { return true; }
	})();

	function setVar (name, px) {
		document.documentElement.style.setProperty(name, px + 'px');
	}

	function fillEl () {
		var col = document.getElementById('compose-col');
		return col ? col.querySelector(':scope > .lp-fill') : null;
	}

	// Standalone: derive the bottom row height from the live viewport.
	function recompute () {
		var fill = fillEl();
		if (!fill) return;
		var top = fill.getBoundingClientRect().top;        // viewport-relative
		var avail = window.innerHeight - top - BOTTOM_GAP;
		if (avail < MIN_FILL) avail = MIN_FILL;
		setVar('--ls-fill-h', avail);
		setVar('--ls-sheet-h', Math.max(320, window.innerHeight - 110));
	}

	var raf = null;
	function schedule () {
		if (raf) return;
		raf = requestAnimationFrame(function () { raf = null; recompute(); });
	}

	function boot () {
		var col = document.getElementById('compose-col');

		if (embedded) {
			// Fixed heights — no viewport reads, no observers, no loop.
			setVar('--ls-fill-h', EMBED_FILL_H);
			setVar('--ls-sheet-h', EMBED_SHEET_H);
			if (!col) setTimeout(boot, 300);   // wait for Gradio to mount, then set once
			return;
		}

		recompute();
		window.addEventListener('resize', schedule);
		if (col && window.ResizeObserver) {
			var ro = new ResizeObserver(schedule);
			ro.observe(col);
			// the two fixed blocks (Compose, Logs) drive the fill row's top
			var fixed = col.querySelectorAll(':scope > .lp-fixed');
			for (var i = 0; i < fixed.length; i++) ro.observe(fixed[i]);
		}
		if (!col) setTimeout(boot, 300);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}
	if (!embedded) setTimeout(recompute, 1200);   // late pass after fonts/player settle
	console.log('[layout-fit] loaded (embedded=' + embedded + ')');
})();
