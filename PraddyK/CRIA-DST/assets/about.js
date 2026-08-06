/* CRIA — "About this analysis" orientation panel + "Next →" workflow cue.
   Fully client-side: injected into every analysis page after Dash renders it, so no
   server/route code is required. Content below is the same truthful per-analysis
   summary used elsewhere (what it shows · how to read it · why it matters) — no new
   claims, numbers, or sources are introduced.

   Behaviour:
     • First analysis page opened in a tab session → panel EXPANDED (orients newcomers).
     • Later pages / revisits → panel starts COLLAPSED; the header toggles it any time.
     • A "Next →" cue at the bottom follows the sidebar workflow order.
   Survives Dash page swaps via a MutationObserver. No permanent storage. */
(function () {
  "use strict";

  // route → [what this shows, how to read it, why it matters]
  var ABOUT = {
    snowpack: ["The basin's snowpack (SNOTEL SWE) and how it translates into the water-year runoff outlook.",
      "Track peak snow-water-equivalent against the record; a low peak or early melt points to a lean supply year.",
      "Snowpack is the basin's largest natural reservoir — its size and timing set the year's water budget."],
    elevsnow: ["Snow-decline trends across the 103 SNOTEL stations, tested against station elevation and latitude.",
      "Each station carries a Mann-Kendall trend in peak SWE; controlled for latitude and record length, elevation is not a significant driver (p ≈ 0.56).",
      "It checks the common assumption that high country dries first — a myth the data does not support."],
    timing: ["Daily-resolution melt timing and flash-drought metrics from the VIC record.",
      "Read the melt center-of-timing shifting earlier over the decades; earlier melt means water leaves before the demand season.",
      "When snow melts matters as much as how much — timing shifts stress reservoirs and irrigation schedules."],
    watbal: ["The basin water balance — where each unit of precipitation goes: evapotranspiration, runoff, and storage change.",
      "Follow the stacked terms and the runoff ratio (Q/P) trend; a falling ratio means less of each storm reaches the river.",
      "It shows, in one accounting, how much of the incoming water the basin actually delivers downstream."],
    budyko: ["Each basin's position in Budyko space (aridity index PET/P vs evaporative index ET/P), 1984–2024.",
      "Watch the annual points drift up-and-right toward the water-limited corner — that drift is aridification.",
      "It reveals a structural shift from energy-limited to water-limited, not just a run of dry years."],
    links: ["How antecedent soil moisture and spring weather connect to the following summer's streamflow.",
      "Compare the spring-heat and soil-moisture correlations to summer flow; the stronger bar is the better early predictor.",
      "It identifies which early signals a manager can watch to anticipate the summer water supply."],
    october: ["Whether the soil moisture the basin carries into 1 October forecasts the whole water year's yield.",
      "Read the fit and its honest out-of-sample skill (leave-one-out R² ≈ 0.45) — a wet October tilts the odds toward a wetter year.",
      "It offers a supply signal months before any snow-based forecast is issued."],
    drought: ["Drought and shortage risk: basin runoff against a shortage threshold, exceedance probability, and a soil-moisture deficit index.",
      "Set a threshold and read the rolling probability of falling below it; deeper, more frequent deficits mean rising risk.",
      "It translates hydrology into the shortage-probability terms operations and planning actually use."],
    reservoirs: ["The operational bridge: VIC streamflow feeding shortage-tier logic for Lake Mead and Powell.",
      "Read modelled supply against the USBR shortage-tier thresholds to see which tier a year would trigger.",
      "Tier declarations set real delivery cuts — this connects the hydrology to those decisions."],
    cascade: ["How a precipitation deficit propagates through soil moisture, runoff, and total storage (GRACE).",
      "Follow the lagged, standardized anomalies down the cascade; each step lags and often amplifies the one before it.",
      "It shows why a dry sky becomes a multi-year storage deficit — and how long the memory lasts."],
    recovery: ["The 2023 near-record snow year as a natural before/after experiment on drought recovery.",
      "Compare how far SWE, soil moisture, runoff and GRACE storage rebounded in 2023 — and how quickly they relapsed in 2024.",
      "It measures how much a single wet year can, and cannot, undo after a deep megadrought."],
    tws: ["NASA GRACE terrestrial water storage: the anomaly time series, accumulated deficit, and seasonal cycle.",
      "Read the deficit accumulation as the basin's 'water bank account' — a steadily deepening balance is drought memory.",
      "Total storage is the integrated bottom line of every gain and loss the basin has seen."],
    storage: ["Groundwater reconstructed as the residual of GRACE total storage minus VIC's modelled soil + snow.",
      "The residual ≈ groundwater + reservoir change — the depletion that no surface gauge can see directly.",
      "It surfaces the invisible, largely groundwater, part of the loss that drives long-term supply risk."],
    warming: ["Two land-surface warming signatures from the VIC record: warming rates and the surface energy / evaporative-demand response.",
      "Note that warming rises while latent-heat flux falls — the land has less water left to evaporate.",
      "It is the physical fingerprint of a basin tipping from energy-limited to water-limited."],
    aridification: ["How much of the river's yield is being lost to warming itself, separate from any change in precipitation.",
      "Read the fitted warming sensitivity (runoff lost per +1 °C); a negative value means heat alone is draining supply.",
      "It isolates the warming-driven share of decline — the part that persists even in a normal-rain year."],
    asi: ["The Aridification Severity Index — a 0–100 composite of four independent VIC stress signals per basin-year.",
      "Higher is more stressed; the trend across years matters more than any single value.",
      "One index lets you rank and track basins on a single, comparable stress scale."],
    scenario: ["A what-if engine: each basin's own observed rainfall/temperature sensitivity of runoff, fitted from 1984–2024.",
      "Dial a precipitation change and a warming amount to project the change in water yield, shown with a confidence band.",
      "It answers the question managers actually ask — how supply responds to a warmer, drier, or wetter future."],
    uncertainty: ["Every uncertainty estimate in the tool, gathered in one place: confidence intervals, significance, and validation skill.",
      "Read each result beside its error band and p-value; wider bands mean less certainty, not a different answer.",
      "It states plainly how confident each headline number is — the honesty a technical audience expects."],
    nmme: ["Published seasonal streamflow forecasts combining the NMME climate models with VIC.",
      "Read the forecast skill by lead time; skill fades as the horizon lengthens.",
      "It shows how far ahead, and how reliably, the basin's supply can be forecast today."],
    future: ["Historical VIC time series anchored to a real WY2100 projection, by decade and variable.",
      "Compare the decade-by-decade means and the 2100 anchor to see the direction and pace of change.",
      "It places today's conditions on the long arc toward end-of-century."],
    cmip: ["Long-range CMIP5 and CMIP6 climate projections, kept honestly separate from the tool's own results.",
      "Read the published ensemble result and rankings distinctly from the interactive layer — each is labelled.",
      "It frames the tool's basin findings inside the broader climate-model consensus."],
    noanalog: ["Which projected WY2100 variables fall outside the entire 1984–2024 historical range — a 'no-analog' future.",
      "Any variable flagged outside its historical envelope has no precedent in the record to learn from.",
      "No-analog conditions are where past experience stops being a reliable guide for planning."],
    basinwide: ["The whole basin at once: an interactive anomaly grid across sub-basins for a chosen water year.",
      "Red is drier than the 1984–2024 normal, blue wetter; recent years light up red across the basin.",
      "It gives a single shared picture so every sub-basin is read on the same evidence."],
    spatial: ["The spatial hub — choropleths, all 103 SNOTEL stations, HUC-10 units, and the VIC grid heatmap.",
      "Switch layers and periods to see where change concentrates, not just the basin average.",
      "Basin averages hide local extremes; the map shows who is affected and where."],
    spatcompare: ["Side-by-side spatial comparison of two periods across the VIC grid.",
      "Read the difference map to see where conditions shifted most between the periods.",
      "It pinpoints the places carrying the basin-wide trend."],
    animations: ["Looping animations built from the real VIC reanalysis, the river network, and dam locations.",
      "Watch the seasonal and drought cycles play out in space over the record.",
      "Motion makes the pace and geography of change legible at a glance."],
    governance: ["The 'Law of the River': a 1922–2022 water-governance analysis of the basin's rules and rights.",
      "Read the timeline of compacts, tiers and tribal rights — many senior rights remain unquantified.",
      "Hydrology only becomes policy through this legal framework, which constrains every allocation."],
    cria: ["The Infrastructure-Asset framing — treating the Colorado River as an asset to be managed and maintained.",
      "Read it as the project's end-vision that ties the analyses to management decisions.",
      "It connects the science to how the basin is actually operated and invested in."],
    methods: ["The methods and data behind every figure: the VIC reanalysis, NASA products, and processing pipeline.",
      "Use it to trace any result back to its data source and computation.",
      "Transparent methods are what let a technical reader trust — and reproduce — the numbers."],
    references: ["Validation and references: every published result beside the tool's own value, with an honest verdict.",
      "Read each row as app-value vs published-value and whether they match.",
      "It is the receipt for the tool's credibility — claims checked against the literature."]
  };

  // Sidebar workflow order (matches app.py GROUPS) → the "Next" step for each page.
  var ORDER = ["snowpack", "elevsnow", "timing", "watbal", "budyko", "links", "october",
    "drought", "reservoirs", "cascade", "recovery", "tws", "storage", "warming",
    "aridification", "asi", "scenario", "uncertainty", "nmme", "future", "cmip",
    "noanalog", "basinwide", "spatial", "spatcompare", "animations",
    "governance", "cria", "methods", "publications", "references"];
  var LABELS = {
    snowpack: "Snowpack & Runoff", elevsnow: "Elevation-Dependent Snow Loss", timing: "Snowmelt Timing",
    watbal: "Basin Water Balance", budyko: "Budyko Water–Energy Balance", links: "Soil Moisture & Streamflow",
    october: "October Signal", drought: "Drought & Shortage Risk", reservoirs: "Reservoirs & Shortage Tiers",
    cascade: "Drought Propagation", recovery: "Drought Recovery", tws: "Water Storage — GRACE",
    storage: "Subsurface Storage", warming: "Surface Warming & Energy", aridification: "Aridification",
    asi: "Aridity Severity Index", scenario: "Scenario Explorer", uncertainty: "Uncertainty & Confidence",
    nmme: "Seasonal Forecasts (NMME)", future: "Projections to 2100", cmip: "Climate Projections (CMIP5/6)",
    noanalog: "No-Analog Climate", basinwide: "Basin-Wide Overview", spatial: "Maps Over Time",
    spatcompare: "Compare by Year", animations: "Seasonal Cycles", governance: "Water Governance",
    cria: "Infrastructure Asset Framework", methods: "Methods & Data", publications: "Publications",
    references: "References & Validation"
  };

  var SEEN = "cria_about_seen";
  function seen() { try { return sessionStorage.getItem(SEEN) === "1"; } catch (e) { return false; } }
  function markSeen() { try { sessionStorage.setItem(SEEN, "1"); } catch (e) {} }

  function currentView() {
    var p = (location.pathname || "/").replace(/^\/+|\/+$/g, "");
    return p === "" ? "home" : p;
  }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function buildPanel(view) {
    var a = ABOUT[view];
    var panel = el("div", "abt-panel");
    panel.setAttribute("data-about", view);
    var head = el("button", "abt-head");
    head.setAttribute("aria-expanded", "true");
    head.innerHTML =
      '<span class="abt-head-l"><i class="bi bi-info-circle-fill"></i>' +
      '<span class="abt-title">About this analysis</span></span>' +
      '<span class="abt-head-r"><span class="abt-hint">New here — start with this</span>' +
      '<i class="bi bi-chevron-down abt-chev"></i></span>';
    function row(ic, k, v) {
      return '<div class="abt-row"><i class="bi ' + ic + ' abt-ic"></i>' +
        '<div class="abt-txt"><span class="abt-k">' + k + '</span>' +
        '<span class="abt-v">' + v + '</span></div></div>';
    }
    var body = el("div", "abt-body",
      row("bi-eye", "What this shows", a[0]) +
      row("bi-rulers", "How to read it", a[1]) +
      row("bi-compass", "Why it matters", a[2]));
    panel.appendChild(head);
    panel.appendChild(body);
    // collapse state: first time this session expanded, thereafter collapsed
    if (seen()) setCollapsed(panel, true); else { setCollapsed(panel, false); markSeen(); }
    return panel;
  }

  function buildCue(view) {
    var i = ORDER.indexOf(view);
    if (i < 0 || i >= ORDER.length - 1) return null;
    var nxt = ORDER[i + 1], label = LABELS[nxt];
    if (!label) return null;
    var a = el("a", "nxt-cue");
    a.href = "/" + nxt;
    a.innerHTML =
      '<div class="nxt-txt"><span class="nxt-kick">NEXT IN THE WORKFLOW</span>' +
      '<span class="nxt-label">' + label + '</span></div>' +
      '<span class="nxt-go"><span>Continue</span><i class="bi bi-arrow-right-circle-fill"></i></span>';
    return a;
  }

  function setCollapsed(panel, yes) {
    panel.classList.toggle("collapsed", yes);
    var head = panel.querySelector(".abt-head");
    if (head) head.setAttribute("aria-expanded", yes ? "false" : "true");
  }

  function inject() {
    var view = currentView();
    var pc = document.getElementById("page-content");
    if (!pc) return;
    // render_page returns a single wrapper <div>; wait for it so we never inject into a
    // half-rendered container (that used to cause a duplicate panel).
    var wrap = pc.firstElementChild;
    if (!wrap || wrap.tagName !== "DIV") return;
    // Drop anything left over from a previous route (belt-and-braces; React usually clears it).
    pc.querySelectorAll(".abt-panel").forEach(function (p) {
      if (p.getAttribute("data-about") !== view) p.remove();
    });
    pc.querySelectorAll(".nxt-cue").forEach(function (c) {
      if (c.getAttribute("data-nxt-for") !== view) c.remove();
    });
    // Panel — one per page, only for routes we have an entry for.
    if (ABOUT[view] && !pc.querySelector(".abt-panel")) {
      wrap.insertBefore(buildPanel(view), wrap.firstChild);
    }
    // Next cue at the bottom — one per page.
    if (!pc.querySelector(".nxt-cue")) {
      var cue = buildCue(view);
      if (cue) { cue.setAttribute("data-nxt-for", view); wrap.appendChild(cue); }
    }
  }

  // toggle on header click (event delegation — survives re-injection)
  document.addEventListener("click", function (e) {
    var head = e.target.closest && e.target.closest(".abt-head");
    if (!head) return;
    var panel = head.closest(".abt-panel");
    if (!panel) return;
    e.preventDefault();
    setCollapsed(panel, !panel.classList.contains("collapsed"));
  });

  var pending = null;
  function schedule() { if (pending) return; pending = setTimeout(function () { pending = null; inject(); }, 120); }

  if (window.MutationObserver) {
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule);
  } else {
    schedule();
  }
})();
