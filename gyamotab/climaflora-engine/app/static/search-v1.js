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

  const searchV1 = {
    life: 'ALL',
    functions: new Set(),
    statuses: new Set(STATUS_KEYS),
    soilStatuses: new Set(STATUS_KEYS),
    offset: 0,
    pageSize: 50,
    hasRun: false,
    running: false,
    abortController: null,
    lastData: null,
    serverSubtitle: ''
  };
  state.searchV1 = searchV1;

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
      button.classList.toggle('active', button.dataset.lifeform === searchV1.life);
    });
    document.querySelectorAll('#functions button').forEach(button => {
      const value = button.dataset.value || '';
      const active = value ? searchV1.functions.has(value) : searchV1.functions.size === 0;
      button.classList.toggle('active', active);
    });
  }

  function activeChips() {
    const chips = [];
    const fnLabels = functionLabels();
    if (searchV1.life !== 'ALL') {
      chips.push({dimension: 'life', value: searchV1.life, label: LIFE_LABELS[searchV1.life] || searchV1.life});
    }
    [...searchV1.functions].forEach(value => {
      chips.push({dimension: 'function', value, label: fnLabels.get(value) || value});
    });
    if (searchV1.statuses.size < STATUS_KEYS.length) {
      [...searchV1.statuses].forEach(value => {
        chips.push({dimension: 'status', value, label: `Climat · ${STATUS_LABELS[value]}`});
      });
    }
    if (searchV1.soilStatuses.size < STATUS_KEYS.length) {
      [...searchV1.soilStatuses].forEach(value => {
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
    panel.innerHTML = `
      <div class="filters-head"><strong>Affiner les résultats</strong><button id="reset-server-filters" type="button">Réinitialiser</button></div>
      <div class="active-filter-zone">
        <div class="active-filter-title">Filtres actifs</div>
        <div class="active-filter-chips">${chips.length ? chips.map(chip => `<button type="button" class="active-filter-chip" data-remove-dimension="${esc(chip.dimension)}" data-remove-value="${esc(chip.value)}">${esc(chip.label)} <span aria-hidden="true">×</span></button>`).join('') : '<span class="no-active-filter">Aucun filtre restrictif</span>'}</div>
      </div>
      <details class="server-filter-group" data-dimension="climate" ${open.has('climate') || !data ? 'open' : ''}>
        <summary><span>Niveau d’adaptation</span><small>${nf.format(Number(metrics.evaluated_candidates || 0))}</small></summary>
        <div class="server-filter-options">${STATUS_KEYS.map(key => facetRow({dimension:'status', value:key, label:STATUS_LABELS[key], count:facets.climate_status?.[key], checked:searchV1.statuses.has(key)})).join('')}</div>
      </details>
      <details class="server-filter-group" data-dimension="function" ${open.has('function') ? 'open' : ''}>
        <summary><span>Fonctions documentées</span><small>${functionEntries.length}</small></summary>
        <div class="server-filter-options">${functionEntries.length ? functionEntries.map(([key,count]) => facetRow({dimension:'function', value:key, label:fnLabels.get(key) || key, count, checked:searchV1.functions.has(key)})).join('') : '<p class="facet-empty">Aucune fonction documentée dans ce sous-ensemble.</p>'}</div>
      </details>
      <details class="server-filter-group" data-dimension="life" ${open.has('life') ? 'open' : ''}>
        <summary><span>Type de végétal</span><small>${nf.format(Number(metrics.catalog_total || 0))}</small></summary>
        <div class="server-filter-options">
          ${facetRow({dimension:'life', value:'ALL', label:'Tous', count:metrics.catalog_total, checked:searchV1.life === 'ALL', type:'radio'})}
          ${LIFE_KEYS.filter(key => key !== 'ALL').map(key => facetRow({dimension:'life', value:key, label:LIFE_LABELS[key], count:facets.life_form?.[key], checked:searchV1.life === key, type:'radio'})).join('')}
        </div>
      </details>
      <details class="server-filter-group" data-dimension="soil" ${open.has('soil') ? 'open' : ''}>
        <summary><span>Compatibilité du sol</span><small>${nf.format(Number(metrics.evaluated_candidates || 0))}</small></summary>
        <div class="server-filter-options">${STATUS_KEYS.map(key => facetRow({dimension:'soil-status', value:key, label:STATUS_LABELS[key], count:facets.soil_status?.[key], checked:searchV1.soilStatuses.has(key)})).join('')}</div>
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
    searchV1.life = 'ALL';
    searchV1.functions.clear();
    searchV1.statuses = new Set(STATUS_KEYS);
    searchV1.soilStatuses = new Set(STATUS_KEYS);
    syncTopControls();
    if (searchV1.hasRun) runSearch(0);
    else renderFilters(searchV1.lastData);
  }

  function removeChip(dimension, value) {
    if (dimension === 'life') searchV1.life = 'ALL';
    if (dimension === 'function') searchV1.functions.delete(value);
    if (dimension === 'status') {
      if (searchV1.statuses.size <= 1) searchV1.statuses = new Set(STATUS_KEYS);
      else searchV1.statuses.delete(value);
    }
    if (dimension === 'soil-status') {
      if (searchV1.soilStatuses.size <= 1) searchV1.soilStatuses = new Set(STATUS_KEYS);
      else searchV1.soilStatuses.delete(value);
    }
    syncTopControls();
    if (searchV1.hasRun) runSearch(0);
    else renderFilters(searchV1.lastData);
  }

  function searchParams(offset) {
    const params = new URLSearchParams({
      lat: $('lat').value,
      lon: $('lon').value,
      horizon: state.horizon,
      scenario: state.scenario,
      life_form: searchV1.life,
      offset: String(offset),
      limit: String(searchV1.pageSize)
    });
    [...searchV1.functions].sort().forEach(value => params.append('function', value));
    if (searchV1.statuses.size < STATUS_KEYS.length) {
      [...searchV1.statuses].forEach(value => params.append('status', value));
    }
    if (searchV1.soilStatuses.size < STATUS_KEYS.length) {
      [...searchV1.soilStatuses].forEach(value => params.append('soil_status', value));
    }
    appendSoilParams(params);
    return params;
  }

  function paginationHtml(data) {
    const p = data.pagination || {};
    const total = Number(data.metrics?.total_results || 0);
    if (!total) return '';
    const start = Number(p.offset || 0) + 1;
    const end = Number(p.offset || 0) + Number(p.returned || 0);
    const previousOffset = Math.max(0, Number(p.offset || 0) - Number(p.limit || searchV1.pageSize));
    const nextOffset = Number(p.offset || 0) + Number(p.limit || searchV1.pageSize);
    return `<nav class="server-pagination" aria-label="Pagination des résultats">
      <button type="button" class="secondary" data-page-offset="${previousOffset}" ${p.has_previous ? '' : 'disabled'}>← Précédent</button>
      <span>${nf.format(start)}–${nf.format(end)} sur ${nf.format(total)}</span>
      <button type="button" class="secondary" data-page-offset="${nextOffset}" ${p.has_next ? '' : 'disabled'}>Suivant →</button>
    </nav>`;
  }

  function restoreServerSubtitle() {
    const subtitle = $('result-subtitle');
    if (!subtitle || !searchV1.serverSubtitle) return;
    subtitle.dataset.original = searchV1.serverSubtitle;
    if (subtitle.textContent !== searchV1.serverSubtitle) subtitle.textContent = searchV1.serverSubtitle;
  }

  async function runSearch(offset = 0) {
    if (!state.scientificReady) return loadReadiness();
    if (searchV1.abortController) searchV1.abortController.abort();
    const controller = new AbortController();
    searchV1.abortController = controller;
    searchV1.running = true;
    searchV1.offset = Math.max(0, Number(offset) || 0);
    const btn = $('search');
    btn.classList.add('loading');
    btn.textContent = 'Analyse du catalogue…';
    $('trajectory').classList.add('hidden');
    try {
      const response = await fetch(`${apiUrl('recommendations/search')}?${searchParams(searchV1.offset)}`, {signal: controller.signal});
      if (!response.ok) throw new Error(`API ${response.status}`);
      const data = await response.json();
      searchV1.lastData = data;
      searchV1.hasRun = true;
      const shown = data.recommendations?.length || 0;
      const metrics = data.metrics || {};
      const page = data.pagination || {};
      const start = shown ? Number(page.offset || 0) + 1 : 0;
      const end = shown ? Number(page.offset || 0) + shown : 0;
      $('result-title').textContent = `${Number(data.climate.latitude).toFixed(3)}, ${Number(data.climate.longitude).toFixed(3)} · ${state.horizon}`;
      searchV1.serverSubtitle = `${nf.format(Number(metrics.catalog_total || 0))} taxons au catalogue · ${nf.format(Number(metrics.after_type || 0))} après type · ${nf.format(Number(metrics.after_function || 0))} analysés · ${nf.format(Number(metrics.total_results || 0))} résultats · ${nf.format(start)}–${nf.format(end)} affichés`;
      restoreServerSubtitle();
      climateSummary(data.climate);
      soilSummary(data.soil);
      const cards = shown ? data.recommendations.map(plantCard).join('') : '<div class="empty">Aucun taxon ne correspond à ces filtres.</div>';
      $('results-list').innerHTML = cards + paginationHtml(data);
      renderFilters(data);
      syncTopControls();
      showWarning(data.warnings || []);
      cleanComparisonWording($('results-list'));
      setTimeout(restoreServerSubtitle, 40);
      setTimeout(restoreServerSubtitle, 180);
    } catch (error) {
      if (error.name !== 'AbortError') {
        $('results-list').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`;
      }
    } finally {
      if (searchV1.abortController === controller) {
        searchV1.running = false;
        btn.classList.remove('loading');
        btn.textContent = 'Lancer la recherche →';
      }
    }
  }

  function installPanelEvents() {
    const panel = document.querySelector('.filters-panel');
    if (!panel || panel.dataset.serverFacets === '1') return;
    panel.dataset.serverFacets = '1';
    panel.addEventListener('change', event => {
      const input = event.target.closest('[data-facet-dimension]');
      if (!input) return;
      const dimension = input.dataset.facetDimension;
      const value = input.value;
      let changed = true;
      if (dimension === 'life') searchV1.life = value;
      if (dimension === 'function') input.checked ? searchV1.functions.add(value) : searchV1.functions.delete(value);
      if (dimension === 'status') changed = setStatusValue(searchV1.statuses, value, input.checked, input);
      if (dimension === 'soil-status') changed = setStatusValue(searchV1.soilStatuses, value, input.checked, input);
      syncTopControls();
      if (changed && searchV1.hasRun) runSearch(0);
      else renderFilters(searchV1.lastData);
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
      const life = event.target.closest('.lifeform-grid button');
      if (life) {
        event.preventDefault();
        event.stopImmediatePropagation();
        searchV1.life = life.dataset.lifeform || 'ALL';
        syncTopControls();
        renderFilters(searchV1.lastData);
        if (searchV1.hasRun) runSearch(0);
        return;
      }
      const fn = event.target.closest('#functions button');
      if (fn) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const value = fn.dataset.value || '';
        searchV1.functions.clear();
        if (value) searchV1.functions.add(value);
        syncTopControls();
        renderFilters(searchV1.lastData);
        if (searchV1.hasRun) runSearch(0);
      }
    }, true);
  }

  function installPagination() {
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-page-offset]');
      if (!button || button.disabled) return;
      runSearch(Number(button.dataset.pageOffset || 0));
      document.getElementById('results')?.scrollIntoView({behavior:'smooth', block:'start'});
    });
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

    const btn = $('search');
    if (btn) btn.onclick = event => { event.preventDefault(); runSearch(0); };
    installPanelEvents();
    installCaptureControls();
    installPagination();
    installSubtitleGuard();
    renderFilters(null);
    syncTopControls();

    $('scenario')?.addEventListener('change', () => { if (searchV1.hasRun) setTimeout(() => runSearch(0), 0); });
    document.getElementById('horizons')?.addEventListener('click', event => {
      if (event.target.closest('button') && searchV1.hasRun) setTimeout(() => runSearch(0), 0);
    });
  }

  install();
})();
