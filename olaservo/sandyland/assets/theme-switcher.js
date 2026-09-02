/* ===========================================================================
   theme-switcher.js  —  runtime theme toggle for the research hub
   ---------------------------------------------------------------------------
   Injects a small control (top-right) that swaps the retro themes defined in
   assets/themes.css by toggling a `theme-*` class on <body>.

   Persistence model (matches the design intent):
     - Uses sessionStorage, so a choice CARRIES OVER across pages within the
       same browsing session/tab (e.g. hub → a survey page keeps your pick).
     - It does NOT persist between visits: open a fresh session (new tab after
       close / browser restart) and the page reverts to its own default theme.

   Each page sets its own default via the class already on <body>
   (e.g. <body class="theme-hypercard">). If sessionStorage holds a choice, that
   wins on load.
   =========================================================================== */
(function () {
  "use strict";

  var THEMES = [
    { id: "hypercard",  label: "HyperCard"  },
    { id: "craigshouse", label: "Craigshouse" },
    { id: "serif",       label: "Serif"       }
  ];
  var KEY = "research-hub-theme";
  var IDS = THEMES.map(function (t) { return t.id; });

  function currentClassTheme() {
    for (var i = 0; i < IDS.length; i++) {
      if (document.body.classList.contains("theme-" + IDS[i])) return IDS[i];
    }
    return null;
  }

  function applyTheme(id) {
    IDS.forEach(function (t) { document.body.classList.remove("theme-" + t); });
    document.body.classList.add("theme-" + id);
    updateButtons(id);
  }

  function setTheme(id) {
    applyTheme(id);
    try { sessionStorage.setItem(KEY, id); } catch (e) { /* private mode: no-op */ }
  }

  var buttons = {};
  function updateButtons(active) {
    IDS.forEach(function (t) {
      if (buttons[t]) buttons[t].setAttribute("aria-checked", String(t === active));
    });
  }

  function buildControl(active) {
    var bar = document.createElement("div");
    bar.className = "theme-switcher";
    bar.setAttribute("role", "radiogroup");   /* single-choice picker */
    bar.setAttribute("aria-label", "Site theme");

    var label = document.createElement("span");
    label.className = "theme-switcher__label";
    label.textContent = "Theme";
    bar.appendChild(label);

    THEMES.forEach(function (t) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.textContent = t.label;
      btn.setAttribute("aria-checked", String(t.id === active));
      btn.addEventListener("click", function () { setTheme(t.id); });
      buttons[t.id] = btn;
      bar.appendChild(btn);
    });

    document.body.appendChild(bar);
  }

  function init() {
    var stored = null;
    try { stored = sessionStorage.getItem(KEY); } catch (e) { /* ignore */ }
    var initial = (stored && IDS.indexOf(stored) !== -1)
      ? stored
      : (currentClassTheme() || "hypercard");
    applyTheme(initial);
    buildControl(initial);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
