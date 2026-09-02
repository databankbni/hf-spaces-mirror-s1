(() => {
  'use strict';

  const ui = {
    alpha: 'ALL',
    regrouping: false,
    panelUpdating: false
  };

  const alphaCollator = new Intl.Collator('fr', {sensitivity: 'base'});

  function genusFromScientificName(name) {
    const parts = String(name || '').trim().replace(/^×\s*/, '').split(/\s+/).filter(Boolean);
    return parts[0] || 'Genre non renseigné';
  }

  function cardScientificName(card) {
    return card?.querySelector('.plant-name em')?.textContent?.trim()
      || card?.querySelector('.plant-name')?.textContent?.trim()
      || '';
  }

  function normalizeWarningText(text) {
    let value = String(text || '');
    value = value.replace(
      /Le pixel exact était NoData pour certaines propriétés\s*;\s*cellule SoilGrids valide la plus proche utilisée\s*\(jusqu[’']à\s*(\d+)\s*m\)\./gi,
      "Certaines propriétés du sol du pixel exact n'étaient pas renseignées; le pixel renseigné le plus proche est utilisé (jusqu’à $1 m)."
    );
    value = value.replace(
      /SoilGrids est un modèle global à 250\s*m\s*:?\s*le profil estimé ne remplace pas une analyse de sol de parcelle\.?/gi,
      ''
    );
    value = value.replace(
      /Enveloppe climatique régionale\s+WCVP\/TDWG-3\s*:\s*proxy de niche réalisée,?\s*confiance plafonnée à C\.?/gi,
      ''
    );
    return value.replace(/\s{2,}/g, ' ').trim();
  }

  function normalizeWarning() {
    const warning = document.getElementById('warning');
    if (!warning) return;
    const normalized = normalizeWarningText(warning.textContent);
    if (normalized !== warning.textContent.trim()) warning.textContent = normalized;
    warning.classList.toggle('hidden', !normalized);
  }

  function makeGenusGroup(genus, cards) {
    const details = document.createElement('details');
    details.className = 'genus-group';
    details.dataset.genus = genus;

    const summary = document.createElement('summary');
    const name = document.createElement('span');
    name.className = 'genus-summary-name';
    const em = document.createElement('em');
    em.textContent = genus;
    name.appendChild(em);

    const meta = document.createElement('span');
    meta.className = 'genus-summary-meta';
    const count = document.createElement('span');
    count.dataset.visibleCount = '';
    count.textContent = String(cards.length);
    meta.append(count, document.createTextNode(` plante${cards.length > 1 ? 's' : ''}`));

    const chevron = document.createElement('span');
    chevron.className = 'genus-chevron';
    chevron.textContent = '⌄';
    summary.append(name, meta, chevron);

    const body = document.createElement('div');
    body.className = 'genus-cards';
    cards.forEach(card => body.appendChild(card));

    details.append(summary, body);
    return details;
  }

  function currentGroups() {
    return [...document.querySelectorAll('#results-list > .genus-group')];
  }

  function sortExistingGroups() {
    const list = document.getElementById('results-list');
    if (!list) return;
    const groups = currentGroups();
    if (groups.length < 2) return;
    const sorted = [...groups].sort((a, b) => alphaCollator.compare(a.dataset.genus || '', b.dataset.genus || ''));
    if (sorted.every((group, index) => group === groups[index])) return;
    ui.regrouping = true;
    const pagination = list.querySelector(':scope > .server-pagination');
    sorted.forEach(group => list.insertBefore(group, pagination || null));
    ui.regrouping = false;
  }

  function groupResultsByGenus() {
    if (ui.regrouping) return;
    const list = document.getElementById('results-list');
    if (!list) return;

    const directCards = [...list.querySelectorAll(':scope > .plant-card')];
    if (!directCards.length) {
      sortExistingGroups();
      ensureAlphabetFilter();
      applyAlphaFilter();
      return;
    }

    const groups = new Map();
    for (const card of directCards) {
      const genus = genusFromScientificName(cardScientificName(card));
      if (!groups.has(genus)) groups.set(genus, []);
      groups.get(genus).push(card);
    }

    const pagination = list.querySelector(':scope > .server-pagination');
    const others = [...list.children].filter(node => !directCards.includes(node) && node !== pagination);
    const entries = [...groups.entries()].sort((a, b) => alphaCollator.compare(a[0], b[0]));
    const fragment = document.createDocumentFragment();
    entries.forEach(([genus, cards]) => fragment.appendChild(makeGenusGroup(genus, cards)));
    others.forEach(node => fragment.appendChild(node));
    if (pagination) fragment.appendChild(pagination);

    ui.regrouping = true;
    list.replaceChildren(fragment);
    ui.regrouping = false;

    ensureAlphabetFilter();
    applyAlphaFilter();
  }

  function alphabetCounts() {
    // Preferred source: server facet computed on the full matched population before pagination.
    const meta = window.CLIMAFLORA_SEARCH_V2?.getResultMeta?.() || {};
    const server = meta.facets?.genus_initial || meta.facets?.alphabet || {};
    const entries = Object.entries(server).filter(([letter, count]) => /^[A-Z]$/.test(String(letter)) && Number(count) > 0);
    if (entries.length) {
      return {
        counts: new Map(entries.map(([letter, count]) => [String(letter).toLocaleUpperCase('fr'), Number(count)])),
        total: Number(server.ALL || meta.metrics?.total_results || 0),
        serverWide: true
      };
    }

    // Older API fallback: loaded-card counts are exact only when all results are already loaded.
    const counts = new Map();
    currentGroups().forEach(group => {
      const letter = String(group.dataset.genus || '').trim().charAt(0).toLocaleUpperCase('fr');
      const count = group.querySelectorAll('.plant-card').length;
      if (letter) counts.set(letter, (counts.get(letter) || 0) + count);
    });
    return {
      counts,
      total: meta.fullyLoaded ? [...counts.values()].reduce((sum, count) => sum + count, 0) : 0,
      serverWide: false
    };
  }

  function syncAlphaChip() {
    const chips = document.querySelector('.filters-panel .active-filter-chips');
    if (!chips) return;
    chips.querySelector('.cf-alpha-chip')?.remove();
    const empty = chips.querySelector('.no-active-filter');
    if (ui.alpha !== 'ALL') {
      empty?.remove();
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'active-filter-chip cf-alpha-chip';
      chip.dataset.cfClearAlpha = '1';
      chip.innerHTML = `Genre · ${String(ui.alpha).replace(/[&<>"']/g, '')} <span aria-hidden="true">×</span>`;
      chips.appendChild(chip);
    } else if (!chips.querySelector('.active-filter-chip') && !empty) {
      const span = document.createElement('span');
      span.className = 'no-active-filter';
      span.textContent = 'Aucun filtre restrictif';
      chips.appendChild(span);
    }
  }

  function ensureAlphabetFilter() {
    if (ui.panelUpdating) return;
    const panel = document.querySelector('.filters-panel');
    if (!panel) return;
    const alphaData = alphabetCounts();
    const counts = alphaData.counts;
    const serverState = window.CLIMAFLORA_SEARCH_V2?.getState?.() || {};
    if (serverState.genusInitial) ui.alpha = serverState.genusInitial;
    const letters = [...counts.keys()].sort((a, b) => alphaCollator.compare(a, b));
    if (ui.alpha !== 'ALL' && !counts.has(ui.alpha)) ui.alpha = 'ALL';

    let group = panel.querySelector('.cf-alpha-group');
    if (!group) {
      group = document.createElement('details');
      group.open = true;
      group.className = 'server-filter-group cf-alpha-group';
      group.dataset.dimension = 'alphabet';
      const activeZone = panel.querySelector('.active-filter-zone');
      if (activeZone) activeZone.insertAdjacentElement('afterend', group);
      else panel.querySelector('.filters-head')?.insertAdjacentElement('afterend', group);
    }

    ui.panelUpdating = true;
    group.innerHTML = '';
    const summary = document.createElement('summary');
    const label = document.createElement('span');
    label.textContent = 'Genres par lettre';
    summary.append(label);

    const alpha = document.createElement('div');
    alpha.className = 'alpha-filter cf-alpha-filter';
    const buttons = document.createElement('div');
    buttons.className = 'alpha-buttons';

    const all = document.createElement('button');
    all.type = 'button';
    all.dataset.cfAlpha = 'ALL';
    all.appendChild(document.createTextNode('Tous'));
    if (alphaData.total > 0) {
      const totalSmall = document.createElement('small');
      totalSmall.textContent = String(alphaData.total);
      all.appendChild(totalSmall);
    }
    buttons.appendChild(all);

    letters.forEach(letter => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.cfAlpha = letter;
      const labelText = document.createTextNode(letter);
      const small = document.createElement('small');
      small.textContent = String(counts.get(letter));
      button.append(labelText, small);
      buttons.appendChild(button);
    });

    alpha.appendChild(buttons);
    group.append(summary, alpha);
    ui.panelUpdating = false;
    syncAlphaButtons();
    syncAlphaChip();
  }

  function syncAlphaButtons() {
    document.querySelectorAll('[data-cf-alpha]').forEach(button => {
      button.classList.toggle('active', button.dataset.cfAlpha === ui.alpha);
    });
  }

  function applyAlphaFilter() {
    currentGroups().forEach(group => {
      const letter = String(group.dataset.genus || '').trim().charAt(0).toLocaleUpperCase('fr');
      group.hidden = ui.alpha !== 'ALL' && letter !== ui.alpha;
      group.open = false;
    });
    syncAlphaButtons();
    syncAlphaChip();
  }

  function revealResultsIfNeeded() {
    const list = document.getElementById('results-list');
    if (!list || !list.children.length) return;
    document.getElementById('results')?.classList.remove('hidden');
    document.getElementById('result-title')?.classList.remove('hidden');
  }

  function installObservers() {
    const warning = document.getElementById('warning');
    if (warning) {
      new MutationObserver(normalizeWarning).observe(warning, {childList: true, characterData: true, subtree: true});
      normalizeWarning();
    }

    const list = document.getElementById('results-list');
    if (list) {
      new MutationObserver(() => {
        if (ui.regrouping) return;
        revealResultsIfNeeded();
        groupResultsByGenus();
      }).observe(list, {childList: true});
      revealResultsIfNeeded();
      groupResultsByGenus();
    }

    const panel = document.querySelector('.filters-panel');
    if (panel) {
      new MutationObserver(() => {
        if (ui.panelUpdating) return;
        ensureAlphabetFilter();
        syncAlphaChip();
      }).observe(panel, {childList: true, subtree: false});
      ensureAlphabetFilter();
    }
  }

  document.addEventListener('click', event => {
    const alpha = event.target.closest('[data-cf-alpha]');
    if (alpha) {
      event.preventDefault();
      event.stopImmediatePropagation();
      ui.alpha = alpha.dataset.cfAlpha || 'ALL';
      syncAlphaButtons();
      syncAlphaChip();
      const meta = window.CLIMAFLORA_SEARCH_V2?.getResultMeta?.() || {};
      const hasServerFacet = Boolean(meta.facets?.genus_initial || meta.facets?.alphabet);
      if (hasServerFacet && window.CLIMAFLORA_SEARCH_V2?.setGenusInitial) {
        window.CLIMAFLORA_SEARCH_V2.setGenusInitial(ui.alpha);
      } else {
        applyAlphaFilter();
      }
      return;
    }
    const clear = event.target.closest('[data-cf-clear-alpha]');
    if (clear) {
      event.preventDefault();
      event.stopImmediatePropagation();
      ui.alpha = 'ALL';
      const meta = window.CLIMAFLORA_SEARCH_V2?.getResultMeta?.() || {};
      const hasServerFacet = Boolean(meta.facets?.genus_initial || meta.facets?.alphabet);
      if (hasServerFacet && window.CLIMAFLORA_SEARCH_V2?.setGenusInitial) {
        window.CLIMAFLORA_SEARCH_V2.setGenusInitial('ALL');
      } else {
        applyAlphaFilter();
      }
    }
  }, true);

  document.addEventListener('climaflora:search-reset', () => {
    ui.alpha = 'ALL';
    syncAlphaButtons();
    syncAlphaChip();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installObservers);
  else installObservers();
})();
