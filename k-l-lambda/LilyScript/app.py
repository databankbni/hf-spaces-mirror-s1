"""LilyScript — a symbolic-music AIGC app built on the LilyletNotaGen model.

Left column:
  (1) generation parameter panel   (2) streaming run log
  (3) .lyl file list (session outputs + built-in examples)   (4) editable lyl editor
Right column:
  sheet-music panel (placeholder for now; later a Lilylet music score renderer
  reusing the lilylet-live-editor pipeline).

Generation streams patch-by-patch: raw decoded text (with `[r:x/y]` stream
markers) goes to the run log, while the measure-segmented postprocessed text
fills the editor. The backend is the int8 + two-level KV-cache ONNX generator
(see lilyscript/generator.py); weights are pulled from the HF model repo
`k-l-lambda/LilyNota` on first use (override with LILYSCRIPT_MODEL_DIR locally).
"""

import os
import re
import time
import json
import random
import logging
from collections import deque

import gradio as gr

from starlette.middleware.base import BaseHTTPMiddleware

from lilyscript.generator import StreamingLilyletGenerator
from lilyscript.postprocess import postprocess
from lilyscript.mask_monitor import MaskMonitor, load_blacklist
from lilyscript.lang import T, LANG

HERE = os.path.dirname(os.path.abspath(__file__))
# Model weights are pulled from a model hub at first use (the int8 + KV-cache ONNX
# bundle lives under its `onnx/` dir). The repo is configured via LILYSCRIPT_MODEL_REPO:
#   - "owner/name"            -> HuggingFace Hub (default)
#   - "modelscope:owner/name" -> ModelScope hub (for users behind the GFW / in China)
# For local development, point LILYSCRIPT_MODEL_DIR at a local onnx dir to skip the
# download, or drop the bundle into the repo-local `models/` dir.
HF_MODEL_REPO = os.environ.get('LILYSCRIPT_MODEL_REPO', 'k-l-lambda/LilyNota')
HF_MODEL_SUBDIR = 'onnx'		# weights + geometry + tokenizer live here in the repo
MODEL_DIR = os.environ.get('LILYSCRIPT_MODEL_DIR')		# set -> use this local dir instead of the hub
LOCAL_MODEL_DIR = os.path.join(HERE, 'models')		# repo-local onnx bundle; preferred over the hub when present
ASSET_DIR = os.path.join(HERE, 'assets')
EXAMPLES_DIR = os.path.join(HERE, 'examples')
OUTPUT_DIR = os.path.join(HERE, 'outputs')
WEB_DIR = os.path.join(HERE, 'web')		# vendored browser libs + score player (gitignored bundles)


# Gradio serves our vendored web/ assets (soundfont gm.sf3 ~38 MB, verovio.bundle.js ~8 MB,
# libfluidsynth ~2 MB, …) via `/gradio_api/file=<abs-path>` with NO Cache-Control header, so the
# browser re-validates (or refetches) them on every load. These are large, static, and effectively
# immutable per deploy — bundles carry a `?v=<mtime>` cache-buster (see _file_url), and the soundfont
# rarely changes. This middleware adds a long-lived Cache-Control to responses for web/ assets so
# returning visitors reuse them from the browser cache instead of re-downloading. It runs inside our
# own app.py, so it applies on Hugging Face and ModelScope Spaces (where we are the server), unlike a
# static-host CDN we couldn't configure.
_WEB_ASSET_MARKER = '/web/'
_CACHEABLE_EXTS = ('.sf3', '.sf2', '.js', '.wasm', '.css', '.mp3', '.ogg')


class AssetCacheHeaderMiddleware(BaseHTTPMiddleware):
	async def dispatch (self, request, call_next):
		response = await call_next(request)
		# Only touch Gradio's static-file route for our vendored web/ assets, and only if a
		# Cache-Control wasn't already set. request.url.path holds the decoded `/gradio_api/file=...`.
		path = request.url.path
		if (
			'/file=' in path
			and _WEB_ASSET_MARKER in path
			and path.endswith(_CACHEABLE_EXTS)
			and 'cache-control' not in {k.lower() for k in response.headers.keys()}
		):
			# 30 days. Safe: bundle URLs change via ?v=<mtime> on redeploy; soundfont is stable.
			response.headers['Cache-Control'] = 'public, max-age=2592000'
		return response

EXAMPLE_PREFIX = '\U0001F4C4 '		# 📄 examples
OUTPUT_PREFIX = '✨ '			# ✨ session outputs

# Suggested metadata values (editable — the dropdowns allow custom input), loaded
# from assets/styles.json. Drawn from the NotaGenX period/instrumentation
# vocabulary + values seen in examples.
_STYLES = json.load(open(os.path.join(ASSET_DIR, 'styles.json'), encoding='utf-8'))
COMPOSERS = _STYLES['composers']
PERIODS = _STYLES['periods']
GENRES = _STYLES['genres']

_GEN = None

# Syntax-blacklist mask: discovered 2-grams whose forbidden next-tokens are masked
# during sampling so the model can't emit those locally-illegal continuations.
# Loaded once at startup; a fresh (stateful) MaskMonitor is built per generation.
# Empty/missing file -> no masking (behavior unchanged).
BLACKLIST_PATH = os.path.join(ASSET_DIR, 'lilylet-blacklist.json')
_BLACKLIST = load_blacklist(BLACKLIST_PATH)


# ---- system log capture ----------------------------------------------------
# A ring buffer that mirrors Python logging (lifecycle messages, warnings, and
# errors) into the Logs panel, alongside the streamed generation text.

LOG = logging.getLogger('lilyscript')


class _RingBufferHandler (logging.Handler):
	'''Keep the most recent N log records as formatted strings.'''
	def __init__ (self, capacity=400):
		super().__init__()
		self.records = deque(maxlen=capacity)

	def emit (self, record):
		try:
			self.records.append(self.format(record))
		except Exception:
			pass

	def text (self):
		return '\n'.join(self.records)


_LOG_BUFFER = _RingBufferHandler()
_LOG_BUFFER.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S'))


def _init_logging ():
	'''Route app + library logs and Python warnings into the ring buffer (once),
	and also echo to stderr so the terminal keeps a copy.'''
	logging.captureWarnings(True)
	root = logging.getLogger()
	if _LOG_BUFFER not in root.handlers:
		root.addHandler(_LOG_BUFFER)
		stderr_h = logging.StreamHandler()
		stderr_h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S'))
		root.addHandler(stderr_h)
	root.setLevel(logging.INFO)
	LOG.setLevel(logging.INFO)


_init_logging()


def resolve_model_dir ():
	'''Where the ONNX weights live, in priority order:
	  1. LILYSCRIPT_MODEL_DIR (explicit override, local dev),
	  2. the repo-local `models/` dir IF it holds the full weight bundle,
	  3. otherwise pull the `onnx/` bundle from the configured model hub
	     (HuggingFace by default; ModelScope when LILYSCRIPT_MODEL_REPO is
	     prefixed with `modelscope:`).
	The tokenizer is NOT pulled — it's read from the app's own assets/ dir — so we
	only fetch the weight files.'''
	if MODEL_DIR:
		return MODEL_DIR
	required = ('geometry.json', 'patch_kv_int8.onnx', 'token_kv_int8.onnx', 'wte.npy')
	if os.path.isdir(LOCAL_MODEL_DIR) and all(
			os.path.isfile(os.path.join(LOCAL_MODEL_DIR, name)) for name in required):
		LOG.info('using local model weights in %s', LOCAL_MODEL_DIR)
		return LOCAL_MODEL_DIR
	# Only the four weight files under `onnx/` are needed (the tokenizer is local).
	patterns = [f'{HF_MODEL_SUBDIR}/{name}' for name in required]
	# Dispatch on the `modelscope:` prefix. Both hubs' snapshot_download share the
	# `allow_patterns` semantics (glob over repo-relative paths) and return the local
	# snapshot root, so the `onnx/` subdir join below is the same for either backend.
	if HF_MODEL_REPO.startswith('modelscope:'):
		repo_id = HF_MODEL_REPO[len('modelscope:'):]
		try:
			from modelscope.hub.snapshot_download import snapshot_download
		except ImportError as e:
			raise RuntimeError(
				'LILYSCRIPT_MODEL_REPO is set to a modelscope: repo but the modelscope '
				'package is not installed. Run `pip install modelscope` (see requirements.txt).'
			) from e
		LOG.info('downloading model weights from modelscope:%s (%s/) ...', repo_id, HF_MODEL_SUBDIR)
		local = snapshot_download(repo_id, allow_patterns=patterns)
	else:
		from huggingface_hub import snapshot_download
		LOG.info('downloading model weights from hf:%s (%s/) ...', HF_MODEL_REPO, HF_MODEL_SUBDIR)
		local = snapshot_download(repo_id=HF_MODEL_REPO, allow_patterns=patterns)
	return os.path.join(local, HF_MODEL_SUBDIR)


def get_generator ():
	'''Lazily build the (heavy) ONNX generator on first use.'''
	global _GEN
	if _GEN is None:
		model_dir = resolve_model_dir()
		LOG.info('loading ONNX generator from %s ...', model_dir)
		t0 = time.perf_counter()
		_GEN = StreamingLilyletGenerator(model_dir, ASSET_DIR)
		LOG.info('generator ready (%.1fs)', time.perf_counter() - t0)
		LOG.info('syntax blacklist: %d contexts / %d forbidden pairs from %s',
			len(_BLACKLIST), sum(len(v) for v in _BLACKLIST.values()), BLACKLIST_PATH)
	return _GEN


def load_examples ():
	'''Read built-in example .lyl files into a {label: text} dict.

	Examples may be stored raw (with inline `[r:x/y]` stream markers and
	run-together header lines); run them through `postprocess` so the editor —
	and the score renderer it feeds — get syntactically clean Lilylet. It's a
	no-op on already-clean text.'''
	store = {}
	if os.path.isdir(EXAMPLES_DIR):
		for name in sorted(os.listdir(EXAMPLES_DIR)):
			if name.endswith('.lyl'):
				with open(os.path.join(EXAMPLES_DIR, name), encoding='utf-8') as f:
					store[EXAMPLE_PREFIX + name] = postprocess(f.read())
	return store


def load_outputs ():
	'''Read previously-generated .lyl files from the outputs dir into a
	{label: text} dict, so past session outputs survive a server restart.'''
	store = {}
	exists = os.path.isdir(OUTPUT_DIR)
	names = sorted(os.listdir(OUTPUT_DIR)) if exists else []
	lyls = [n for n in names if n.endswith('.lyl')]
	LOG.info('load_outputs: OUTPUT_DIR=%s exists=%s total_entries=%d lyl_files=%d',
		OUTPUT_DIR, exists, len(names), len(lyls))
	if exists:
		for name in lyls:
			with open(os.path.join(OUTPUT_DIR, name), encoding='utf-8') as f:
				store[OUTPUT_PREFIX + name[:-4]] = f.read()
	return store


def load_library ():
	'''Initial file list: built-in examples + any persisted session outputs.'''
	return {**load_examples(), **load_outputs()}


def refresh_library ():
	'''Re-read the library from disk and return updates for (store, file_list).

	Wired to demo.load so EVERY new session / page refresh picks up outputs that
	were generated after server boot. Without this, store=gr.State(examples) and the
	Radio's choices are frozen at the boot-time snapshot, so a refresh drops any
	freshly-generated score from the Score List even when it persisted to disk.'''
	lib = load_library()
	LOG.info('refresh_library: %d entries (%d examples + %d outputs)',
		len(lib), len(load_examples()), len(load_outputs()))
	return lib, gr.update(choices=list(lib.keys()))


# A managed style line in the new `--styles-in-comments` format: a leading `%<value>`
# comment carrying period / composer / instrumentation (one per line). `sync_prompt`
# regenerates these from the dropdowns; any other line the user typed is preserved.
_STYLE_LINE_RE = re.compile(r'^%(?!%).*$')


def sync_prompt (composer, period, genre, current):
	'''Rewrite the metadata-prompt text from the three style dropdowns.

	The model is trained on the `--styles-in-comments` format: style is carried by
	leading `%<value>` comment lines, ordered period/composer/instrumentation (matching
	abc2lilylet's catalogCommentLines: %<period> / %<composer> / %<genre>). These
	are regenerated from the dropdowns and placed at the top; any other line the user
	typed (e.g. a `[staves "..."]` header) is preserved below in its original order.
	'''
	lines = []
	for value in (period, composer, genre):
		value = (value or '').strip()
		if value:
			lines.append(f'%{value}')
	# keep every line that isn't one of the managed `%<style>` lines
	for ln in (current or '').splitlines():
		if not _STYLE_LINE_RE.match(ln.strip()):
			if ln.strip():
				lines.append(ln)
	return '\n'.join(lines)


# Marker line written to the log buffer at the moment generation output begins.
# `_log_panel` replaces this marker with the live generation text, so the streamed
# output appears in true chronological position — after the "requested"/"ready"
# lines and before the later "timing"/"done" lines.
_GEN_MARKER = '⁣__GENERATION_OUTPUT__⁣'


def _log_panel (raw=''):
	'''Render the Logs panel in chronological order: the captured system log,
	with the generation-output marker (if present) expanded to the live text.'''
	sys_log = _LOG_BUFFER.text()
	if _GEN_MARKER in sys_log:
		block = '--- generation output ---\n' + raw if raw else '--- generation output ---'
		return sys_log.replace(_GEN_MARKER, block)
	# no marker yet (e.g. before generation): fall back to appending raw
	if raw:
		return (sys_log + '\n' if sys_log else '') + '--- generation output ---\n' + raw
	return sys_log


def run_generation (prompt, measures, temperature, max_patches, seed, store, top_k=0, top_p=0.9):
	'''Streaming generate callback. Yields updates for (log, editor, file_list, store, seed, gen_btn).

	store: {label: lyl_text} dict held in gr.State; the produced document is added
	to it under a timestamped label once generation finishes.

	top_k / top_p have fixed defaults (no UI controls); pass them explicitly to override.

	Progress is shown on the Generate button itself: its label becomes
	"Generating… M/N" (by completed measures when a measure count is requested, else
	by patches out of max_patches) during the run, and reverts to "Generate" at the
	end. (Gradio's native progress bar can't render on a Button, so we drive the
	label directly.)

	The output file is named with the seed used for THIS generation; on completion
	the seed slider is randomized (final yield) so the next click uses a fresh seed.
	'''
	meas = int(measures) if measures and int(measures) > 0 else None
	store = dict(store or {})
	LOG.info('generation requested: measures=%s temperature=%s max_patches=%s seed=%s',
		meas, temperature, max_patches, seed)

	raw = pretty = ''
	n_yields = 0
	mp = int(max_patches)
	t0 = time.perf_counter()
	try:
		gen = get_generator()
		# build a fresh per-run mask monitor (stateful: tracks the running 2-gram).
		# None when no blacklist is loaded -> sampling path unchanged.
		monitor = MaskMonitor(gen, _BLACKLIST) if _BLACKLIST else None
		# drop a marker in the log timeline; _log_panel expands it to the live output,
		# so subsequent log lines (timing/done) land *after* the generation text.
		LOG.info(_GEN_MARKER)
		for raw, pretty, done in gen.generate_stream(
			prompt_text=prompt or '', max_patches=mp, temperature=float(temperature),
			top_k=int(top_k), top_p=float(top_p), measures=meas, seed=int(seed), monitor=monitor):
			if not done:
				n_yields += 1
			# progress on the Generate button label: by measures (completed `|`
			# separators vs target) when a measure count was requested, else by patches.
			if meas:
				btn_label = T('generating') % (min(raw.count('|'), meas), meas)
			else:
				btn_label = T('generating') % (max(0, n_yields - 1), mp)
			# The log streams every patch (raw text). The editor, however, must stay
			# syntactically valid: only sync it at a measure boundary — i.e. when the
			# accumulated text ends with the measure separator `|` (so it never shows a
			# half-generated, incomplete measure). `done` forces a final sync.
			at_boundary = raw.rstrip().endswith('|')
			editor_update = pretty if (at_boundary or done) else gr.update()
			yield _log_panel(raw), editor_update, gr.update(), store, gr.update(), gr.update(value=btn_label)
	except Exception as e:
		LOG.exception('generation failed: %s', e)
		yield _log_panel(raw), pretty, gr.update(), store, gr.update(), gr.update(value=T('generate'))
		return

	# timing: the stream yields once for prefill + once per generated patch, so the
	# patch count is the non-done yields minus that initial prefill yield.
	elapsed = time.perf_counter() - t0
	n_patches = max(0, n_yields - 1)
	per_patch = (elapsed / n_patches) if n_patches else 0.0
	LOG.info('timing: %.2fs total, %d patches, %.3fs/patch (%.1f patches/s)',
		elapsed, n_patches, per_patch, (n_patches / elapsed if elapsed else 0.0))

	# finished: persist the document, refresh the file list, select the new entry
	label = OUTPUT_PREFIX + time.strftime('%Y%m%d_%H%M%S') + ('_m%d' % meas if meas else '') + '_s%d' % int(seed)
	store[label] = pretty
	out_path = os.path.join(OUTPUT_DIR, label.replace(OUTPUT_PREFIX, '') + '.lyl')
	# Persist to disk so the output survives a page refresh / server restart. On some
	# hosts (e.g. a ModelScope studio) the project dir may be read-only or the
	# container's filesystem ephemeral, so a write can fail or silently not persist —
	# log the outcome (and don't let a write error kill the final yield, which would
	# leave the new entry out of the Score List even in-session).
	saved = False
	try:
		os.makedirs(OUTPUT_DIR, exist_ok=True)
		with open(out_path, 'w', encoding='utf-8') as f:
			f.write(pretty)
		size = os.path.getsize(out_path)
		saved = os.path.isfile(out_path)
		LOG.info('generation done: %d chars -> %s (saved=%s, on_disk_size=%d, dir_writable=%s)',
			len(pretty), out_path, saved, size, os.access(OUTPUT_DIR, os.W_OK))
		# list what's actually on disk right after the write, to catch ephemeral-FS cases
		on_disk = [n for n in os.listdir(OUTPUT_DIR) if n.endswith('.lyl')]
		LOG.info('outputs dir now holds %d .lyl file(s): %s', len(on_disk), on_disk)
	except Exception as e:
		LOG.exception('FAILED to persist generated score to %s: %s', out_path, e)
	# randomize the seed slider for the next run (the file above already used the
	# seed this generation ran with, so naming is unaffected)
	next_seed = random.randint(0, 2147483647)
	yield _log_panel(raw), pretty, gr.update(choices=list(store.keys()), value=label), store, gr.update(value=next_seed), gr.update(value=T('generate'))


def load_file (label, store):
	'''File-list selection -> load that document into the editor.'''
	return (store or {}).get(label, '')


SHEET_PLACEHOLDER = '''
<div id="ls-score" class="ls-score-mount" style="height:100%%;min-height:600px;">
	<!-- Self-contained loading placeholder. The spinner styles + keyframes are INLINE
	     (not in score-player.css) on purpose: on a slow host (e.g. ModelScope) this
	     static HTML is shown for a long time WHILE the vendored scripts and CSS are
	     still downloading, so the animation must not depend on any external resource.
	     Once score-player.js mounts, it replaces this whole node. -->
	<style>
		@keyframes ls-ph-spin { to { transform: rotate(360deg); } }
		#ls-score .ls-loading-placeholder {
			display: flex; flex-direction: column; align-items: center; justify-content: center;
			height: 100%%; min-height: 600px; border: 1px dashed #c9c9c9; border-radius: 8px;
			color: #999; font-family: sans-serif; text-align: center;
		}
		#ls-score .ls-loading-spinner {
			width: 38px; height: 38px; margin-bottom: 14px;
			border: 4px solid #e3e3ea; border-top-color: #7c5cff; border-radius: 50%%;
			animation: ls-ph-spin 0.8s linear infinite;
		}
		#ls-score .ls-loading-text { font-size: 14px; }
		@media (prefers-reduced-motion: reduce) {
			#ls-score .ls-loading-spinner { animation: ls-ph-spin 2.4s linear infinite; }
		}
	</style>
	<div class="ls-loading-placeholder">
		<div class="ls-loading-spinner" aria-hidden="true"></div>
		<div class="ls-loading-text">%s</div>
	</div>
</div>
''' % T('loading_renderer')


# Static-file URL prefix Gradio serves allowed_paths under (verified at 6.18.0).
# For real files we append a `?v=<mtime>` cache-buster so a redeploy that changes
# a vendored bundle / player script is picked up immediately instead of being
# served from the browser (or a CDN/proxy) cache under the same URL. Directories
# (soundfont, fluid) are passed through unchanged — the caller concatenates a
# trailing '/' + subpath, which a query string would corrupt; their individual
# assets are content-addressed / rarely change anyway.
def _file_url (path):
	url = '/gradio_api/file=' + path
	try:
		if os.path.isfile(path):
			url += '?v=%d' % int(os.path.getmtime(path))
	except OSError:
		pass
	return url


def build_head ():
	'''<head> injection: load the vendored browser libs (lilylet bundle, Verovio
	WASM, music-widgets) then the score player, and point the soundfont loader at
	the vendored copy. Gradio delivers this via its client config and injects it
	on the frontend, so absolute `/gradio_api/file=` URLs resolve correctly.'''
	vendor = os.path.join(WEB_DIR, 'vendor')
	# ORDER MATTERS for cold-load UX. score-player.js (28KB) defines window.LilyScore
	# and self-mounts the player as soon as it executes, replacing the loading spinner.
	# The heavy deps it uses — verovio.bundle.js (7.6MB!), music-widgets, the FluidSynth
	# adapter — are accessed LAZILY (initVerovio/initAudio await their globals via
	# waitForGlobal), so they must NOT block score-player.js from running. We therefore
	# load score-player.js FIRST; if it sat behind verovio (synchronous <head> order),
	# a slow cold load would leave the spinner stuck for the whole 7.6MB download before
	# LilyScore — and the self-mount inside it — could run. lilylet.bundle.js stays ahead
	# because lylToMei() needs window.LilyletLib synchronously at render time (no waiter).
	scripts = [
		os.path.join(WEB_DIR, 'score-player.js'),        # defines LilyScore + self-mounts (load first!)
		os.path.join(vendor, 'lilylet.bundle.js'),       # window.LilyletLib (used synchronously by lylToMei)
		os.path.join(vendor, 'verovio.bundle.js'),       # 7.6MB; awaited lazily via VerovioInit
		os.path.join(vendor, 'musicWidgetsBrowser.umd.min.js'),
		# FluidSynth audio backend: js-synthesizer UMD (window.JSSynth) + our adapter
		# (window.LilyFluidAudio). score-player.js awaits these lazily in initAudio()
		# (no longer a hard ordering requirement). The libfluidsynth runtime + gm.sf3 are
		# loaded on demand by the adapter from web/fluid/ and web/soundfont/.
		os.path.join(vendor, 'js-synthesizer.min.js'),
		os.path.join(WEB_DIR, 'fluid-audio.js'),
		# our own CodeMirror 6 editor (CM + grammar-derived lilylet() highlighter) and
		# the mount/bridge script that wires it to the hidden #ls-editor-state textbox.
		os.path.join(vendor, 'lyl-editor.bundle.js'),
		os.path.join(WEB_DIR, 'lyl-editor-mount.js'),
		# pako (deflate) + js-base64: used by the "Open in live-editor" share link to
		# compress+url-safe-base64 the editor text into a ?code= param, matching
		# lilylet-live-editor's share.ts encoding exactly. Expose window.pako/Base64.
		os.path.join(vendor, 'pako_deflate.min.js'),
		os.path.join(vendor, 'js-base64.js'),
		# computes --ls-fill-h so the bottom Score List | editor row fills the height
		# left under Compose + Logs (robust against Gradio's flex-nesting quirks).
		os.path.join(WEB_DIR, 'layout-fit.js'),
	]
	tags = ['<script>window.__LILYSCRIPT_SOUNDFONT_URL=%r;window.__LILYSCRIPT_FLUID_URL=%r;window.__LILYSCRIPT_LOADING_RENDERER=%s;window.__LILYSCRIPT_EMPTY_SCORE=%s;window.__LILYSCRIPT_RENDERER_FAILED=%s;</script>'
		% (_file_url(os.path.join(WEB_DIR, 'soundfont')) + '/',
		   _file_url(os.path.join(WEB_DIR, 'fluid')) + '/',
		   json.dumps(T('loading_renderer')),
		   json.dumps(T('empty_score')),
		   json.dumps(T('renderer_failed')))]
	tags.append('<link rel="stylesheet" href="%s">' % _file_url(os.path.join(WEB_DIR, 'score-player.css')))
	tags.append('<link rel="stylesheet" href="%s">' % _file_url(os.path.join(WEB_DIR, 'lyl-editor.css')))
	for s in scripts:
		tags.append('<script src="%s"></script>' % _file_url(s))
	return '\n'.join(tags)


# ---- client-side glue (Gradio `js=` handlers) -------------------------------
# These run in the browser. They wait for LilyScore (score-player.js) to load,
# then mount it into #ls-score and drive render / generation-gating.

_JS_HELPERS = '''
function () {
	// NB: mounting the score player into #ls-score is handled by score-player.js
	// itself (event-driven self-mount via MutationObserver — see web/score-player.js).
	// We deliberately do NOT poll-and-mount here: on a cold load over a slow link the
	// 7.6MB verovio.bundle.js ahead of score-player.js in <head> can take well over a
	// minute to arrive, so any fixed-deadline poll here would expire before LilyScore
	// is even defined and leave the loading spinner stuck forever.

	// Initial render on RELOAD/restore. Gradio repopulates the hidden #ls-editor-state
	// textbox with the previous score on a page reload but does NOT fire a `change`
	// event, so the normal change->render path never runs and the sheet stays blank.
	// This is self-healing against the reload race (mount, Gradio's textbox restore,
	// and Verovio init all settle at different times): poll until an SVG has actually
	// appeared, re-calling render each tick while the editor has text but no SVG is
	// shown yet. render() has a lastCode no-op guard, so repeat calls with the same
	// text are cheap once it has succeeded. On a FRESH deep-link load the editor
	// starts empty and the radio-click path renders it, so the SVG shows up and this
	// loop stops without ever calling render itself (no double render).
	{
		let rtries = 0;
		const initialRender = () => {
			const root = document.getElementById('ls-score');
			const shown = root && root.querySelector('.ls-svg svg');
			if (shown) return;                       // something rendered — done
			const ta = document.querySelector('#ls-editor-state textarea');
			const txt = ta && ta.value;
			if (window.LilyScore && root && txt && txt.trim()) {
				try { window.LilyScore.render(txt); } catch (e) {}
			}
			if (++rtries < 100) setTimeout(initialRender, 150);
		};
		initialRender();
	}

	// Deep-link: if the URL carries #score=<file>, select that Score List entry on
	// first load (so a bookmarked/shared score opens directly). We strip the leading
	// emoji prefix (📄/✨) when comparing, and click the matching radio input — that
	// fires Gradio's .select handler, which loads the file into the editor exactly
	// as a manual click would. Poll until the radio list is populated.
	const stripPrefix = (s) => (s || '').replace(/^\\s*[\\u{1F4C4}\\u2728]\\s*/u, '').trim();
	const m = (location.hash || '').match(/(?:^#|&)score=([^&]*)/);
	if (m) {
		const want = decodeURIComponent(m[1]);
		let tries = 0;
		const pick = () => {
			const labels = document.querySelectorAll('.score-list label');
			if (!labels.length) { if (++tries < 100) setTimeout(pick, 150); return; }
			for (const lab of labels) {
				const span = lab.querySelector('span');
				const text = stripPrefix(span ? span.textContent : lab.textContent);
				if (text === want) {
					const input = lab.querySelector('input');
					if (input && !input.checked) input.click();
					return;
				}
			}
			if (++tries < 40) setTimeout(pick, 150);   // list may still be filling
		};
		pick();
	}
}
'''

# file-list selection -> write the chosen file into location.hash (#score=<file>) so
# the URL deep-links to it. This is a js-ONLY listener (no python fn) running beside
# the load_file handler; `value` is the selected radio label. Strip the emoji prefix
# for a clean, shareable hash. Returning [] is fine — there are no outputs.
_JS_SELECT_HASH = '''
function (value) {
	try {
		const name = (value || '').replace(/^\\s*[\\u{1F4C4}\\u2728]\\s*/u, '').trim();
		if (name) history.replaceState(null, '', '#score=' + encodeURIComponent(name));
	} catch (e) {}
	return [];
}
'''

# Share button: copy the current deep-link URL to the clipboard and flash a hint.
#
# iframe notes (this app is embedded in a cross-origin iframe on HF Spaces):
#  - location.href ALWAYS reads THIS frame's own document URL — the Gradio app's
#    direct URL incl. the #score=<file> hash — even inside a cross-origin iframe.
#    The same-origin policy only blocks reading window.parent/window.top.location,
#    not your own frame's. So this is exactly the shareable deep-link; the outer
#    huggingface.co/spaces URL is both unreadable AND wrong (it has no hash).
#  - navigator.clipboard.writeText may be blocked by Permissions-Policy in a
#    cross-origin iframe (needs allow="clipboard-write", which the HF embed may not
#    grant). So we try the async Clipboard API first and fall back to a hidden
#    <textarea> + document.execCommand('copy'), which works from a user gesture.
_JS_SHARE = '''
function () {
	const stripPrefix = (s) => (s || '').replace(/^\\s*[\\u{1F4C4}\\u2728]\\s*/u, '').trim();
	const flash = (msg, ok) => {
		const btn = document.getElementById('ls-share-btn');
		if (!btn) return;
		let hint = document.getElementById('ls-share-hint');
		if (!hint) {
			hint = document.createElement('span');
			hint.id = 'ls-share-hint';
			hint.className = 'ls-share-hint';
			btn.insertAdjacentElement('afterend', hint);
		}
		hint.textContent = msg;
		hint.classList.toggle('ls-share-err', !ok);
		hint.classList.add('show');
		clearTimeout(hint._t);
		hint._t = setTimeout(() => hint.classList.remove('show'), 2200);
	};
	// Determine the selected score. Prefer the live #score= hash, but fall back to the
	// currently-checked Score List radio: when a fresh generation auto-selects its new
	// file, that happens via Gradio setting the Radio value (NOT a user click), so the
	// js-only select listener never fires and the hash is stale/empty. Reading the
	// checked radio here covers both generation-selection and click-selection, and we
	// (re)write the hash so the copied URL always deep-links to the right score.
	let name = '';
	const m = (location.hash || '').match(/(?:^#|&)score=([^&]*)/);
	if (m) { try { name = decodeURIComponent(m[1]); } catch (e) { name = ''; } }
	if (!name) {
		const checked = document.querySelector('.score-list input:checked');
		if (checked) {
			const lab = checked.closest('label');
			const span = lab && lab.querySelector('span');
			name = stripPrefix(span ? span.textContent : (lab ? lab.textContent : ''));
		}
	}
	if (!name) { flash('Select a score first', false); return []; }
	try { history.replaceState(null, '', '#score=' + encodeURIComponent(name)); } catch (e) {}
	const url = location.href;
	const fallback = () => {
		try {
			const ta = document.createElement('textarea');
			ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
			document.body.appendChild(ta); ta.focus(); ta.select();
			const ok = document.execCommand('copy');
			document.body.removeChild(ta);
			flash(ok ? 'Link copied!' : 'Copy failed — select & copy manually', ok);
		} catch (e) {
			flash('Copy failed — select & copy manually', false);
		}
	};
	try {
		if (navigator.clipboard && navigator.clipboard.writeText) {
			navigator.clipboard.writeText(url).then(
				() => flash('Link copied!', true),
				() => fallback()
			);
		} else { fallback(); }
	} catch (e) { fallback(); }
	return [];
}
'''

# Open the current editor text in lilylet-live-editor. We compress the text exactly
# as the editor's share.ts does — JSON.stringify({code}) -> pako.deflate(level 9) ->
# URL-safe base64 — and put it in ?code=<...>, then open the deployed editor in a new
# tab. window.pako / window.Base64 come from the vendored UMD bundles (build_head).
# Reads the text from the hidden #ls-editor-state <textarea> (the canonical editor
# value). No-op with a hint if empty or the libs failed to load.
_LIVE_EDITOR_URL = 'https://k-l-lambda.github.io/lilylet-live-editor/'
_JS_LIVE_EDITOR = '''
function () {
	const flash = (msg, ok) => {
		const btn = document.getElementById('ls-live-btn');
		if (!btn) return;
		let hint = document.getElementById('ls-share-hint');
		if (!hint) {
			hint = document.createElement('span');
			hint.id = 'ls-share-hint';
			hint.className = 'ls-share-hint';
			const sb = document.getElementById('ls-share-btn');
			(sb || btn).insertAdjacentElement('afterend', hint);
		}
		hint.textContent = msg;
		hint.classList.toggle('ls-share-err', !ok);
		hint.classList.add('show');
		clearTimeout(hint._t);
		hint._t = setTimeout(() => hint.classList.remove('show'), 2200);
	};
	try {
		const ta = document.querySelector('#ls-editor-state textarea');
		const code = ta && ta.value;
		if (!code || !code.trim()) { flash('Editor is empty', false); return []; }
		if (!window.pako || !window.Base64) { flash('Encoder not loaded', false); return []; }
		const json = JSON.stringify({ code: code });
		const compressed = window.pako.deflate(json, { level: 9 });
		const encoded = window.Base64.fromUint8Array(compressed, true);   // URL-safe
		const url = '%s' + '?code=' + encoded;
		window.open(url, '_blank', 'noopener');
	} catch (e) {
		flash('Could not build link', false);
	}
	return [];
}
''' % _LIVE_EDITOR_URL


# Render the editor text to SVG. The text is passed in by Gradio as the event's
# input value (the hidden #ls-editor-state textbox, kept in sync with the embedded
# CodeMirror editor) — taking the value as an argument gives the full text directly,
# no DOM scraping needed. Also toggles the "Open in live-editor" button: shown only
# when the editor has non-empty text (the link needs content to encode).
_JS_RENDER = '''
function (text) {
	if (window.LilyScore) window.LilyScore.render(text || '');
	try {
		const live = document.getElementById('ls-live-btn');
		if (live) live.classList.toggle('ls-hidden', !(text && text.trim()));
	} catch (e) {}
	return [];
}
'''

# NB: when js= runs before a backend fn, Gradio passes the event's input values
# to the js function and uses its RETURN value as the fn's inputs. So the gate
# must return its args unchanged — returning nothing makes Gradio send null for
# every input (which breaks e.g. the temperature Slider's preprocessor).
_JS_GEN_START = '''
function (...args) {
	if (window.LilyScore) window.LilyScore.setGenerating(true);
	// turn Generate yellow + Stop red while running
	['gen-btn', 'stop-btn'].forEach(function (idv) {
		const b = document.getElementById(idv);
		if (b) b.classList.add('ls-generating');
	});
	return args;
}
'''

_JS_GEN_END = '''
function () {
	if (window.LilyScore) window.LilyScore.setGenerating(false);
	['gen-btn', 'stop-btn'].forEach(function (idv) {
		const b = document.getElementById(idv);
		if (b) b.classList.remove('ls-generating');
	});
}
'''




CUSTOM_CSS = '''
/* Score List: truncate long file names to a single line with an ellipsis. */
.score-list label {
	max-width: 100%;
}
.score-list label > span {
	display: inline-block;
	max-width: 100%;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	vertical-align: middle;
}
/* on hover, reveal the full (otherwise ellipsised) file name */
.score-list label:hover > span {
	overflow: visible;
	white-space: normal;
	word-break: break-all;
}
/* Score List scrolls within the height its column is given (see the layout model
   at the bottom of this stylesheet). */
.score-list {
	overflow-y: auto;
}
/* Generate button turns yellow while a generation is running (the .ls-generating
   class is toggled by the generation-gate js). !important beats the primary variant. */
#gen-btn.ls-generating {
	background: #f5c518 !important;
	background-image: none !important;
	border-color: #d4a800 !important;
	color: #3a2f00 !important;
}
/* Stop button: grey by default (theme look), solid red only while generating
   (the .ls-generating class is toggled by the generation-gate js). */
#stop-btn.ls-generating {
	background: #e23b3b !important;
	background-image: none !important;
	border-color: #c42b2b !important;
	color: #fff !important;
}
#stop-btn.ls-generating:hover {
	background: #cf2e2e !important;
}

/* ---- Layout: viewport-locked two-column workspace ----------------------------
   Goal: Compose + Logs keep their natural height; the Score List | editor row fills
   the rest; a long score must NOT stretch the page (it scrolls inside the sheet
   panel instead). Gradio's deep wrapper nesting makes pure-CSS flex height
   propagation unreliable, so the panel heights are driven from JS in
   web/layout-fit.js, which sets --ls-fill-h (bottom row) and --ls-sheet-h (sheet
   panel) on :root. IMPORTANT: those are plain pixel values, NOT 100vh — when this
   app is embedded in an auto-height iframe (Hugging Face Spaces), any 100vh/viewport
   reference feeds back into the iframe's growing height and the page scroll height
   runs away forever. layout-fit.js detects the iframe and uses fixed heights there. */
#main-row {
	align-items: flex-start;    /* don't stretch columns to each other's height */
}
/* Right (Sheet music) column: the score preview scrolls inside a bounded height
   (set by layout-fit.js) instead of growing the row / page. */
#sheet-col .ls-score-root {
	height: var(--ls-sheet-h, 720px);
	min-height: 320px;
}
#sheet-col .ls-preview {
	overflow: auto;             /* the SVG scrolls here, not the page */
}

/* Left column stacks naturally: Compose, Logs, then the fill row. */
#compose-col {
	display: flex;
	flex-direction: column;
}
/* The bottom Score List | editor row gets a bounded height from layout-fit.js
   (--ls-fill-h); never a viewport unit (see the iframe note above). */
#compose-col > .lp-fill {
	height: var(--ls-fill-h, 460px);
	min-height: 360px;
}
#compose-col > .lp-fill > .column,
#compose-col > .lp-fill > .column > .gr-group,
#compose-col > .lp-fill > .column > .gr-group > .gr-group {
	height: 100%;
	min-height: 0;
	display: flex;
	flex-direction: column;
}
/* Score-list column: the "## Score List" header (a .prose block) stays natural at
   the top; the radio list scrolls in the remaining space. The header block sits in
   the inner group alongside the radio, so pin it 0-shrink and let the list fill. */
#compose-col > .lp-fill > .column:first-child .block:has(.prose) {
	flex: 0 0 auto;
}
#compose-col > .lp-fill > .column:first-child .block:has(.score-list) {
	flex: 1 1 0;
	min-height: 0;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}
#compose-col > .lp-fill > .column:first-child .score-list {
	flex: 1 1 auto;
	min-height: 0;
}
/* Logs textbox stays compact even on long output. */
#compose-col > .lp-fixed.gr-accordion textarea {
	max-height: 200px;
}
/* Editor column: the embedded CodeMirror mount fills the space under its header.
   DOM (Gradio): #editor-col > .gr-group > .gr-group > .styler > { headerBlock,
   editorBlock(.html-container > .gradio-style > #ls-editor-mount), hiddenStateBlock }.
   We make the chain down to .styler full-height flex columns, let the editor block
   fill (flex:1, basis 0 so a long score can't inflate it), and keep the header
   block natural. CM then scrolls inside the bounded mount. */
#editor-col,
#editor-col > .gr-group,
#editor-col > .gr-group > .gr-group,
#editor-col .styler {
	display: flex;
	flex-direction: column;
	height: 100%;
	min-height: 0;
}
/* the editor block (the one wrapping the gr.HTML mount) fills the styler height */
#editor-col .styler > .block:has(.html-container) {
	flex: 1 1 0;
	min-height: 0;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}
#editor-col .html-container,
#editor-col .html-container > .gradio-style {
	flex: 1 1 0;
	min-height: 0;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}
#editor-col #ls-editor-mount {
	flex: 1 1 0;
	height: auto;              /* override lyl-editor.css fixed 470px */
	min-height: 0;
}
'''


def build_ui ():
	examples = load_library()

	with gr.Blocks(title='LilyScript') as demo:
		gr.Markdown(T('app_title'))
		store = gr.State(examples)

		with gr.Row(elem_id='main-row'):
			# ---------------- LEFT ----------------
			with gr.Column(scale=5, elem_id='compose-col'):
				# (1) compose params, with (2) the collapsible run log stacked below
				with gr.Group(elem_classes=['lp-fixed']):
					gr.Markdown(T('compose'))
					with gr.Group():
						gr.Markdown(T('style_options'))
						with gr.Row():
							composer = gr.Dropdown(label=T('composer'), choices=COMPOSERS, value='',
								allow_custom_value=True)
							period = gr.Dropdown(label=T('period'), choices=PERIODS, value='',
								allow_custom_value=True)
							genre = gr.Dropdown(label=T('genre'), choices=GENRES, value='',
								allow_custom_value=True)
					prompt = gr.Textbox(label=T('metadata_prompt'), lines=3, value='',
						placeholder=T('metadata_placeholder'))
					gr.Markdown(T('length'))
					with gr.Row():
						measures = gr.Number(label=T('measures'), value=0, precision=0)
						max_patches = gr.Number(label=T('max_patches'), value=1024, precision=0)
					gr.Markdown(T('sampler'))
					with gr.Row():
						temperature = gr.Slider(0.0, 2.0, value=1.0, step=0.05, label=T('temperature'))
						seed = gr.Slider(0, 2147483647, value=42, step=1, label=T('seed'))
					with gr.Row():
						gen_btn = gr.Button(T('generate'), variant='primary', elem_id='gen-btn')
						stop_btn = gr.Button(T('stop'), variant='stop', elem_id='stop-btn')

				with gr.Accordion(T('logs'), open=True, elem_classes=['lp-fixed']):
					log = gr.Textbox(show_label=False, lines=10, max_lines=10,
						autoscroll=True, interactive=False, container=False)

				# bottom row: (3) file list | (4) editor — flex-fills the remaining height
				with gr.Row(equal_height=True, elem_classes=['lp-fill']):
					with gr.Column(scale=2, min_width=160):
						with gr.Group():
							gr.Markdown(T('score_list'))
							file_list = gr.Radio(show_label=False, choices=list(examples.keys()),
								value=None, interactive=True, container=False,
								elem_classes=['score-list'])
					with gr.Column(scale=5, elem_id='editor-col'):
						with gr.Group():
							gr.Markdown(T('lilylet_editor'))
							with gr.Row(elem_id='ls-editor-actions'):
								# Share button: copies the current deep-link URL (#score=<file>)
								# to the clipboard. js-only handler (_JS_SHARE) — see its comment
								# for the iframe URL/clipboard caveats. A transient hint span next
								# to it shows the copy result.
								share_btn = gr.Button(T('share_link'), elem_id='ls-share-btn',
									size='sm', scale=0, min_width=110)
								# Open the current editor text in lilylet-live-editor: builds a
								# ?code=<pako+base64> URL (matching the editor's share.ts) and
								# opens it in a new tab. Hidden via CSS until the editor has text
								# (toggled by _JS_RENDER, which receives the full text each change).
								live_btn = gr.Button(T('open_in_live_editor'), elem_id='ls-live-btn',
									size='sm', scale=0, min_width=150, elem_classes=['ls-hidden'])
							# Our own CodeMirror 6 editor (lyl-editor.bundle.js) mounts into
							# this div and bridges to the hidden textbox below — Gradio's
							# gr.Code can't be syntax-highlighted (its CM is sealed), so we
							# embed our own with the grammar-derived lilylet() highlighter.
							gr.HTML('<div id="ls-editor-mount" class="ls-editor-mount"></div>')
							# Canonical editor text as Gradio state: generation/file-load write
							# it, the SVG render reads it, and the embedded CM mirrors it both
							# ways (see web/lyl-editor-mount.js). Hidden via CSS (NOT visible=False,
							# which removes the element from the DOM so the bridge can't find its
							# <textarea>); the .ls-editor-state-hidden rule sets display:none.
							editor = gr.Textbox(elem_id='ls-editor-state',
								elem_classes=['ls-editor-state-hidden'], show_label=False, container=False)

			# ---------------- RIGHT ----------------
			with gr.Column(scale=6, elem_id='sheet-col'):
				with gr.Group():
					gr.Markdown(T('sheet_music'))
					gr.HTML(SHEET_PLACEHOLDER)

		# ---- wiring ----
		# mount the score player once the page (and LilyScore) is ready
		demo.load(None, None, None, js=_JS_HELPERS)
		# re-read the library from disk on every new session / refresh, so outputs
		# generated after server boot still appear in the Score List (store + Radio
		# are otherwise frozen at the boot-time snapshot — see refresh_library).
		demo.load(refresh_library, None, outputs=[store, file_list])

		# style dropdowns -> keep the metadata-prompt text box in sync
		for field in (composer, period, genre):
			field.change(sync_prompt, inputs=[composer, period, genre, prompt], outputs=[prompt])

		# Generate: a single click dep that runs the gate js (SVG-only, player
		# hidden) and then the streaming model fn — `js=` on a backend click runs
		# first and, returning nothing, leaves the declared `inputs` untouched. A
		# trailing `.then` js lifts the gate + reveals the player when it finishes.
		gen_event = gen_btn.click(
			run_generation,
			inputs=[prompt, measures, temperature, max_patches, seed, store],
			outputs=[log, editor, file_list, store, seed, gen_btn],
			js=_JS_GEN_START,
			# progress is shown on the Generate button's own label ("Generating… M/N"),
			# driven by run_generation. Hide Gradio's native progress overlay (it can't
			# render on a Button and otherwise covers the Logs/editor outputs).
			show_progress='hidden',
		)
		gen_event.then(None, None, None, js=_JS_GEN_END)

		# every editor change (streaming syncs + manual edits + file loads) -> re-render
		# SVG. Pass the editor value as input so the js receives the FULL text (gr.Code
		# virtualises long docs in the DOM, so scraping it client-side truncates).
		editor.change(None, inputs=[editor], outputs=None, js=_JS_RENDER)

		# Stop: cancel generation, reset the Generate button label (the cancelled
		# run never reaches its final yield, so it'd otherwise stay "Generating…"),
		# then lift the gate (js) so the player returns + button colors revert.
		stop_btn.click(
			lambda: gr.update(value=T('generate')), None, outputs=[gen_btn], cancels=[gen_event],
		).then(None, None, None, js=_JS_GEN_END)
		file_list.select(load_file, inputs=[file_list, store], outputs=[editor])
		# separate js-only listener: mirror the selected file into location.hash for deep-linking
		file_list.select(None, inputs=[file_list], outputs=None, js=_JS_SELECT_HASH)
		# Share: copy the current deep-link URL (the #score hash kept current by the
		# select listener above) to the clipboard. js-only — see _JS_SHARE.
		share_btn.click(None, inputs=None, outputs=None, js=_JS_SHARE)
		# Open in live-editor: encode the editor text into a ?code= URL and open it.
		live_btn.click(None, inputs=None, outputs=None, js=_JS_LIVE_EDITOR)

	return demo


if __name__ == '__main__':
	demo = build_ui()
	from starlette.middleware import Middleware
	demo.queue().launch(
		theme=gr.themes.Soft(),
		css=CUSTOM_CSS,
		head=build_head(),
		allowed_paths=[WEB_DIR],
		# Inject a long-lived Cache-Control on our large static web/ assets (see
		# AssetCacheHeaderMiddleware). app_kwargs flows into the FastAPI/Starlette constructor.
		app_kwargs={'middleware': [Middleware(AssetCacheHeaderMiddleware)]},
	)
