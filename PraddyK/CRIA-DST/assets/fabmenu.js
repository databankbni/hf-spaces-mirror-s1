/* Collapse the floating action pills into a single dot on small screens */
(function () {
  document.addEventListener("click", function (e) {
    var tog = e.target.closest && e.target.closest("#fab-toggle");
    if (tog) { e.preventDefault(); document.body.classList.toggle("fab-open"); return; }
    var pill = e.target.closest && e.target.closest("#fab-stack a, #fab-stack button");
    if (pill) { document.body.classList.remove("fab-open"); return; }
    if (document.body.classList.contains("fab-open") &&
        !(e.target.closest && (e.target.closest("#fab-stack") || e.target.closest("#fab-toggle")))) {
      document.body.classList.remove("fab-open");
    }
  });
})();
