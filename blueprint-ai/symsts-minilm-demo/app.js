/* SymSTS-MiniLM in-browser inference: onnxruntime-web (fp16) + local WordPiece tokenizer */
(function () {
  var DIM = 384;
  var MODEL_VER = '1.19.2';
  var session = null, vocab = null, readyFlag = false;

  function el(id) { return document.getElementById(id); }
  function colorFor(pct) {
    if (pct >= 80) return '#0f766e'; // green
    if (pct >= 60) return '#b45309'; // amber
    if (pct >= 40) return '#a16207'; // olive
    return '#b91c1c';                // red
  }
  function wordFor(pct) {
    if (pct >= 80) return 'very similar';
    if (pct >= 60) return 'similar meaning';
    return pct >= 40 ? 'partially related' : 'not similar';
  }

  function setReady(ok, msg) {
    var pill = el('pill');
    pill.className = 'pill' + (ok ? ' ok' : '');
    pill.innerHTML = ok ? '<b>Ready</b> · ' + msg : '<b>Error</b> · ' + msg;
  }

  function buildVocab(text) {
    var lines = text.split('\n');
    var v = {};
    for (var i = 0; i < lines.length; i++) { var t = lines[i].replace(/\r$/, ''); v[t] = i; }
    v['[CLS]'] = 101; v['[SEP]'] = 102; v['[UNK]'] = 100; v['[PAD]'] = 0; v['[MASK]'] = 103;
    return v;
  }

  async function init() {
    try {
      var vr = await fetch('./vocab.txt');
      vocab = buildVocab(await vr.text());
      window.ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@' + MODEL_VER + '/dist/';
      window.ort.env.wasm.numThreads = Math.min(4, navigator.hardwareConcurrency || 2);
      var mr = await fetch('./model.onnx');
      session = await window.ort.InferenceSession.create(new Uint8Array(await mr.arrayBuffer()), { executionProviders: ['wasm'] });
      readyFlag = true;
      setReady(true, 'loaded, runs on your CPU');
      el('go').disabled = false; el('bgobtn').disabled = false;
    } catch (err) {
      setReady(false, 'could not load model: ' + (err && err.message ? err.message : err));
    }
  }

  async function embed(text) {
    var t = MyBERT.tokenize(text || '', vocab, 512);
    var ids = t.input_ids, mask = t.attention_mask, seq = ids.length;
    var I = new BigInt64Array(seq), M = new BigInt64Array(seq), T = new BigInt64Array(seq);
    for (var i = 0; i < seq; i++) { I[i] = BigInt(ids[i]); M[i] = BigInt(mask[i]); T[i] = 0n; }
    var out = await session.run({
      input_ids: new window.ort.Tensor('int64', I, [1, seq]),
      attention_mask: new window.ort.Tensor('int64', M, [1, seq]),
      token_type_ids: new window.ort.Tensor('int64', T, [1, seq])
    });
    var h = out.last_hidden_state.data, sum = new Float32Array(DIM), count = 0, s, d;
    for (s = 0; s < seq; s++) { if (mask[s] === 0) continue; count++;
      for (d = 0; d < DIM; d++) sum[d] += h[s * DIM + d]; }
    var norm = 0;
    for (d = 0; d < DIM; d++) { sum[d] = count > 0 ? sum[d] / count : 0; norm += sum[d] * sum[d]; }
    norm = Math.sqrt(norm) || 1;
    for (d = 0; d < DIM; d++) sum[d] /= norm;
    return sum;
  }

  function cosine(a, b) { var dot = 0; for (var i = 0; i < DIM; i++) dot += a[i] * b[i]; return dot; }

  function animateTo(targetPct, color, note) {
    var out = el('result'); out.style.display = 'block';
    el('resnote').textContent = note;
    el('fill').style.background = color;
    // reset then animate width + count-up
    el('fill').style.transition = 'none'; el('fill').style.width = '0%';
    var numEl = el('num'); numEl.textContent = '0%'; numEl.style.color = color;
    requestAnimationFrame(function () {
      el('fill').style.transition = 'width 1s cubic-bezier(.22,1,.36,1)';
      el('fill').style.width = targetPct + '%';
    });
    var start = null, from = 0;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / 700, 1);
      p = 1 - Math.pow(1 - p, 3); // ease-out
      numEl.textContent = Math.round(from + (targetPct - from) * p) + '%';
      if (p < 1) requestAnimationFrame(step); else numEl.textContent = targetPct + '%';
    }
    requestAnimationFrame(step);
  }

  async function doCompare() {
    var a = el('a').value, b = el('b').value;
    if (!readyFlag || !a.trim() || !b.trim()) return;
    var btn = el('go'); btn.disabled = true; btn.textContent = '…';
    try {
      var t0 = performance.now();
      var ea = await embed(a), eb = await embed(b);
      var cos = cosine(ea, eb), pct = Math.round(cos * 10000) / 100;
      var ms = Math.round(performance.now() - t0);
      el('pairA').innerHTML = escapeHtml(a);
      el('pairB').innerHTML = escapeHtml(b) + ' <i>— ' + wordFor(pct) + '</i>';
      animateTo(pct, colorFor(pct), 'similarity ' + cos.toFixed(4) + ' · computed in ' + ms + ' ms on your device');
    } finally { btn.disabled = false; btn.textContent = 'Compute'; }
  }

  async function doBatch() {
    var ref = el('bref').value, list = el('blist').value;
    if (!readyFlag || !ref.trim() || !list.trim()) return;
    var btn = el('bgobtn'); btn.disabled = true;
    try {
      var ea = await embed(ref);
      var lines = list.split('\n').map(function (x) { return x.trim(); }).filter(Boolean);
      var out = '', max = Math.min(lines.length, 100), best = null, worst = null;
      for (var i = 0; i < max; i++) {
        var cos = cosine(ea, await embed(lines[i])), pct = Math.round(cos * 10000) / 100;
        if (best === null || pct > best[0]) best = [pct, lines[i]];
        if (worst === null || pct < worst[0]) worst = [pct, lines[i]];
        out += '<div class="row"><span>' + escapeHtml(lines[i]) + '</span><span class="sc">' + pct + '%</span></div>';
      }
      if (!best || !worst) out = '<div class="row"><span>No sentences given.</span></div>';
      else out += '<div class="row"><span>&nbsp;</span><span class="sc" style="color:#4f46e5">best ' + best[0] + '% · worst ' + worst[0] + '%</span></div>';
      el('batchOut').innerHTML = out;
    } finally { btn.disabled = false; }
  }

  function escapeHtml(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var EXAMPLES = [
    ['Two people are playing cricket.', 'A couple of persons are playing a game of cricket.'],
    ['The cat is sitting on the mat.', 'A dog is running in the park.'],
    ['Artificial intelligence is transforming the world.', 'I went to the store to buy some milk.']
  ];
  function useExample(i) { el('a').value = EXAMPLES[i][0]; el('b').value = EXAMPLES[i][1]; el('result').style.display = 'none'; }

  function wire() {
    el('go').addEventListener('click', doCompare);
    el('bgobtn').addEventListener('click', doBatch);
    el('toggleBatch').addEventListener('click', function () {
      var open = el('batchPanel').style.display === 'block';
      el('batchPanel').style.display = open ? 'none' : 'block';
      el('toggleBatch').textContent = (open ? 'Compare one sentence against a list ▸' : 'Hide list compare ▾');
    });
    el('a').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doCompare(); } });
    el('b').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doCompare(); } });
    el('ex1').addEventListener('click', function () { useExample(0); });
    el('ex2').addEventListener('click', function () { useExample(1); });
    el('ex3').addEventListener('click', function () { useExample(2); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { wire(); init(); });
  else { wire(); init(); }
})();
