/* Keep every Plotly graph perfectly fitted to its container at ALL sizes.

   Dash graphs only re-layout on *window* resize by default. But the container
   can change size without the window doing so — the sidebar drawer opening,
   the A/A/A display-size switch, a tab changing width, a column reflowing.
   When that happens the graph keeps its old pixel size and axis labels / titles
   get clipped or spill out. A ResizeObserver on each plot's container fixes it:
   whenever the container resizes, we tell Plotly to re-fit the figure. */
(function () {
  if (typeof window === "undefined") return;
  var RO = window.ResizeObserver;
  var seen = (typeof WeakSet !== "undefined") ? new WeakSet() : null;

  function fit(gd) {
    if (window.Plotly && gd && gd._fullLayout) {
      try { window.Plotly.Plots.resize(gd); } catch (e) {}
    }
  }

  function hook() {
    var plots = document.querySelectorAll(".js-plotly-plot");
    for (var i = 0; i < plots.length; i++) {
      var gd = plots[i];
      if (seen && seen.has(gd)) continue;
      if (seen) seen.add(gd);
      if (RO) {
        (function (node) {
          var ro = new RO(function () { fit(node); });
          ro.observe(node.parentNode || node);
        })(gd);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", hook);
  window.addEventListener("load", hook);
  // Dash re-creates graphs on navigation — re-attach observers periodically.
  setInterval(hook, 1200);
  window.addEventListener("resize", function () {
    var plots = document.querySelectorAll(".js-plotly-plot");
    for (var i = 0; i < plots.length; i++) fit(plots[i]);
  });
})();
