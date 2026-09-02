/* <oham-stream> — OHAM (OrthoHolonic Accessible Memory) as ONE TAG.
 *
 *   <script src="oham-element.js"></script>
 *   <oham-stream></oham-stream>                          the frozen flagship demo
 *   <oham-stream clip="https://…/my.tsb"></oham-stream>  your own sealed clip
 *
 * The element deliberately does NOT reimplement the player. It parameterizes
 * the PROVEN, FROZEN receiver page (the same bytes the owner's pinned
 * on-device run verified at 60 fps; each device shows its own measured
 * rate in the status bar) through its existing query surface (?src ?mirror ?level
 * ?bank …) inside an iframe. One implementation, already gated, already
 * deployed; the element is pure embedding — it cannot drift from the demo
 * because it IS the demo. A standalone (in-element pipeline) mode ships with
 * the npm package once the packaged worker+wasm path is gated.
 *
 * Attributes (all optional, all live — change them and the frame reloads):
 *   clip     absolute URL of a .tsb (v1 or v2 z-wire)     [default: page's own]
 *   mirrors  extra origins, |-separated, striped across   [default: page's own]
 *   level    resolution rung (0 = native, each +1 halves) [default: auto]
 *   bank     content-tick bank budget in MB (locked mode)
 *   mode     "stream" (paces to your wire, edge.html) ·
 *            "locked" (fill once then locked 60, edge-next.html) ·
 *            "probe"  (measure your wire to the sources, wire-probe.html)
 *   page     override the receiver page URL entirely (self-hosted copies)
 *   credit   "off" hides the one-line attribution
 *
 * Paul Phillips — solo developer · OHAM / OrthoHolonic Accessible Memory
 * involvedinvolutions.com · License: Apache-2.0 + Commons Clause
 */
(() => {
  "use strict";
  const HOME = "https://storage.googleapis.com/framecore-etch-video/";
  const PAGES = { stream: "edge.html", locked: "edge-next.html", probe: "wire-probe.html" };

  class OhamStream extends HTMLElement {
    static get observedAttributes() {
      return ["clip", "mirrors", "level", "bank", "mode", "page", "credit"];
    }
    constructor() {
      super();
      const root = this.attachShadow({ mode: "open" });
      root.innerHTML = `
        <style>
          :host { display: block; }
          .box { position: relative; width: 100%; aspect-ratio: 16/9;
                 background: #000; }
          iframe { width: 100%; height: 100%; border: 0; display: block; }
          .fallback { position: absolute; inset: 0; display: none;
                      align-items: center; justify-content: center;
                      color: #9ab; font: 14px system-ui, sans-serif; }
          .fallback a { color: #7cf; }
          .credit { font: 11px/1.6 system-ui, sans-serif; color: #667;
                    text-align: right; }
          .credit a { color: inherit; text-decoration: none; }
        </style>
        <div class="box">
          <iframe allowfullscreen loading="lazy" title="OHAM stream"></iframe>
          <div class="fallback"><span></span></div>
        </div>
        <div class="credit">OHAM — OrthoHolonic Accessible Memory ·
          <a rel="author">Paul Phillips</a></div>`;
      this._iframe = root.querySelector("iframe");
      this._fallback = root.querySelector(".fallback");
      this._credit = root.querySelector(".credit");
      this._creditLink = root.querySelector(".credit a");
    }
    connectedCallback() { this._render(); }
    attributeChangedCallback() { if (this.isConnected) this._render(); }

    /** The URL the element resolves to — exposed for tests and curiosity. */
    get resolvedSrc() { return this._src || ""; }

    _render() {
      const mode = (this.getAttribute("mode") || "stream").toLowerCase();
      const page = this.getAttribute("page")
                || HOME + (PAGES[mode] || PAGES.stream);
      const q = new URLSearchParams();
      const clip = this.getAttribute("clip");
      const mirrors = this.getAttribute("mirrors");
      const level = this.getAttribute("level");
      const bank = this.getAttribute("bank");
      if (clip) q.set("src", clip);
      if (mirrors) q.set("mirror", mirrors);
      // a non-numeric level is a typo, not a request for native decode —
      // same guard the lab register's A6 put in the page itself
      if (level !== null && level !== "" && Number.isFinite(+level)) q.set("level", level);
      if (bank !== null && bank !== "" && Number.isFinite(+bank)) q.set("bank", bank);
      const src = q.toString() ? `${page}?${q}` : page;
      if (src === this._src) return;
      this._src = src;

      // fallback: if the frame produces no load event, show a direct link —
      // links always work (the site-handoff rule, kept here too)
      clearTimeout(this._tmr);
      this._fallback.style.display = "none";
      this._fallback.querySelector("span").innerHTML =
        `embed blocked — <a href="${src}" target="_blank" rel="noopener">open the stream directly</a>`;
      this._tmr = setTimeout(() => { this._fallback.style.display = "flex"; }, 12000);
      this._iframe.addEventListener("load",
        () => clearTimeout(this._tmr), { once: true });
      this._iframe.src = src;

      this._credit.style.display =
        this.getAttribute("credit") === "off" ? "none" : "block";
      this._creditLink.href = "https://involvedinvolutions.com";
    }
  }
  if (!customElements.get("oham-stream")) {
    customElements.define("oham-stream", OhamStream);
  }
})();
