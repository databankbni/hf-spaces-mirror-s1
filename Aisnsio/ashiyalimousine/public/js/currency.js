/* Ashiya Limousine — lightweight multi-currency DISPLAY helper.
 * Prices are always charged in JPY; this only shows an approximate
 * inbound (KIX) conversion next to yen amounts. Never mutates money logic.
 * Owns: the currency chip + appended ".als-fx" conversion spans only.
 * Robust by design: guarded, self-contained, never throws. */
(function () {
  "use strict";
  if (window.__alsFx) return;          // guard double-init
  window.__alsFx = true;

  try {
    // ---- static FX (approx, hard-coded) : units of currency per 1 JPY ----
    var FX = {
      JPY: { rate: 1,      sym: "¥", dp: 0 },
      USD: { rate: 0.0067, sym: "$",      dp: 0 },
      HKD: { rate: 0.052,  sym: "HK$",    dp: 0 },
      SGD: { rate: 0.0091, sym: "S$",     dp: 0 },
      TWD: { rate: 0.21,   sym: "NT$",    dp: 0 },
      CNY: { rate: 0.048,  sym: "CN¥", dp: 0 }
    };
    var ORDER = ["JPY", "USD", "HKD", "SGD", "TWD", "CNY"];
    var LS_KEY = "als-currency";
    var FX_CLS = "als-fx";
    var PRICE_RE = /¥\s?(\d[\d,]*)/g;   // "¥44,000"

    var Core = window.ALSCore || null;
    function tt(k, fb) {
      try { if (Core && typeof Core.tt === "function") { var v = Core.tt(k); if (v && v !== k) return v; } }
      catch (_) {}
      return fb;
    }

    // ---- current selection ----
    var cur = "JPY";
    try { var saved = localStorage.getItem(LS_KEY); if (saved && FX[saved]) cur = saved; } catch (_) {}

    // ---- injected style ----
    function injectStyle() {
      if (document.getElementById("als-fx-style")) return;
      var s = document.createElement("style");
      s.id = "als-fx-style";
      s.textContent =
        "." + FX_CLS + "{color:var(--faint,#6A7188);font-size:.82em;font-weight:400;" +
        "letter-spacing:.01em;white-space:nowrap}" +
        ".als-cur{display:inline-flex;align-items:center;margin-left:8px}" +
        ".als-cur select{background:transparent;border:1px solid var(--line,rgba(154,160,181,.28));" +
        "color:var(--faint,#6A7188);font:inherit;font-size:11px;font-weight:700;letter-spacing:.06em;" +
        "border-radius:999px;padding:5px 22px 5px 10px;cursor:pointer;-webkit-appearance:none;" +
        "appearance:none;background-image:url(\"data:image/svg+xml;utf8," +
        "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8' viewBox='0 0 8 8'>" +
        "<path d='M0 2l4 4 4-4' fill='none' stroke='%236A7188' stroke-width='1.4'/></svg>\");" +
        "background-repeat:no-repeat;background-position:right 8px center}" +
        ".als-cur.als-cur-fixed{position:fixed;left:14px;bottom:14px;z-index:60}";
      (document.head || document.documentElement).appendChild(s);
    }

    // ---- convert one yen integer to a display string for the active currency ----
    function convert(yenInt) {
      var c = FX[cur];
      var v = yenInt * c.rate;
      var out = c.dp > 0 ? v.toFixed(c.dp) : String(Math.round(v));
      // group thousands
      var parts = out.split(".");
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      return c.sym + parts.join(".");
    }

    // ---- roots to scan ----
    function roots() {
      var out = [];
      ["#booking", "#plans", "#packages"].forEach(function (sel) {
        var el = document.querySelector(sel);
        if (el) out.push(el);
      });
      document.querySelectorAll(".mdetail, .receipt").forEach(function (el) { out.push(el); });
      return out;
    }

    // ---- remove all appended conversions ----
    function clearFx(scope) {
      var ctx = scope || document;
      var nodes = ctx.querySelectorAll ? ctx.querySelectorAll("." + FX_CLS) : [];
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n.parentNode) n.parentNode.removeChild(n);
      }
    }

    // ---- append conversions under a root ----
    function applyRoot(root) {
      if (!root || !root.ownerDocument) return;
      var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: function (node) {
          if (!node.nodeValue || node.nodeValue.indexOf("¥") === -1) return NodeFilter.FILTER_REJECT;
          var p = node.parentNode;
          if (!p || p.classList && p.classList.contains(FX_CLS)) return NodeFilter.FILTER_REJECT;
          var tag = p.nodeName;
          if (tag === "SCRIPT" || tag === "STYLE" || tag === "OPTION" || tag === "SELECT") return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      });
      var hits = [], n;
      while ((n = walker.nextNode())) hits.push(n);

      hits.forEach(function (node) {
        // don't double-append: skip if an .als-fx already follows this text node
        var sib = node.nextSibling;
        if (sib && sib.nodeType === 1 && sib.classList && sib.classList.contains(FX_CLS)) return;

        PRICE_RE.lastIndex = 0;
        var amounts = [], m;
        while ((m = PRICE_RE.exec(node.nodeValue))) {
          var yenInt = parseInt(m[1].replace(/,/g, ""), 10);
          if (yenInt > 0) amounts.push(yenInt);
        }
        if (!amounts.length) return;

        var conv = amounts.map(convert).join(" + ");
        var span = document.createElement("span");
        span.className = FX_CLS;
        span.textContent = " (≈ " + conv + ")";
        if (node.parentNode) node.parentNode.insertBefore(span, node.nextSibling);
      });
    }

    // ---- full re-apply ----
    var observer = null;
    function apply() {
      var rs = roots();
      clearFx(document);
      if (cur === "JPY") return;
      // pause observer while we mutate to avoid feedback loops
      if (observer) observer.disconnect();
      try { rs.forEach(applyRoot); }
      finally { observeStart(rs); }
    }

    // ---- debounced observer ----
    var deb = null;
    function schedule() {
      if (deb) clearTimeout(deb);
      deb = setTimeout(function () { deb = null; apply(); }, 180);
    }
    function observeStart(rs) {
      if (cur === "JPY") { if (observer) observer.disconnect(); return; }
      if (!observer) {
        observer = new MutationObserver(function (muts) {
          for (var i = 0; i < muts.length; i++) {
            var mu = muts[i];
            // ignore mutations that are only our own inserted spans
            var self = true, j;
            for (j = 0; j < mu.addedNodes.length; j++) {
              var a = mu.addedNodes[j];
              if (!(a.nodeType === 1 && a.classList && a.classList.contains(FX_CLS))) { self = false; break; }
            }
            for (j = 0; j < mu.removedNodes.length; j++) {
              var r = mu.removedNodes[j];
              if (!(r.nodeType === 1 && r.classList && r.classList.contains(FX_CLS))) { self = false; break; }
            }
            if (mu.type === "characterData") self = false;
            if (!self) { schedule(); return; }
          }
        });
      } else {
        observer.disconnect();
      }
      (rs || roots()).forEach(function (root) {
        try { observer.observe(root, { childList: true, subtree: true, characterData: true }); } catch (_) {}
      });
    }

    // ---- build the selector chip ----
    function buildSelector() {
      if (document.querySelector(".als-cur")) return;
      var wrap = document.createElement("div");
      wrap.className = "als-cur";
      var sel = document.createElement("select");
      sel.setAttribute("aria-label", tt("cur_l", "Currency"));
      sel.title = tt("cur_l", "Currency");
      ORDER.forEach(function (code) {
        var o = document.createElement("option");
        o.value = code;
        o.textContent = code;
        if (code === cur) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () {
        cur = FX[sel.value] ? sel.value : "JPY";
        try { localStorage.setItem(LS_KEY, cur); } catch (_) {}
        apply();
      });
      wrap.appendChild(sel);

      var host = document.getElementById("langTg");
      if (host) {
        host.appendChild(wrap);
      } else {
        wrap.classList.add("als-cur-fixed");
        (document.body || document.documentElement).appendChild(wrap);
      }
    }

    function init() {
      injectStyle();
      buildSelector();
      apply();
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { try { init(); } catch (_) {} });
    } else {
      init();
    }
  } catch (_) { /* never throw */ }
})();
