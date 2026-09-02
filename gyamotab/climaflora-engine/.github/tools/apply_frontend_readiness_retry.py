from __future__ import annotations

from pathlib import Path

APP = Path("frontend/static/app.js")
PROGRESS = Path("frontend/static/search-progress.js")
INDEX = Path("frontend/index.html")

MARKER = "CLIMAFLORA_READINESS_RETRY_ACTIVE"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "fetchWithTimeout(`${candidate}/health?probe=${Date.now()}`, {cache:'no-store'}, 10000)",
        "fetchWithTimeout(`${candidate}/health?probe=${Date.now()}`, {cache:'no-store'}, 30000)",
        "health cold-start timeout",
    )
    APP.write_text(text, encoding="utf-8")


def patch_progress() -> None:
    text = PROGRESS.read_text(encoding="utf-8")
    if MARKER in text:
        return
    addition = r'''

/* Keep the search CTA recoverable across Hugging Face cold starts. Search v0.10
   prewarms its immutable runtime at startup, so the first health/readiness probe
   may legitimately take longer than the historical 10 s frontend timeout. */
(() => {
  'use strict';

  if (window.CLIMAFLORA_READINESS_RETRY_ACTIVE) return;
  window.CLIMAFLORA_READINESS_RETRY_ACTIVE = true;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function showConnectingState() {
    const button = document.getElementById('search');
    if (!button || button.classList.contains('loading')) return;
    button.disabled = true;
    button.textContent = 'Connexion au moteur scientifique…';
  }

  async function waitForScientificReadiness() {
    let delayMs = 2500;
    await sleep(250);

    while (true) {
      if (typeof state !== 'undefined' && state.scientificReady) return;
      showConnectingState();

      try {
        if (typeof resolveApiBase === 'function') await resolveApiBase();
        if (typeof loadReadiness === 'function') await loadReadiness();
        if (typeof state !== 'undefined' && state.scientificReady) return;
      } catch (_) {
        // The normal app bootstrap already exposes a warning. This loop only
        // keeps recovery automatic when the backend wakes up afterwards.
      }

      showConnectingState();
      await sleep(delayMs);
      delayMs = Math.min(15000, Math.round(delayMs * 1.5));
    }
  }

  waitForScientificReadiness().catch(() => {});
})();
'''
    PROGRESS.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def patch_index() -> None:
    text = INDEX.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '<button class="primary search-cta" disabled="" id="search">Lancer la recherche <span>→</span></button>',
        '<button class="primary search-cta" disabled="" id="search">Connexion au moteur scientifique…</button>',
        "initial search CTA",
    )
    text = replace_once(
        text,
        '<script src="static/app.js?v=beta-20260821-1000"></script>',
        '<script src="static/app.js?v=frontend-v10-readiness-20260823-1"></script>',
        "app.js cache buster",
    )
    text = replace_once(
        text,
        '<script src="static/search-v2.js?v=frontend-v10-exhaustive"></script>',
        '<script src="static/search-v2.js?v=frontend-v10-readiness-20260823-1"></script>',
        "search-v2 cache buster",
    )
    text = replace_once(
        text,
        '<script src="static/search-progress.js?v=frontend-v10-progress-1"></script>',
        '<script src="static/search-progress.js?v=frontend-v10-readiness-20260823-1"></script>',
        "search-progress cache buster",
    )
    INDEX.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app()
    patch_progress()
    patch_index()
    print("frontend readiness retry fix applied")


if __name__ == "__main__":
    main()
