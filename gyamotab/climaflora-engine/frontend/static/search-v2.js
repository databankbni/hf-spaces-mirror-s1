(() => {
  'use strict';

  const STATUS_KEYS = ['GREEN', 'ORANGE', 'RED', 'UNKNOWN'];
  const STATUS_LABELS = {
    GREEN: 'Favorable', ORANGE: 'Sous contrainte', RED: 'À risque', UNKNOWN: 'Données limitées'
  };
  const LIFE_KEYS = ['ALL', 'TREE', 'SHRUB', 'HERB', 'CLIMBER', 'PALM', 'OTHER', 'UNKNOWN'];
  const LIFE_LABELS = {
    ALL: 'Tous', TREE: 'Arbres', SHRUB: 'Arbustes', HERB: 'Herbacées',
    CLIMBER: 'Grimpantes', PALM: 'Palmiers', OTHER: 'Autres', UNKNOWN: 'Non renseigné'
  };
  const nf = new Intl.NumberFormat('fr-FR');
  const PAGE_SIZE = 100;
  const PAGE_CACHE_MAX = 60;
  const GENUS_FUNCTION_PREFIX = '__CF_GENUS_INITIAL_';

  const searchV2 = {
    life: 'ALL',
    functions: new Set(),
    statuses: new Set(STATUS_KEYS),
    soilStatuses: new Set(STATUS_KEYS),
    genusInitial: 'ALL',
    offset: 0,
    pageSize: PAGE_SIZE,
    hasRun: false,
    running: false,
    abortController: null,
    lastData: null,
    serverSubtitle: '',
    pageCache: new Map()
  };

  const initialUi = {
    lat: $('lat')?.value || '46.2044',
    lon: $('lon')?.value || '6.1432',
    horizon: state.horizon || '2050',
    scenario: state.scenario || 'MEDIUM'
  };

  window.CLIMAFLORA_SERVER_SEARCH_ACTIVE = true;
  state.searchV2 = searchV2;

  const comparisonWording = /À titre de comparaison\s*:?\s*/g;
  function cleanComparisonWording(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      root.nodeValue = String(root.nodeValue || '').replace(comparisonWording, '');
      comparisonWording.lastIndex = 0;
      return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      node.nodeValue = String(node.nodeValue || '').replace(comparisonWording, '');
      comparisonWording.lastIndex = 0;
    }
  }

  function functionLabels() {
    return new Map((state.meta?.functions || []).map(item => [item.value, item.label]));
  }

  function syncTopControls() {
    document.querySelectorAll('.lifeform-grid button').forEach(button => {
      button.classList.toggle('active', button.dataset.lifeform === searchV2.life);
    });
    document.querySelectorAll('#functions button').forEach(button => {
      const value = button.dataset.value || '';
      const active = value ? searchV2.functions.has(value) : searchV2.functions.size === 0;
      button.classList.toggle('active', active);
    });
  }

  function activeChips() {
    const chips = [];
    const fnLabels = functionLabels();
    if (searchV2.life !== 'ALL') {
      chips.push({dimension: 'life', value: searchV2.life, label: LIFE_LABELS[searchV2.life] || searchV2.life});
    }
    [...searchV2.functions].forEach(value => {
      chips.push({dimension: 'function', value, label: fnLabels.get(value) || value});
    });
    if (searchV2.statuses.size < STATUS_KEYS.length) {
      [...searchV2.statuses].forEach(value => {
        chips.push({dimension: 'status', value, label: `Climat · ${STATUS_LABELS[value]}`});
      });
    }
    if (searchV2.soilStatuses.size < STATUS_KEYS.length) {
      [...searchV2.soilStatuses].forEach(value => {
        chips.push({dimension: 'soil-status', value, label: `Sol · ${STATUS_LABELS[value]}`});
      });
    }
    return chips;
  }

  function facetRow({dimension, value, label, count, checked, type = 'checkbox'}) {
    return `<label class="server-facet-row">
      <input type="${type}" name="facet-${esc(dimension)}" data-facet-dimension="${esc(dimension)}" value="${esc(value)}" ${checked ? 'checked' : ''}>
      <span>${esc(label)}</span><small>${nf.format(Number(count || 0))}</small>
    </label>`;
  }

  function renderFilters(data) {
    const panel = document.querySelector('.filters-panel');
    if (!panel) return;
    const open = new Set([...panel.querySelectorAll('details[open]')].map(node => node.dataset.dimension));
    const facets = data?.facets || {life_form:{}, functions:{}, climate_status:{}, soil_status:{}};
    const fnLabels = functionLabels();
    const chips = activeChips();
    const metrics = data?.metrics || {};
    const functionEntries = Object.entries(facets.functions || {})
      .sort((a, b) => Number(b[1]) - Number(a[1]));

    panel.dataset.v4 = '1';
    panel.dataset.serverFacets = '1';
    panel.innerHTML = `
      <div class="filters-head"><strong>Affiner les résultats</strong><button id="reset-server-filters" type="button">Réinitialiser</button></div>
      <p class="facet-scope-note">Compteurs calculés sur toute la population évaluée, pas seulement sur les cartes affichées.</p>
      <div class="active-filter-zone">
        <div class="active-filter-title">Filtres actifs</div>
        <div class="active-filter-chips">${chips.length ? chips.map(chip => `<button type="button" class="active-filter-chip" data-remove-dimension="${esc(chip.dimension)}" data-remove-value="${esc(chip.value)}">${esc(chip.label)} <span aria-hidden="true">×</span></button>`).join('') : '<span class="no-active-filter">Aucun filtre restrictif</span>'}</div>
      </div>
      <details class="server-filter-group" data-dimension="climate" ${open.has('climate') || !data ? 'open' : ''}>
        <summary><span>Niveau d’adaptation</span></summary>
        <div class="server-filter-options">${STATUS_KEYS.map(key => facetRow({dimension:'status', value:key, label:STATUS_LABELS[key], count:facets.climate_status?.[key], checked:searchV2.statuses.has(key)})).join('')}</div>
      </details>
      <details class="server-filter-group" data-dimension="function" ${open.has('function') ? 'open' : ''}>
        <summary><span>Fonctions documentées</span></summary>
        <div class="server-filter-options">${functionEntries.length ? functionEntries.map(([key,count]) => facetRow({dimension:'function', value:key, label:fnLabels.get(key) || key, count, checked:searchV2.functions.has(key)})).join('') : '<p class="facet-empty">Aucune fonction documentée dans ce sous-ensemble.</p>'}</div>
      </details>
      <details class="server-filter-group" data-dimension="life" ${open.has('life') ? 'open' : ''}>
        <summary><span>Type de végétal</span></summary>
        <div class="server-filter-options">
          ${facetRow({dimension:'life', value:'ALL', label:'Tous', count:metrics.catalog_total, checked:searchV2.life === 'ALL', type:'radio'})}
          ${LIFE_KEYS.filter(key => key !== 'ALL').map(key => facetRow({dimension:'life', value:key, label:LIFE_LABELS[key], count:facets.life_form?.[key], checked:searchV2.life === key, type:'radio'})).join('')}
        </div>
      </details>
      <details class="server-filter-group" data-dimension="soil" ${open.has('soil') ? 'open' : ''}>
        <summary><span>Compatibilité du sol</span></summary>
        <div class="server-filter-options">${STATUS_KEYS.map(key => facetRow({dimension:'soil-status', value:key, label:STATUS_LABELS[key], count:facets.soil_status?.[key], checked:searchV2.soilStatuses.has(key)})).join('')}</div>
      </details>`;
  }

  function setStatusValue(targetSet, value, checked, input) {
    checked ? targetSet.add(value) : targetSet.delete(value);
    if (!targetSet.size) {
      targetSet.add(value);
      if (input) input.checked = true;
      return false;
    }
    return true;
  }

  function resetFilters() {
    searchV2.life = 'ALL';
    searchV2.functions.clear();
    searchV2.statuses = new Set(STATUS_KEYS);
    searchV2.soilStatuses = new Set(STATUS_KEYS);
    searchV2.genusInitial = 'ALL';
    syncTopControls();
    if (searchV2.hasRun) runSearch(0, 'filter');
    else renderFilters(searchV2.lastData);
  }

  function removeChip(dimension, value) {
    if (dimension === 'life') searchV2.life = 'ALL';
    if (dimension === 'function') searchV2.functions.delete(value);
    if (dimension === 'status') {
      if (searchV2.statuses.size <= 1) searchV2.statuses = new Set(STATUS_KEYS);
      else searchV2.statuses.delete(value);
    }
    if (dimension === 'soil-status') {
      if (searchV2.soilStatuses.size <= 1) searchV2.soilStatuses = new Set(STATUS_KEYS);
      else searchV2.soilStatuses.delete(value);
    }
    syncTopControls();
    if (searchV2.hasRun) runSearch(0, 'filter');
    else renderFilters(searchV2.lastData);
  }

  function searchParams(offset) {
    const params = new URLSearchParams({
      lat: $('lat').value,
      lon: $('lon').value,
      horizon: state.horizon,
      scenario: state.scenario,
      life_form: searchV2.life,
      offset: String(offset),
      limit: String(PAGE_SIZE)
    });
    [...searchV2.functions].sort().forEach(value => params.append('function', value));
    if (searchV2.genusInitial !== 'ALL') {
      params.append('function', `${GENUS_FUNCTION_PREFIX}${searchV2.genusInitial}`);
    }
    if (searchV2.statuses.size < STATUS_KEYS.length) {
      [...searchV2.statuses].forEach(value => params.append('status', value));
    }
    if (searchV2.soilStatuses.size < STATUS_KEYS.length) {
      [...searchV2.soilStatuses].forEach(value => params.append('soil_status', value));
    }
    appendSoilParams(params);
    return params;
  }

  async function fetchPage(offset, signal) {
    const params = searchParams(offset);
    const cacheKey = params.toString();
    if (searchV2.pageCache.has(cacheKey)) return searchV2.pageCache.get(cacheKey);
    const response = await fetch(`${apiUrl('recommendations/search')}?${params}`, {signal});
    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    searchV2.pageCache.set(cacheKey, data);
    if (searchV2.pageCache.size > PAGE_CACHE_MAX) {
      searchV2.pageCache.delete(searchV2.pageCache.keys().next().value);
    }
    return data;
  }

  function paginationHtml(data) {
    if (data.fully_loaded) return '';
    const p = data.pagination || {};
    const total = Number(data.metrics?.total_results || 0);
    if (!total) return '';
    const start = Number(p.offset || 0) + 1;
    const end = Number(p.offset || 0) + Number(p.returned || 0);
    const previousOffset = Math.max(0, Number(p.offset || 0) - PAGE_SIZE);
    const nextOffset = Number(p.offset || 0) + PAGE_SIZE;
    return `<nav class="server-pagination" aria-label="Pagination des résultats">
      <button type="button" class="secondary" data-page-offset="${previousOffset}" ${p.has_previous ? '' : 'disabled'}>← Précédent</button>
      <span>${nf.format(start)}–${nf.format(end)} sur ${nf.format(total)}</span>
      <button type="button" class="secondary" data-page-offset="${nextOffset}" ${p.has_next ? '' : 'disabled'}>Suivant →</button>
    </nav>`;
  }

  function restoreServerSubtitle() {
    const subtitle = $('result-subtitle');
    if (!subtitle || !searchV2.serverSubtitle) return;
    subtitle.dataset.original = searchV2.serverSubtitle;
    if (subtitle.textContent !== searchV2.serverSubtitle) subtitle.textContent = searchV2.serverSubtitle;
  }

  function renderResults(data) {
    searchV2.lastData = data;
    const shown = data.recommendations?.length || 0;
    const metrics = data.metrics || {};
    const page = data.pagination || {};
    const total = Number(metrics.total_results || 0);
    const evaluated = Number(metrics.evaluated_candidates || 0);
    const start = shown ? Number(page.offset || 0) + 1 : 0;
    const end = shown ? Number(page.offset || 0) + shown : 0;

    $('result-title').textContent = `${nf.format(total)} plante${total > 1 ? 's' : ''} correspond${total > 1 ? 'ent' : ''} à votre recherche · ${state.horizon}`;
    // The detailed evaluated/displayed/method line is intentionally not shown in the public result header.
    searchV2.serverSubtitle = '';
    climateSummary(data.climate);
    soilSummary(data.soil);
    const cards = shown ? data.recommendations.map(plantCard).join('') : '<div class="empty">Aucun taxon ne correspond à ces filtres.</div>';
    $('results-list').innerHTML = cards + paginationHtml(data);
    renderFilters(data);
    syncTopControls();
    showWarning(data.warnings || []);
    cleanComparisonWording($('results-list'));
  }

  async function runSearch(offset = 0, reason = '') {
    if (!state.scientificReady) return loadReadiness();
    if (searchV2.abortController) searchV2.abortController.abort();
    const controller = new AbortController();
    searchV2.abortController = controller;
    searchV2.running = true;
    searchV2.offset = Math.max(0, Number(offset) || 0);
    const button = $('search');
    const phase = reason || (searchV2.hasRun ? 'filter' : 'analysis');
    button.dataset.searchPhase = phase;
    button.classList.add('loading');
    button.textContent = phase === 'analysis'
      ? 'Analyse exhaustive du catalogue…'
      : phase === 'page' ? 'Chargement de la page…' : 'Application des filtres…';
    $('trajectory').classList.add('hidden');

    try {
      const data = await fetchPage(searchV2.offset, controller.signal);
      searchV2.hasRun = true;
      renderResults(data);
    } catch (error) {
      if (error.name !== 'AbortError') {
        $('results-list').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`;
      }
    } finally {
      if (searchV2.abortController === controller) {
        searchV2.running = false;
        button.classList.remove('loading');
        delete button.dataset.searchPhase;
        button.textContent = 'Lancer la recherche →';
      }
    }
  }

  function setGenusInitial(value='ALL') {
    const normalized = String(value || 'ALL').trim().toUpperCase();
    searchV2.genusInitial = /^[A-Z]$/.test(normalized) ? normalized : 'ALL';
    if (searchV2.hasRun) return runSearch(0, 'filter');
    return Promise.resolve();
  }

  function installPanelEvents() {
    const panel = document.querySelector('.filters-panel');
    if (!panel || panel.dataset.serverV2Events === '1') return;
    panel.dataset.serverV2Events = '1';
    panel.addEventListener('change', event => {
      const input = event.target.closest('[data-facet-dimension]');
      if (!input) return;
      const dimension = input.dataset.facetDimension;
      const value = input.value;
      let changed = true;
      if (dimension === 'life') searchV2.life = value;
      if (dimension === 'function') input.checked ? searchV2.functions.add(value) : searchV2.functions.delete(value);
      if (dimension === 'status') changed = setStatusValue(searchV2.statuses, value, input.checked, input);
      if (dimension === 'soil-status') changed = setStatusValue(searchV2.soilStatuses, value, input.checked, input);
      syncTopControls();
      if (changed && searchV2.hasRun) runSearch(0, 'filter');
      else renderFilters(searchV2.lastData);
    });
    panel.addEventListener('click', event => {
      const reset = event.target.closest('#reset-server-filters');
      if (reset) { resetFilters(); return; }
      const chip = event.target.closest('[data-remove-dimension]');
      if (chip) removeChip(chip.dataset.removeDimension, chip.dataset.removeValue);
    });
  }

  function installCaptureControls() {
    document.addEventListener('click', event => {
      const searchButton = event.target.closest('#search');
      if (searchButton) {
        event.preventDefault();
        event.stopImmediatePropagation();
        runSearch(0);
        return;
      }

      const life = event.target.closest('.lifeform-grid button');
      if (life) {
        event.preventDefault();
        event.stopImmediatePropagation();
        searchV2.life = life.dataset.lifeform || 'ALL';
        syncTopControls();
        renderFilters(searchV2.lastData);
        if (searchV2.hasRun) runSearch(0, 'filter');
        return;
      }

      const fn = event.target.closest('#functions button');
      if (fn) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const value = fn.dataset.value || '';
        searchV2.functions.clear();
        if (value) searchV2.functions.add(value);
        syncTopControls();
        renderFilters(searchV2.lastData);
        if (searchV2.hasRun) runSearch(0, 'filter');
        return;
      }

      const horizon = event.target.closest('#horizons button');
      if (horizon) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (window.CLIMAFLORA_ACCESS && !window.CLIMAFLORA_ACCESS.canUseHorizon(horizon.dataset.value)) {
          window.CLIMAFLORA_AUTH?.open();
          return;
        }
        document.querySelectorAll('#horizons button').forEach(button => button.classList.toggle('active', button === horizon));
        state.horizon = horizon.dataset.value;
        if (searchV2.hasRun) runSearch(0, 'analysis');
        return;
      }

      const page = event.target.closest('[data-page-offset]');
      if (page && !page.disabled) {
        event.preventDefault();
        event.stopImmediatePropagation();
        runSearch(Number(page.dataset.pageOffset || 0), 'page');
        document.getElementById('results')?.scrollIntoView({behavior:'smooth', block:'start'});
      }
    }, true);

    document.addEventListener('change', event => {
      if (event.target?.id !== 'scenario') return;
      state.scenario = event.target.value;
      if (searchV2.hasRun) setTimeout(() => runSearch(0, 'analysis'), 0);
    }, true);
  }

  function resetSearch() {
    searchV2.abortController?.abort();
    searchV2.abortController = null;
    searchV2.hasRun = false;
    searchV2.running = false;
    searchV2.offset = 0;
    searchV2.lastData = null;
    searchV2.serverSubtitle = '';
    searchV2.pageCache.clear();
    searchV2.life = 'ALL';
    searchV2.functions.clear();
    searchV2.statuses = new Set(STATUS_KEYS);
    searchV2.soilStatuses = new Set(STATUS_KEYS);
    searchV2.genusInitial = 'ALL';

    state.horizon = initialUi.horizon;
    state.scenario = initialUi.scenario;
    state.fn = '';
    state.selectedPlant = null;
    state.lastRecommendations = [];
    state.lastEvaluatedCandidates = 0;
    state.sortMode = 'scientific';
    clearTimeout(state.plantSearchTimer);

    if (typeof switchMode === 'function') switchMode('explore');
    if (typeof setPoint === 'function') setPoint(initialUi.lat, initialUi.lon);
    const city = $('city-search');
    if (city) city.value = '';
    if (typeof hideCitySuggestions === 'function') hideCitySuggestions();
    document.querySelectorAll('#horizons button').forEach(button => {
      button.classList.toggle('active', button.dataset.value === initialUi.horizon);
    });
    const scenario = $('scenario');
    if (scenario) scenario.value = initialUi.scenario;
    if (typeof updateScenarioChart === 'function') updateScenarioChart();

    const soilManual = $('soil-manual');
    if (soilManual) soilManual.checked = true;
    document.querySelectorAll('#soil-manual-fields input, #soil-manual-fields select').forEach(control => { control.value = ''; });
    if (typeof syncManualSoilFields === 'function') syncManualSoilFields();
    document.querySelectorAll('.advanced-controls').forEach(details => { details.open = false; });

    const plantQuery = $('plant-query');
    if (plantQuery) plantQuery.value = '';
    const plantHits = $('plant-hits');
    if (plantHits) plantHits.innerHTML = '';
    const plantSearch = $('plant-search');
    if (plantSearch) { plantSearch.disabled = true; plantSearch.textContent = 'Analyser la sélection'; }

    $('results')?.classList.add('hidden');
    $('result-title')?.classList.add('hidden');
    if ($('result-title')) $('result-title').textContent = '';
    if ($('results-list')) $('results-list').innerHTML = '';
    if ($('climate-summary')) $('climate-summary').innerHTML = '';
    if ($('climate-source-mini')) $('climate-source-mini').textContent = '';
    if ($('soil-source')) $('soil-source').textContent = '—';
    if ($('soil-summary')) $('soil-summary').innerHTML = '<div class="empty small-empty">Le profil de sol sera chargé avec l’analyse.</div>';
    $('uncertainty-note')?.classList.add('hidden');
    if ($('uncertainty-note')) $('uncertainty-note').innerHTML = '';
    $('trajectory')?.classList.add('hidden');
    if ($('trajectory')) $('trajectory').innerHTML = '';
    if (typeof closeDrawer === 'function') closeDrawer();
    if (typeof showWarning === 'function') showWarning([]);
    const progress = $('search-progress');
    if (progress) progress.hidden = true;
    const sort = $('result-sort');
    if (sort) sort.value = 'scientific';
    if (typeof setResultsView === 'function') setResultsView('grid');

    renderFilters(null);
    syncTopControls();
    document.dispatchEvent(new CustomEvent('climaflora:search-reset'));
    $('explorer')?.scrollIntoView({behavior:'smooth', block:'start'});
  }

  function installSubtitleGuard() {
    const subtitle = $('result-subtitle');
    if (!subtitle) return;
    new MutationObserver(restoreServerSubtitle).observe(subtitle, {childList:true, characterData:true, subtree:true});
  }

  function install() {
    cleanComparisonWording(document.body);
    new MutationObserver(mutations => {
      for (const mutation of mutations) mutation.addedNodes.forEach(cleanComparisonWording);
    }).observe(document.body, {childList:true, subtree:true});

    installPanelEvents();
    installCaptureControls();
    installSubtitleGuard();
    $('new-search')?.addEventListener('click', event => {
      event.preventDefault();
      resetSearch();
    });
    renderFilters(null);
    syncTopControls();
  }

  window.CLIMAFLORA_SEARCH_V2 = Object.freeze({
    runSearch,
    resetSearch,
    setGenusInitial,
    getState: () => ({
      life: searchV2.life,
      functions: [...searchV2.functions],
      statuses: [...searchV2.statuses],
      soilStatuses: [...searchV2.soilStatuses],
      genusInitial: searchV2.genusInitial,
      hasRun: searchV2.hasRun,
      pageSize: PAGE_SIZE
    }),
    getResultMeta: () => ({
      facets: searchV2.lastData?.facets || {},
      metrics: searchV2.lastData?.metrics || {},
      fullyLoaded: Boolean(searchV2.lastData?.fully_loaded)
    })
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
