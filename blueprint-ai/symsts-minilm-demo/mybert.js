/* Minimal BERT (uncased, WordPiece) tokenizer + mean-pooling helpers.
   Mirrors transformers.BertTokenizer for normal text. Works in browser & node. */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.MyBERT = factory();
})(typeof self !== 'undefined' ? self : globalThis, function () {
  var CLS = 101, SEP = 102, UNK = 100, PAD = 0, MASK = 103;
  var MAX = 512;

  function normalize(s) {
    // clean_text equivalent
    s = s.replace(/\n/g, ' ').replace(/\t/g, ' ').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, ' ');
    s = s.replace(/\s+/g, ' ').trim();
    // strip accents (NFD) + lowercase
    s = s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    s = s.toLowerCase();
    return s;
  }

  function isChinese(cp) {
    return (cp >= 0x3400 && cp <= 0x4DBF) || (cp >= 0x4E00 && cp <= 0x9FFF) ||
           (cp >= 0xF900 && cp <= 0xFAFF) || (cp >= 0x3040 && cp <= 0x30FF) ||
           (cp >= 0xFF00 && cp <= 0xFFEF);
  }
  function isPunct(cp) {
    if ((cp >= 33 && cp <= 47) || (cp >= 58 && cp <= 64) ||
        (cp >= 91 && cp <= 96) || (cp >= 123 && cp <= 126)) return true;
    if (cp >= 0x2000 && cp <= 0x206F) return true;
    return false;
  }

  function wordpiece(token, vocab) {
    var chars = token.split('');
    var start = 0, out = [];
    while (start < chars.length) {
      var end = chars.length;
      var cur = null;
      while (start < end) {
        var sub = token.slice(start, end);
        var key = (start > 0) ? ('##' + sub) : sub;
        if (vocab.hasOwnProperty(key)) { cur = key; break; }
        end -= 1;
      }
      if (cur === null) return [UNK];
      out.push(vocab[cur]);
      start = end;
    }
    return out;
  }

  // BERT basic tokenization (whitespace + punctuation, keep chinese)
  function basicTokenize(text) {
    // add spaces around chinese chars
    text = text.replace(/[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uFF00-\uFFEF]/g,
                        function (c) { return ' ' + c + ' '; }).trim();
    var words = text.split(/\s+/);
    var toks = [];
    for (var i = 0; i < words.length; i++) {
      if (!words[i]) continue;
      var cur = '';
      var pieces = [];
      for (var j = 0; j < words[i].length; j++) {
        var ch = words[i][j];
        if (isPunct(ch.codePointAt(0))) {
          if (cur) { pieces.push(cur); cur = ''; }
          pieces.push(ch);
        } else {
          cur += ch;
        }
      }
      if (cur) pieces.push(cur);
      for (var k = 0; k < pieces.length; k++) if (pieces[k]) toks.push(pieces[k]);
    }
    return toks;
  }

  // Returns { input_ids, attention_mask } (BigInt64 not needed; plain Int32)
  function tokenize(text, vocab, maxLength) {
    maxLength = maxLength || MAX;
    var norm = normalize(text);
    var basic = basicTokenize(norm);
    var ids = [CLS];
    var attm = [1];
    for (var i = 0; i < basic.length && ids.length < maxLength - 1; i++) {
      var sub = wordpiece(basic[i], vocab);
      for (var j = 0; j < sub.length && ids.length < maxLength - 1; j++) {
        ids.push(sub[j]); attm.push(1);
      }
    }
    ids.push(SEP); attm.push(1);
    return { input_ids: ids, attention_mask: attm };
  }

  // mean-pool last_hidden [seq,384] over mask, normalize -> [384]
  function embed(lastHidden, attentionMask) {
    var n = lastHidden.length, dim = lastHidden[0].length;
    var sum = new Array(dim).fill(0);
    var count = 0;
    for (var s = 0; s < n; s++) {
      if (attentionMask[s] === 0) continue;
      count += 1;
      for (var d = 0; d < dim; d++) sum[d] += lastHidden[s][d];
    }
    var norm = 0;
    for (var d2 = 0; d2 < dim; d2++) {
      sum[d2] = count > 0 ? sum[d2] / count : 0;
      norm += sum[d2] * sum[d2];
    }
    norm = Math.sqrt(norm) || 1;
    sum = sum.map(function (x) { return x / norm; });
    return sum;
  }

  function cosine(a, b) {
    var dot = 0;
    for (var i = 0; i < a.length; i++) dot += a[i] * b[i];
    return dot; // both normalized
  }

  return { normalize: normalize, basicTokenize: basicTokenize, wordpiece: wordpiece,
           tokenize: tokenize, embed: embed, cosine: cosine,
           ids: { CLS: CLS, SEP: SEP, UNK: UNK, PAD: PAD, MASK: MASK, MAX: MAX } };
});
