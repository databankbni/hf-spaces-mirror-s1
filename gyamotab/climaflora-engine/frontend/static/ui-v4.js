(() => {
  'use strict';

  const apiBase = String(window.CLIMAFLORA_CONFIG?.apiBase || 'api/v1').replace(/\/$/, '');
  const lifeLabels = {
    ALL: 'Tous', TREE: 'Arbres', SHRUB: 'Arbustes', HERB: 'Herbacées',
    CLIMBER: 'Grimpantes', PALM: 'Palmiers', OTHER: 'Autres', UNKNOWN: 'Non renseigné'
  };
  const lifeIcons = {ALL:'❧', TREE:'♠', SHRUB:'♧', HERB:'✤', CLIMBER:'⌁', PALM:'♜', OTHER:'◇', UNKNOWN:'?'};
  const state = {life:'ALL', statuses:new Set(['GREEN','ORANGE','RED','UNKNOWN']), uses:new Set(), enrichment:new Map()};
  let enriching = false;
  let rerun = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function classifyLifeForm(value) {
    const v = String(value || '').trim().toLowerCase();
    if (!v) return 'UNKNOWN';
    if (/palm|palmae|palmier/.test(v)) return 'PALM';
    if (/climb|liana|vine|grimp/.test(v)) return 'CLIMBER';
    if (/shrub|bush|arbust/.test(v)) return 'SHRUB';
    if (/tree|arbores|arbre/.test(v)) return 'TREE';
    if (/herb|forb|graminoid|grass|herbac/.test(v)) return 'HERB';
    return 'OTHER';
  }

  function installLifeFormChooser() {
    const card = document.querySelector('.type-card');
    if (!card || card.querySelector('.lifeform-grid')) return;
    const title = card.querySelector('.card-title-row strong');
    if (title) title.textContent = 'Type de végétaux';
    const help = card.querySelector('.field-help');
    if (help) help.textContent = 'Filtre descriptif fondé sur les formes biologiques documentées du catalogue v1.8.';
    const functions = document.getElementById('functions');
    const grid = document.createElement('div');
    grid.className = 'lifeform-grid';
    for (const key of ['ALL','TREE','SHRUB','HERB','CLIMBER','PALM','OTHER']) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.lifeform = key;
      button.className = key === 'ALL' ? 'active' : '';
      button.innerHTML = `<span>${lifeIcons[key]}</span><strong>${lifeLabels[key]}</strong>`;
      button.onclick = () => {
        state.life = key;
        grid.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === button));
        if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) applyFilters();
      };
      grid.appendChild(button);
    }
    if (functions) {
      functions.insertAdjacentElement('beforebegin', grid);
      const details = document.createElement('details');
      details.className = 'function-filter-details';
      details.innerHTML = '<summary>＋ Filtrer aussi par fonction documentée</summary>';
      functions.parentNode.insertBefore(details, functions);
      details.appendChild(functions);
    } else {
      card.appendChild(grid);
    }
  }

  function installResultsFilters() {
    const panel = document.querySelector('.filters-panel');
    if (!panel || panel.dataset.v4 === '1') return;
    panel.dataset.v4 = '1';
    panel.innerHTML = `
      <div class="filters-head"><strong>Affiner les résultats</strong><button id="reset-v4" type="button">Réinitialiser</button></div>
      <div class="filter-block" id="status-filter-v4"><strong>Niveau d’adaptation</strong>
        <label><input type="checkbox" value="GREEN" checked> <span>Favorable</span><small data-count="GREEN">0</small></label>
        <label><input type="checkbox" value="ORANGE" checked> <span>Sous contrainte</span><small data-count="ORANGE">0</small></label>
        <label><input type="checkbox" value="RED" checked> <span>À risque</span><small data-count="RED">0</small></label>
        <label><input type="checkbox" value="UNKNOWN" checked> <span>Données limitées</span><small data-count="UNKNOWN">0</small></label>
      </div>
      <details open><summary>Usages documentés</summary><div id="use-filter-v4" class="dynamic-filter-list"><p>Aucun usage v1.8 chargé pour l’instant.</p></div></details>
      <details><summary>Type de plante</summary><div id="life-summary-v4" class="dynamic-filter-list"></div></details>
      <details><summary>Contraintes</summary><p>Les contraintes climat et sol restent visibles dans chaque fiche sans être transformées en inférences.</p></details>
      <details><summary>Autres critères</summary><p>Comparaison, favoris et projets seront ajoutés dans ClimaFlora+ sans modifier le classement.</p></details>`;
    panel.querySelectorAll('#status-filter-v4 input').forEach(input => input.onchange = () => {
      input.checked ? state.statuses.add(input.value) : state.statuses.delete(input.value);
      if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) applyFilters();
    });
    panel.querySelector('#reset-v4').onclick = () => {
      state.life = 'ALL'; state.statuses = new Set(['GREEN','ORANGE','RED','UNKNOWN']); state.uses.clear();
      document.querySelectorAll('.lifeform-grid button').forEach(b => b.classList.toggle('active', b.dataset.lifeform === 'ALL'));
      panel.querySelectorAll('#status-filter-v4 input').forEach(i => i.checked = true);
      panel.querySelectorAll('#use-filter-v4 input').forEach(i => i.checked = false);
      if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) applyFilters();
    };
  }

  async function fetchEnrichment(ids) {
    const missing = ids.filter(id => !state.enrichment.has(id));
    if (!missing.length) return;
    const params = new URLSearchParams();
    missing.slice(0, 250).forEach(id => params.append('taxon_id', id));
    const response = await fetch(`${apiBase}/plants/enrichment?${params}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`enrichment ${response.status}`);
    const payload = await response.json();
    Object.entries(payload.taxa || {}).forEach(([id, data]) => state.enrichment.set(id, data));
  }

  function cardTaxon(card) {
    return card.querySelector('[data-taxon]')?.dataset.taxon || '';
  }

  function extractStatus(card) {
    const node = card.querySelector('.plant-scores .status');
    for (const key of ['GREEN','ORANGE','RED','UNKNOWN']) if (node?.classList.contains(key)) return key;
    return 'UNKNOWN';
  }

  function decorateCard(card) {
    if (card.dataset.enriched === '1') return;
    const id = cardTaxon(card); if (!id) return;
    const data = state.enrichment.get(id); if (!data) return;
    const category = classifyLifeForm(data.life_form);
    card.dataset.lifeform = category;
    card.dataset.status = extractStatus(card);
    card.dataset.uses = (data.uses || []).map(u => u.code).join(',');

    const identity = card.querySelector('.plant-identity>div:last-child');
    const common = card.querySelector('.common');
    if (common && data.vernacular_name_fr) common.textContent = data.vernacular_name_fr;
    if (identity) {
      const badges = document.createElement('div');
      badges.className = 'descriptive-badges';
      if (data.life_form) badges.innerHTML += `<span title="Forme biologique documentée : ${esc(data.life_form)}">${esc(lifeLabels[category])}</span>`;
      (data.uses || []).slice(0,2).forEach(use => badges.innerHTML += `<span>${esc(use.label_fr || use.label_en || use.code)}</span>`);
      if (badges.children.length) identity.appendChild(badges);
    }

    const funcs = card.querySelector('.functions');
    if (funcs && (data.uses || []).length) {
      funcs.innerHTML = (data.uses || []).slice(0,4).map(use => `<span title="Usage rapporté · ${esc(use.source_id || '')}">${esc(use.label_fr || use.label_en || use.code)}</span>`).join('');
      funcs.insertAdjacentHTML('beforeend','<small>Usages rapportés : information descriptive, pas une recommandation de sécurité ou d’efficacité.</small>');
    }

    const action = card.querySelector('.trajectory-btn');
    if (action) action.textContent = 'Voir la fiche →';
    const top = card.querySelector('.plant-top');
    if (top && !top.querySelector('.future-favorite')) {
      const fav = document.createElement('button'); fav.type='button'; fav.disabled=true; fav.className='future-favorite'; fav.title='Favoris bientôt disponibles'; fav.textContent='♡'; top.appendChild(fav);
    }
    card.dataset.enriched = '1';
  }

  function rebuildDynamicFilters() {
    const cards = [...document.querySelectorAll('.plant-card[data-enriched="1"]')];
    const counts = {GREEN:0,ORANGE:0,RED:0,UNKNOWN:0};
    const lifeCounts = {};
    const useMap = new Map();
    cards.forEach(card => {
      counts[card.dataset.status || 'UNKNOWN']++;
      lifeCounts[card.dataset.lifeform || 'UNKNOWN'] = (lifeCounts[card.dataset.lifeform || 'UNKNOWN'] || 0) + 1;
      const data = state.enrichment.get(cardTaxon(card));
      (data?.uses || []).forEach(use => {
        const prev = useMap.get(use.code) || {count:0,label:use.label_fr || use.label_en || use.code}; prev.count++; useMap.set(use.code,prev);
      });
    });
    Object.entries(counts).forEach(([k,v]) => { const n=document.querySelector(`[data-count="${k}"]`); if(n)n.textContent=String(v); });
    const life = document.getElementById('life-summary-v4');
    if (life) life.innerHTML = Object.entries(lifeCounts).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div><span>${esc(lifeLabels[k] || k)}</span><small>${v}</small></div>`).join('') || '<p>Aucune forme biologique chargée.</p>';
    const use = document.getElementById('use-filter-v4');
    if (use) {
      use.innerHTML = [...useMap.entries()].sort((a,b)=>b[1].count-a[1].count).slice(0,10).map(([code,item])=>`<label><input type="checkbox" value="${esc(code)}" ${state.uses.has(code)?'checked':''}> <span>${esc(item.label)}</span><small>${item.count}</small></label>`).join('') || '<p>Aucun usage v1.8 sur les résultats chargés.</p>';
      use.querySelectorAll('input').forEach(input => input.onchange = () => {input.checked?state.uses.add(input.value):state.uses.delete(input.value);if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) applyFilters();});
    }
  }

  function applyFilters() {
    const cards = [...document.querySelectorAll('.plant-card')];
    let shown = 0;
    cards.forEach(card => {
      const lifeOk = state.life === 'ALL' || card.dataset.lifeform === state.life;
      const statusOk = state.statuses.has(card.dataset.status || 'UNKNOWN');
      const useCodes = new Set(String(card.dataset.uses || '').split(',').filter(Boolean));
      const useOk = !state.uses.size || [...state.uses].every(code => useCodes.has(code));
      const visible = lifeOk && statusOk && useOk;
      card.hidden = !visible; if (visible) shown++;
    });
    const subtitle = document.getElementById('result-subtitle');
    if (subtitle && cards.length) {
      const original = subtitle.dataset.original || subtitle.textContent; subtitle.dataset.original = original;
      subtitle.textContent = `${shown} résultat${shown>1?'s':''} visible${shown>1?'s':''} sur ${cards.length} chargé${cards.length>1?'s':''} · ${original}`;
    }
  }

  async function enrichVisibleCards() {
    if (enriching) {rerun=true;return;} enriching=true;
    try {
      const cards = [...document.querySelectorAll('.plant-card')];
      const ids = cards.map(cardTaxon).filter(Boolean);
      if (!ids.length) return;
      await fetchEnrichment(ids);
      cards.forEach(decorateCard);
      if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) rebuildDynamicFilters();
      if (!window.CLIMAFLORA_SERVER_SEARCH_ACTIVE) applyFilters();
      document.body.classList.add('v18-enriched');
    } catch (error) {
      console.warn('ClimaFlora descriptive enrichment unavailable:', error);
    } finally {
      enriching=false; if(rerun){rerun=false;setTimeout(enrichVisibleCards,50);}
    }
  }

  function observeResults() {
    const root = document.getElementById('results-list'); if (!root) return;
    new MutationObserver(() => setTimeout(enrichVisibleCards, 20)).observe(root, {childList:true,subtree:true});
  }

  function finishLayout() {
    installLifeFormChooser(); observeResults();
    const heading = document.querySelector('.progress-step:last-child'); if (heading) heading.lastChild.textContent = 'Type de végétaux';
    const trust = document.querySelector('.trust-strip article:last-child p'); if (trust) trust.textContent = 'Usages documentés séparés du score scientifique.';
    setTimeout(enrichVisibleCards, 100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', finishLayout); else finishLayout();
})();
