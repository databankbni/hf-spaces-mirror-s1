(() => {
  'use strict';

  if (window.CLIMAFLORA_SEARCH_PROGRESS_ACTIVE) return;
  window.CLIMAFLORA_SEARCH_PROGRESS_ACTIVE = true;

  const nf = new Intl.NumberFormat('fr-FR');
  const nativeFetch = window.fetch.bind(window);
  const progressState = {
    active: false,
    total: 0,
    loadedByOffset: new Map(),
    hideTimer: null
  };

  function isSearchRequest(input) {
    const url = typeof input === 'string' ? input : input?.url;
    return /\/recommendations\/search(?:\?|$)/.test(String(url || ''));
  }

  function ensureProgressUi() {
    const button = document.getElementById('search');
    if (!button) return null;

    if (!document.getElementById('climaflora-search-progress-style')) {
      const style = document.createElement('style');
      style.id = 'climaflora-search-progress-style';
      style.textContent = `
        .cf-search-progress{width:100%;margin-top:9px;padding:10px 12px;border:1px solid var(--line,#dce5da);border-radius:9px;background:#fff;box-shadow:0 4px 14px rgba(25,54,34,.035)}
        .cf-search-progress[hidden]{display:none!important}
        .cf-search-progress-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:7px}
        .cf-search-progress-label{font-size:13px;font-weight:800;color:var(--ink,#10241a)}
        .cf-search-progress-value{min-width:42px;text-align:right;font-size:12px;font-weight:800;color:var(--green,#1f6d35)}
        .cf-search-progress-track{position:relative;height:8px;overflow:hidden;border-radius:999px;background:#edf2eb}
        .cf-search-progress-bar{display:block;height:100%;width:0;border-radius:inherit;background:linear-gradient(90deg,#1b632f,#2b7a42);transition:width .24s ease}
        .cf-search-progress-track.is-indeterminate .cf-search-progress-bar{width:38%;animation:cf-search-progress-slide 1.15s ease-in-out infinite;transition:none}
        .cf-search-progress-detail{margin-top:6px;color:var(--muted,#66746b);font-size:11px;line-height:1.35}
        @keyframes cf-search-progress-slide{0%{transform:translateX(-120%)}100%{transform:translateX(360%)}}
        @media (prefers-reduced-motion:reduce){.cf-search-progress-track.is-indeterminate .cf-search-progress-bar{width:55%;animation:none}.cf-search-progress-bar{transition:none}}
      `;
      document.head.appendChild(style);
    }

    let box = document.getElementById('search-progress');
    if (!box) {
      box = document.createElement('div');
      box.id = 'search-progress';
      box.className = 'cf-search-progress';
      box.hidden = true;
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      box.innerHTML = `
        <div class="cf-search-progress-head">
          <span class="cf-search-progress-label" id="search-progress-label">Analyse du catalogue…</span>
          <strong class="cf-search-progress-value" id="search-progress-value"></strong>
        </div>
        <div class="cf-search-progress-track" id="search-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">
          <span class="cf-search-progress-bar" id="search-progress-bar"></span>
        </div>
        <div class="cf-search-progress-detail" id="search-progress-detail"></div>`;
      button.insertAdjacentElement('afterend', box);
    }
    return box;
  }

  function refs() {
    const box = ensureProgressUi();
    if (!box) return null;
    return {
      box,
      label: document.getElementById('search-progress-label'),
      value: document.getElementById('search-progress-value'),
      track: document.getElementById('search-progress-track'),
      bar: document.getElementById('search-progress-bar'),
      detail: document.getElementById('search-progress-detail')
    };
  }

  function setIndeterminate(label, detail) {
    const ui = refs();
    if (!ui) return;
    ui.box.hidden = false;
    ui.label.textContent = label;
    ui.value.textContent = '';
    ui.detail.textContent = detail || '';
    ui.track.classList.add('is-indeterminate');
    ui.track.removeAttribute('aria-valuenow');
    ui.track.setAttribute('aria-valuetext', label);
    ui.bar.style.width = '';
  }

  function setDeterminate(percent, label, detail) {
    const ui = refs();
    if (!ui) return;
    const value = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
    ui.box.hidden = false;
    ui.label.textContent = label;
    ui.value.textContent = `${value} %`;
    ui.detail.textContent = detail || '';
    ui.track.classList.remove('is-indeterminate');
    ui.track.setAttribute('aria-valuenow', String(value));
    ui.track.setAttribute('aria-valuetext', `${label} ${value} %`);
    ui.bar.style.width = `${value}%`;
  }

  function beginProgress() {
    if (progressState.hideTimer) clearTimeout(progressState.hideTimer);
    progressState.active = true;
    progressState.total = 0;
    progressState.loadedByOffset.clear();
    const phase = document.getElementById('search')?.dataset.searchPhase || 'analysis';
    if (phase === 'filter') {
      setIndeterminate('Application des filtres…', 'Les scores déjà calculés sont conservés ; seule la sélection affichée est mise à jour.');
    } else if (phase === 'page') {
      setIndeterminate('Chargement de la page…', 'Récupération des 100 résultats suivants déjà classés.');
    } else {
      setIndeterminate('Analyse exhaustive du catalogue…', 'Évaluation des taxons éligibles selon le climat et le sol sélectionnés.');
    }
  }

  function finishProgress() {
    if (!progressState.active) return;
    progressState.active = false;
    const loaded = [...progressState.loadedByOffset.values()].reduce((sum, value) => sum + value, 0);
    const detail = progressState.total
      ? `${nf.format(progressState.total)} résultat${progressState.total > 1 ? 's' : ''} trouvé${progressState.total > 1 ? 's' : ''}.`
      : loaded
        ? `${nf.format(loaded)} résultat${loaded > 1 ? 's' : ''} chargé${loaded > 1 ? 's' : ''}.`
        : 'Résultats prêts.';
    setDeterminate(100, 'Recherche terminée', detail);
    progressState.hideTimer = setTimeout(() => {
      const box = document.getElementById('search-progress');
      if (box && !progressState.active) box.hidden = true;
    }, 1100);
  }

  function updateFromPayload(payload) {
    if (!progressState.active || !payload) return;
    const total = Number(payload.metrics?.total_results || 0);
    const offset = Number(payload.pagination?.offset || 0);
    const returned = Number(payload.pagination?.returned || payload.recommendations?.length || 0);
    if (total > 0) progressState.total = total;
    progressState.loadedByOffset.set(offset, returned);

    if (!total) {
      setIndeterminate('Préparation des résultats…', 'Le calcul est terminé, mise en forme des résultats.');
      return;
    }

    setDeterminate(
      95,
      offset > 0 ? 'Page prête…' : 'Résultats prêts…',
      `${nf.format(returned)} résultat${returned > 1 ? 's' : ''} chargé${returned > 1 ? 's' : ''} sur ${nf.format(total)}.`
    );
  }

  window.fetch = async (...args) => {
    const tracked = isSearchRequest(args[0]);
    const signal = args[1]?.signal;
    const response = await nativeFetch(...args);
    if (tracked && response.ok && !signal?.aborted) {
      response.clone().json().then(updateFromPayload).catch(() => {});
    }
    return response;
  };

  function install() {
    const button = document.getElementById('search');
    if (!button) return;
    ensureProgressUi();

    const sync = () => {
      const loading = button.classList.contains('loading');
      if (loading && !progressState.active) beginProgress();
      if (!loading && progressState.active) finishProgress();
    };

    new MutationObserver(sync).observe(button, {
      attributes: true,
      attributeFilter: ['class'],
      childList: true,
      characterData: true,
      subtree: true
    });
    sync();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();

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
