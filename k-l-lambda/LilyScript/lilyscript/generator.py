"""Standalone streaming Lilylet generator (int8 ONNX + two-level KV cache).

Torch-free adaptation of deep-starry's ORTGeneratorKV
(tests/bench_lilylet_int8_ort.py): the patch-level decoder runs incrementally
through `patch_kv_int8.onnx` (O(1) per step) and the token decoder inside each
patch through `token_kv_int8.onnx`, both via onnxruntime. The token embedding
table and model geometry are loaded from vendored assets (`wte.npy`,
`geometry.json`) instead of a torch model, and sampling is reimplemented in
numpy — so the only runtime deps are onnxruntime + numpy.

`generate_stream(...)` is a Python generator: it yields `(raw, pretty, done)`
after every patch, where `raw` is the accumulated decoded text (for the run
log) and `pretty = postprocess(raw)` (for the editor, segmented by measure).
"""

import os
import json
import logging

LOG = logging.getLogger('lilyscript')

import numpy as np
import onnxruntime as ort

from .postprocess import postprocess


class _StreamAborted (Exception):
	'''Raised by the token loop when a syntax monitor exhausts its redraw budget,
	signalling generate_stream to end the stream cleanly rather than commit a bad
	token (which would corrupt the monitor's running text). Internal to the
	blacklist-discovery path; never raised when monitor is None.'''
	pass


def sample_next (logits, rng, temperature=1.0, top_k=0, top_p=1.0, banned_ids=None):
	'''Sample one token id from a logits vector (numpy) with temperature/top-k/top-p.

	banned_ids: optional iterable of token ids to forbid; their logits are set to
	-inf before any other filtering, so they can never be drawn (used by the
	syntax-blacklist mask in tools/lilylet_blacklist_gen.py). Default None = no-op.
	'''
	logits = logits.astype(np.float64)
	if banned_ids:
		logits = logits.copy()
		logits[list(banned_ids)] = -np.inf
	if temperature != 1.0:
		logits = logits / max(temperature, 1e-6)
	if top_k and top_k > 0:
		k = min(top_k, logits.shape[-1])
		kth = np.sort(logits)[-k]
		logits = np.where(logits < kth, -np.inf, logits)
	if top_p and top_p < 1.0:
		order = np.argsort(logits)[::-1]
		sorted_logits = logits[order]
		probs = _softmax(sorted_logits)
		cdf = np.cumsum(probs)
		remove = cdf > top_p
		remove[1:] = remove[:-1].copy()
		remove[0] = False
		sorted_logits = np.where(remove, -np.inf, sorted_logits)
		logits = np.full_like(logits, -np.inf)
		logits[order] = sorted_logits
	probs = _softmax(logits)
	return int(rng.choice(len(probs), p=probs))


def _softmax (x):
	x = x - np.max(x)
	e = np.exp(x)
	return e / e.sum()


def _physical_cores ():
	'''Best-effort physical (not logical/HT) core count via /proc/cpuinfo; None if
	unavailable. ORT's intra_op default (=0) maps to this on most CPU builds.'''
	try:
		phys, cur = set(), {}
		for line in open('/proc/cpuinfo'):
			line = line.strip()
			if not line:
				if 'physical id' in cur and 'core id' in cur:
					phys.add((cur['physical id'], cur['core id']))
				cur = {}
				continue
			if ':' in line:
				k, v = line.split(':', 1)
				cur[k.strip()] = v.strip()
		return len(phys) or None
	except Exception:
		return None


def _log_thread_info (so, sess):
	'''Log host CPU capacity + the ONNX Runtime intra/inter-op thread settings that
	are actually in effect. intra_op_num_threads/inter_op_num_threads == 0 means
	"ORT auto" — it picks the number of physical cores for the intra-op pool.'''
	logical = os.cpu_count()
	affinity = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else logical
	physical = _physical_cores()
	intra = so.intra_op_num_threads
	inter = so.inter_op_num_threads
	effective_intra = intra if intra else (physical or affinity or logical)
	LOG.info('CPU: %s logical / %s physical cores, %s available (affinity)',
		logical, physical if physical is not None else '?', affinity)
	LOG.info('ONNX Runtime threads: intra_op=%s (%s), inter_op=%s (%s) | execution_mode=%s',
		intra, 'auto -> ~%s' % effective_intra if intra == 0 else 'explicit',
		inter, 'auto' if inter == 0 else 'explicit',
		getattr(so, 'execution_mode', '?'))


class StreamingLilyletGenerator:
	'''Loads the int8 KV ONNX sessions + vendored assets and streams generation.'''

	def __init__ (self, model_dir, asset_dir, threads=None):
		from .tokenizer import LilyletTokenizer

		geo = json.load(open(os.path.join(model_dir, 'geometry.json')))
		self.patch_size = geo['patch_size']
		self.pad_id = geo['pad_id']
		self.bos_id = geo['bos_id']
		self.eos_id = geo['eos_id']
		# patch-level KV geometry
		self.n_layers = geo['patch']['n_layers']
		self.n_kv = geo['patch']['n_kv_heads']
		self.head_dim = geo['patch']['head_dim']
		# token-level KV geometry
		self.t_layers = geo['token']['n_layers']
		self.t_kv = geo['token']['n_kv_heads']
		self.t_head_dim = geo['token']['head_dim']

		self.tokenizer = LilyletTokenizer(os.path.join(asset_dir, 'lilylet-tokenizer.json'))
		self.wte = np.load(os.path.join(model_dir, 'wte.npy'))		# [vocab, hidden] — model weight, lives with the onnx

		so = ort.SessionOptions()
		if threads:
			so.intra_op_num_threads = threads
		self.patch_kv_sess = ort.InferenceSession(
			os.path.join(model_dir, 'patch_kv_int8.onnx'), so, providers=['CPUExecutionProvider'])
		self.token_kv_sess = ort.InferenceSession(
			os.path.join(model_dir, 'token_kv_int8.onnx'), so, providers=['CPUExecutionProvider'])
		self.patch_out_names = [o.name for o in self.patch_kv_sess.get_outputs()]
		self.token_out_names = [o.name for o in self.token_kv_sess.get_outputs()]
		_log_thread_info(so, self.patch_kv_sess)

	# ---- text helpers (mirror LilyletPatchyGenerator.patch_to_text) ----

	def patch_to_text (self, patch):
		out = []
		for tid in patch:
			tid = int(tid)
			if tid == self.eos_id:
				break
			if tid in (self.pad_id, self.bos_id):
				continue
			out.append(self.tokenizer.text_by_id.get(tid, ''))
		return ''.join(out)

	def patches_to_text (self, patches):
		return ''.join(self.patch_to_text(p) for p in patches)

	def _encode_lines (self, lines):
		'''Encode text lines into padded patches (trailing newline per line, matching
		the patchifier). Returns a list of patch_size-long id lists.'''
		patches = []
		for line in lines:
			ids = self.tokenizer.encode(line + '\n')
			for i in range(0, len(ids), self.patch_size):
				chunk = ids[i:i + self.patch_size]
				patches.append(chunk + [self.pad_id] * (self.patch_size - len(chunk)))
		return patches

	def _seed_patches (self, prompt_text):
		'''Build the seed patch list, mirroring the training patchifier's layout:

			%-prompt patches  ->  <bos> patch  ->  [header] patches

		Lines starting with `%` are the unsupervised style PROMPT (go BEFORE <bos>); the
		rest (`[field "..."]` headers) are the supervised HEADER (go AFTER <bos>). With no
		`%` lines this reduces to `[<bos>] + header` (the legacy <bos>-at-index-0 layout).
		'''
		prompt_lines, header_lines = [], []
		for line in prompt_text.splitlines():
			(prompt_lines if line.lstrip().startswith('%') else header_lines).append(line)

		bos_patch = [self.bos_id] * (self.patch_size - 1) + [self.eos_id]
		return self._encode_lines(prompt_lines) + [bos_patch] + self._encode_lines(header_lines)

	# ---- KV plumbing ----

	def _empty_patch_past (self):
		return [np.zeros((1, self.n_kv, 0, self.head_dim), dtype=np.float32) for _ in range(2 * self.n_layers)]

	def _empty_token_past (self):
		return [np.zeros((1, self.t_kv, 0, self.t_head_dim), dtype=np.float32) for _ in range(2 * self.t_layers)]

	def _patch_kv_step (self, patch_rows, past):
		'''Feed L new patches (list of patch_size-length id rows) + past KV.
		Returns (last_hidden [hidden], new_past list).'''
		feed = {'patches': np.asarray([patch_rows], dtype=np.int64)}
		for i in range(self.n_layers):
			feed[f'past_k_{i}'] = past[2 * i]
			feed[f'past_v_{i}'] = past[2 * i + 1]
		out = dict(zip(self.patch_out_names, self.patch_kv_sess.run(None, feed)))
		new_past = []
		for i in range(self.n_layers):
			new_past.append(out[f'new_k_{i}'])
			new_past.append(out[f'new_v_{i}'])
		return out['hidden'][0, -1], new_past

	def _token_kv_step (self, emb_np, past):
		'''Feed L new token embeddings [1,L,hidden] + past KV. Returns (logits[-1], new_past).'''
		feed = {'inputs_embeds': emb_np.astype(np.float32)}
		for i in range(self.t_layers):
			feed[f'past_k_{i}'] = past[2 * i]
			feed[f'past_v_{i}'] = past[2 * i + 1]
		out = dict(zip(self.token_out_names, self.token_kv_sess.run(None, feed)))
		new_past = []
		for i in range(self.t_layers):
			new_past.append(out[f'new_k_{i}'])
			new_past.append(out[f'new_v_{i}'])
		return out['logits'][0, -1], new_past

	def _generate_patch (self, last_hidden, rng, prefix_ids=None, temperature=1.0, top_k=0, top_p=1.0,
		monitor=None, max_redraws=16):
		'''Token-level decode for one patch through the token-KV session: feed the
		patch state, then bos+prefix embeddings, then sample until the patch is full.

		monitor: optional syntax-blacklist hook (default None -> unchanged behavior).
		  - monitor.banned() -> iterable of token ids to mask for the next draw,
		  - monitor.accept(id) -> bool: True to commit the drawn token, False to
		    redraw (the monitor records the violation + grows its ban set internally),
		  - monitor.commit_forced(id): notified of each forced (non-sampled) token so
		    its running context/stream stay correct.
		Forced tokens (bos + prefix_ids) bypass accept()/redraw — only commit_forced.
		'''
		generated = list(prefix_ids or [])
		tokens = [self.bos_id] + list(prefix_ids or [])
		if monitor is not None:
			for tid in prefix_ids or []:
				monitor.commit_forced(tid)
		past = self._empty_token_past()
		enc = last_hidden.reshape(1, 1, -1).astype(np.float32)
		logits, past = self._token_kv_step(enc, past)
		for i in range(1, len(tokens)):
			emb = self.wte[tokens[i]].reshape(1, 1, -1)
			logits, past = self._token_kv_step(emb, past)
		while len(generated) < self.patch_size:
			if monitor is None:
				nxt = sample_next(logits, rng, temperature=temperature, top_k=top_k, top_p=top_p)
			else:
				# draw with the current ban mask; on a rejected (illegal) token the
				# monitor records it and we redraw from the SAME logits with the now-
				# larger mask. The token KV cache is only advanced for the committed
				# token below, so redrawing here costs nothing.
				for _ in range(max_redraws):
					nxt = sample_next(logits, rng, temperature=temperature, top_k=top_k, top_p=top_p,
						banned_ids=monitor.banned())
					if monitor.accept(nxt):
						break
				else:
					# every redraw was rejected. Committing a bad token would corrupt
					# the monitor's running text (every subsequent token would then
					# parse-fail and be mis-recorded), so abort the stream cleanly
					# instead — the caller (generate_stream) ends generation here.
					raise _StreamAborted()
			generated.append(nxt)
			if len(generated) < self.patch_size:
				emb = self.wte[nxt].reshape(1, 1, -1)
				logits, past = self._token_kv_step(emb, past)
		return generated

	def generate_stream (self, prompt_text='', max_patches=256, temperature=1.0, top_k=0,
		top_p=0.9, measures=None, seed=0, monitor=None):
		'''Autoregressive generation, yielding after every patch.

		Yields (raw, pretty, done):
		  raw    -- accumulated decoded patch text (with `[r:x/y]` markers), for the log
		  pretty -- postprocess(raw), measure-segmented, for the editor
		  done   -- True on the final yield (EOS patch or max_patches reached)

		monitor: optional syntax-blacklist hook threaded into the token decode loop
		  (default None -> behavior identical to before). When a monitor is given the
		  `[r:0/<measures>]` priming re-sample is disabled: priming is a probe-then-
		  discard draw that would corrupt the monitor's running stream, and the
		  blacklist harness wants free generation anyway.
		'''
		rng = np.random.default_rng(seed)

		patches = self._seed_patches(prompt_text)

		out_text = self.patches_to_text(patches)
		# 0-based marker: `y` counts measures remaining AFTER this one (patchifier:
		# y = total - i - 1), so `[r:0/{measures-1}]` yields exactly `measures` total.
		prime_ids = self.tokenizer.encode(f'[r:0/{measures - 1}]') if measures is not None and measures >= 1 else None
		primed = False

		# seed the monitor's running context/stream from the seed patches (commit_forced
		# skips bos/pad/eos, so passing the whole list incl. the <bos> patch is safe).
		if monitor is not None and len(patches) > 0:
			for p in patches:
				for tid in p:
					monitor.commit_forced(tid)

		# prefill: run all seed patches through the patch-KV decoder in one call
		past = self._empty_patch_past()
		last, past = self._patch_kv_step(patches, past)

		yield out_text, postprocess(out_text), False

		for _ in range(max_patches):
			# If a monitor supports priming-rewind (mark/rollback), snapshot before the
			# draw so a discarded probe patch can be undone (see priming below).
			can_prime_with_monitor = monitor is not None and hasattr(monitor, 'mark')
			if can_prime_with_monitor:
				monitor.mark()
			try:
				patch_ids = self._generate_patch(last, rng, temperature=temperature, top_k=top_k, top_p=top_p,
					monitor=monitor)
			except _StreamAborted:
				break

			# first time the model emits a stream patch, re-sample with the forced
			# `[r:0/<measures>]` prefix so the body starts at the requested measure count.
			# With a priming-capable monitor we rewind its running text first, so the
			# discarded probe patch doesn't pollute the 2-gram context. (The discovery
			# harness's monitor lacks mark/rollback, so priming stays disabled there.)
			if prime_ids is not None and not primed and self.patch_to_text(patch_ids).startswith('[r:') \
					and (monitor is None or can_prime_with_monitor):
				primed = True
				if can_prime_with_monitor:
					monitor.rollback()
				patch_ids = self._generate_patch(last, rng, prefix_ids=prime_ids,
					temperature=temperature, top_k=top_k, top_p=top_p, monitor=monitor)

			# EOS patch -> done
			if patch_ids[0] == self.bos_id and patch_ids[1] == self.eos_id:
				break

			out_text += self.patch_to_text(patch_ids)

			# mask tokens after the first EOS inside the patch to PAD before caching
			clean = list(patch_ids)
			seen_eos = False
			for j in range(len(clean)):
				if seen_eos:
					clean[j] = self.pad_id
				if clean[j] == self.eos_id:
					seen_eos = True

			# advance the patch-level cache by the one new patch -> next hidden state
			last, past = self._patch_kv_step([clean], past)

			yield out_text, postprocess(out_text), False

		yield out_text, postprocess(out_text), True
