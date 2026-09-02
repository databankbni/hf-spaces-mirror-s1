const state = {
  horizon: '2050', scenario: 'MEDIUM', fn: '', marker: null, map: null, meta: null, mode: 'explore',
  scientificReady: false, readiness: null, recommendationLimit: 50, recommendationStep: 50, recommendationMax: 1000, viewMode: 'grid', sortMode: 'scientific', lastRecommendations: [], lastEvaluatedCandidates: 0, lastMethodVersion: '', selectedPlant: null, plantSearchTimer: null, trajectoryCache: new Map(), trajectoryPending: new Map(), enrichmentCache: new Map()
};
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const API_CANDIDATES = [
  'https://gyamotab-climaflora-engine.hf.space/api/v1',
  `${window.location.origin}/climaflora/api/v1`,
  `${window.location.origin}/api/v1`
];
let apiBase = API_CANDIDATES[0];
window.CLIMAFLORA_RUNTIME = { apiBase, apiCandidates: [...API_CANDIDATES] };
const apiUrl = (path) => `${apiBase}/${String(path).replace(/^\/+/, '')}`;

async function fetchWithTimeout(url, options={}, timeoutMs=10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal, credentials: 'omit'});
  } finally {
    clearTimeout(timer);
  }
}

async function resolveApiBase() {
  const failures = [];
  for (const candidate of API_CANDIDATES) {
    try {
      const response = await fetchWithTimeout(`${candidate}/health?probe=${Date.now()}`, {cache:'no-store'}, 30000);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload?.status !== 'ok') throw new Error('health status != ok');
      apiBase = candidate.replace(/\/$/, '');
      window.CLIMAFLORA_RUNTIME.apiBase = apiBase;
      document.documentElement.dataset.apiReady = 'true';
      return apiBase;
    } catch (error) {
      failures.push(`${candidate}: ${error?.name === 'AbortError' ? 'timeout' : error.message}`);
    }
  }
  document.documentElement.dataset.apiReady = 'false';
  throw new Error(`API ClimaFlora indisponible. ${failures.join(' | ')}`);
}

function initMap() {
  const target = $('map');
  if (!target || typeof window.L === 'undefined' || state.map) return;
  const {lat, lon} = currentCoords();
  state.map = L.map(target, {worldCopyJump:true, zoomControl:true}).setView([lat, lon], 9);
  state.tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(state.map);
  state.marker = L.circleMarker([lat, lon], {
    radius: 7, weight: 2, fillOpacity: .85, color: '#1f6d35', fillColor: '#1f6d35'
  }).addTo(state.map);
  state.map.on('click', e => setPoint(e.latlng.lat, e.latlng.lng));
  setTimeout(() => state.map?.invalidateSize(), 50);
}

const citySearchState = {
  timer: null,
  controller: null,
  activeIndex: -1,
  results: [],
  cache: new Map()
};

function cityResultLabel(feature) {
  const p = feature?.properties || {};
  const parts = [];
  const push = value => {
    const text = String(value || '').trim();
    if (text && !parts.some(existing => existing.toLocaleLowerCase('fr') === text.toLocaleLowerCase('fr'))) parts.push(text);
  };
  push(p.name);
  push(p.city || p.locality || p.district);
  push(p.state);
  push(p.country);
  return parts.join(', ') || 'Lieu sans nom';
}

function hideCitySuggestions() {
  const root = $('city-suggestions');
  const input = $('city-search');
  if (root) {
    root.classList.add('hidden');
    root.innerHTML = '';
  }
  if (input) input.setAttribute('aria-expanded', 'false');
  citySearchState.activeIndex = -1;
  citySearchState.results = [];
}

function renderCitySuggestions(features, query) {
  const root = $('city-suggestions');
  const input = $('city-search');
  if (!root || !input) return;
  citySearchState.results = features;
  citySearchState.activeIndex = -1;
  if (!features.length) {
    root.innerHTML = `<div class="city-suggestion-empty">Aucune adresse trouvée pour « ${esc(query)} ».</div>`;
    root.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
    return;
  }
  root.innerHTML = features.map((feature, index) => {
    const coords = feature?.geometry?.coordinates || [];
    const lon = Number(coords[0]), lat = Number(coords[1]);
    return `<button class="city-suggestion" data-city-index="${index}" type="button" role="option">
      <span class="city-suggestion-name">${esc(cityResultLabel(feature))}</span>
      <small>${Number.isFinite(lat) && Number.isFinite(lon) ? `${lat.toFixed(3)}, ${lon.toFixed(3)}` : ''}</small>
    </button>`;
  }).join('');
  root.classList.remove('hidden');
  input.setAttribute('aria-expanded', 'true');
  root.querySelectorAll('[data-city-index]').forEach(button => {
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => selectCitySuggestion(Number(button.dataset.cityIndex)));
  });
}

function selectCitySuggestion(index) {
  const feature = citySearchState.results[index];
  if (!feature) return;
  const coords = feature?.geometry?.coordinates || [];
  const lon = Number(coords[0]), lat = Number(coords[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  const input = $('city-search');
  if (input) input.value = cityResultLabel(feature);
  setPoint(lat, lon, true);
  if (state.map) state.map.setView([lat, lon], 11);
  hideCitySuggestions();
  showWarning([]);
}

async function searchCities(query) {
  const q = String(query || '').trim();
  if (q.length < 3) {
    hideCitySuggestions();
    return;
  }
  const cacheKey = q.toLocaleLowerCase('fr');
  if (citySearchState.cache.has(cacheKey)) {
    renderCitySuggestions(citySearchState.cache.get(cacheKey), q);
    return;
  }
  if (citySearchState.controller) citySearchState.controller.abort();
  citySearchState.controller = new AbortController();
  const {lat, lon} = currentCoords();
  const params = new URLSearchParams({
    q,
    limit: '7',
    lang: 'fr',
    lat: String(lat),
    lon: String(lon),
    zoom: '8'
  });
  try {
    const response = await fetch(`https://photon.komoot.io/api/?${params}`, {
      signal: citySearchState.controller.signal,
      cache: 'no-store',
      headers: {'Accept': 'application/json'}
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const features = (payload?.features || []).filter(feature => {
      const coords = feature?.geometry?.coordinates || [];
      return Number.isFinite(Number(coords[0])) && Number.isFinite(Number(coords[1]));
    }).slice(0, 7);
    citySearchState.cache.set(cacheKey, features);
    renderCitySuggestions(features, q);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    const root = $('city-suggestions');
    const input = $('city-search');
    if (root && input) {
      root.innerHTML = '<div class="city-suggestion-empty">Recherche d’adresse momentanément indisponible. La carte et les coordonnées restent utilisables.</div>';
      root.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }
  }
}

function initCitySearch() {
  const input = $('city-search');
  const root = $('city-suggestions');
  if (!input || !root) return;
  input.addEventListener('input', () => {
    clearTimeout(citySearchState.timer);
    const query = input.value;
    citySearchState.timer = setTimeout(() => searchCities(query), 350);
  });
  input.addEventListener('keydown', event => {
    const options = [...root.querySelectorAll('[data-city-index]')];
    if (!options.length) {
      if (event.key === 'Escape') hideCitySuggestions();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      citySearchState.activeIndex = (citySearchState.activeIndex + direction + options.length) % options.length;
      options.forEach((option, index) => {
        const active = index === citySearchState.activeIndex;
        option.classList.toggle('active', active);
        option.setAttribute('aria-selected', String(active));
      });
      options[citySearchState.activeIndex]?.scrollIntoView({block:'nearest'});
    } else if (event.key === 'Enter' && citySearchState.activeIndex >= 0) {
      event.preventDefault();
      selectCitySuggestion(citySearchState.activeIndex);
    } else if (event.key === 'Escape') {
      hideCitySuggestions();
    }
  });
  input.addEventListener('focus', () => {
    if (input.value.trim().length >= 3 && citySearchState.results.length) {
      root.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.city-search-wrap')) hideCitySuggestions();
  });
}

const wikipediaUrl = (scientificName) => `https://fr.wikipedia.org/wiki/Special:Search?search=${encodeURIComponent(String(scientificName || ''))}&go=Go`;
const powoSearchUrl = (scientificName) => `https://powo.science.kew.org/results?q=${encodeURIComponent(String(scientificName || ''))}`;
const qwantUrl = (scientificName) => `https://www.qwant.com/?q=${encodeURIComponent(String(scientificName || ''))}`;

function setScientificAvailability(ready, readiness=null) {
  state.scientificReady = Boolean(ready); state.readiness = readiness;
  const search = $('search'); const plantSearch = $('plant-search');
  search.disabled = !state.scientificReady; plantSearch.disabled = !state.scientificReady || !state.selectedPlant;
  if (state.scientificReady) {
    search.innerHTML = 'Trouver les plantes <span>→</span>';
    plantSearch.textContent = 'Analyser la sélection';
    showWarning([]);
    return;
  }
  const phase = readiness?.master?.phase || 'initialisation';
  search.textContent = 'Moteur scientifique en préparation';
  plantSearch.textContent = 'Moteur scientifique en préparation';
  showWarning([`Moteur scientifique en préparation (${phase}).`]);
}

async function loadReadiness() {
  try {
    const response = await fetch(apiUrl('readiness'), {cache: 'no-store'}); if (!response.ok) throw new Error(`readiness ${response.status}`);
    const readiness = await response.json(); setScientificAvailability(Boolean(readiness.ready && readiness.scientific_ready), readiness);
  } catch (error) { setScientificAvailability(false, null); showWarning([`Le moteur scientifique ne répond pas encore (${error.message}).`]); }
}

function statusLabel(status) { return {GREEN:'Favorable', ORANGE:'Sous contrainte', RED:'À risque', UNKNOWN:'Inconnu'}[status] || status; }
function scenarioLabel(scenario) {
  return {
    LOW: 'Faible · SSP1-2.6',
    MEDIUM: 'Intermédiaire · SSP3-7.0',
    HIGH: 'Élevé · SSP5-8.5'
  }[String(scenario || '').toUpperCase()] || String(scenario || '—');
}

function lifeFormLabel(value) {
  const raw = String(value || '').trim();
  const v = raw.toLowerCase();
  if (!v) return '';
  if (/liana|climb|vine|grimp/.test(v)) return 'Liane / grimpante';
  if (/palm|palmae|palmier/.test(v)) return 'Palmier';
  if (/shrub|bush|arbust/.test(v)) return 'Arbuste';
  if (/tree|arbores|arbre/.test(v)) return 'Arbre';
  if (/herb|forb|graminoid|grass|herbac/.test(v)) return 'Herbacée';
  if (/succulent/.test(v)) return 'Succulente';
  if (/epiphyt/.test(v)) return 'Épiphyte';
  if (/aquatic|hydroph/.test(v)) return 'Aquatique';
  return raw;
}
function metric(label, value, unit='') { return `<div class="metric"><div class="v">${value == null ? '—' : esc(value)}${value == null ? '' : unit}</div><div class="k">${esc(label)}</div></div>`; }
function currentCoords() { return {lat: Number($('lat').value), lon: Number($('lon').value)}; }
function setPoint(lat, lon, pan=false) {
  lat = Math.max(-90, Math.min(90, Number(lat))); lon = Math.max(-180, Math.min(180, Number(lon)));
  $('lat').value = lat.toFixed(4); $('lon').value = lon.toFixed(4); if (state.marker) state.marker.setLatLng([lat, lon]);
  if (pan && state.map) state.map.setView([lat, lon], Math.max(state.map.getZoom(), 7));
}
function showWarning(messages=[]) { if (messages.length) { $('warning').textContent = messages.join(' '); $('warning').classList.remove('hidden'); } else $('warning').classList.add('hidden'); }

function userFacingWarnings(messages=[]) {
  return (messages || []).filter(message => {
    const text = String(message || '');
    return !(
      /SoilGrids est un modèle global à 250\s*m/i.test(text) ||
      /Enveloppe climatique régionale\s+WCVP\/TDWG-3/i.test(text) ||
      /proxy de niche réalisée/i.test(text)
    );
  });
}

function setResultsView(mode='grid') {
  state.viewMode = mode === 'list' ? 'list' : 'grid';
  const results = $('results');
  if (results) results.classList.toggle('list-view', state.viewMode === 'list');
  const grid = $('view-grid');
  const list = $('view-list');
  if (grid) {
    const active = state.viewMode === 'grid';
    grid.classList.toggle('active', active);
    grid.setAttribute('aria-pressed', String(active));
  }
  if (list) {
    const active = state.viewMode === 'list';
    list.classList.toggle('active', active);
    list.setAttribute('aria-pressed', String(active));
  }
}

function updateScenarioChart() {
  document.querySelectorAll('[data-scenario-line]').forEach(path => {
    path.classList.toggle('selected', path.dataset.scenarioLine === state.scenario);
  });
  document.querySelectorAll('[data-scenario-choice]').forEach(button => {
    const selected = button.dataset.scenarioChoice === state.scenario;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
}

function bindScenarioChart() {
  document.querySelectorAll('[data-scenario-choice]').forEach(button => {
    button.onclick = () => {
      state.scenario = button.dataset.scenarioChoice;
      if ($('scenario')) $('scenario').value = state.scenario;
      updateScenarioChart();
    };
  });
  updateScenarioChart();
}


function climateSummary(climate) {
  const v = climate.variables || {};
  $('climate-summary').innerHTML = [
    metric('Temp. annuelle', v.bio01, ' °C'), metric('Mois le + chaud', v.bio05, ' °C'), metric('Mois le + froid', v.bio06, ' °C'),
    metric('Précipitations', v.bio12, ' mm'), metric('Saisonnalité pluie', v.bio15, ''), metric('Scénario', scenarioLabel(climate.scenario), '')
  ].join('');
  const tempSpread = (climate.uncertainty || {}).bio01;
  if (tempSpread && tempSpread.n > 1) {
    $('uncertainty-note').textContent = `Ensemble de ${tempSpread.n} modèles · température annuelle p10–p90 : ${Number(tempSpread.p10).toFixed(1)} à ${Number(tempSpread.p90).toFixed(1)} °C.`;
    $('uncertainty-note').classList.remove('hidden');
  } else $('uncertainty-note').classList.add('hidden');
}

function soilSummary(soil) {
  if (!soil) { $('soil-summary').innerHTML = '<div class="empty small-empty">Profil de sol indisponible.</div>'; $('soil-source').textContent = '—'; return; }
  const p = soil.properties || {};
  $('soil-summary').innerHTML = [
    metric('pH', p.ph), metric('Argile', p.clay_pct, ' %'), metric('Sable', p.sand_pct, ' %'), metric('Limon', p.silt_pct, ' %'),
    metric('CEC', p.cec_cmol_kg, ''), metric('Fragments', p.coarse_fragments_pct, ' %'),
    metric('Carbone org.', p.soc_g_kg, ' g/kg'), metric('Azote', p.nitrogen_g_kg, ' g/kg')
  ].join('') + `<div class="soil-texture">Texture indicative : <strong>${esc(p.texture || '—')}</strong>${p.texture_class ? ` · classe ECOCROP : <strong>${esc(p.texture_class)}</strong>` : ''}${p.drainage ? ` · drainage : ${esc(p.drainage)}` : ''}</div>`;
  $('soil-source').textContent = `${soil.provider} · ${soil.depth}${soil.manual_override ? ' · corrigé par vous' : ''}`;
}

function linkFor(p, key, fallback) { return p?.links?.[key] || fallback(p?.scientific_name || ''); }

function imageHtml(p, cssClass='plant-thumb') {
  const image = p?.image || null;
  if (!image?.thumbnail_url) return `<div class="${cssClass} plant-thumb-placeholder" aria-hidden="true">🌿</div>`;
  const attr = [image.author, image.license].filter(Boolean).join(' · ');
  const inner = `<img src="${esc(image.thumbnail_url)}" alt="Illustration de ${esc(p.scientific_name || '')}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />`;
  if (image.attribution_url) return `<a class="${cssClass}" href="${esc(image.attribution_url)}" target="_blank" rel="noopener noreferrer" title="${esc(attr || 'Crédit image')}">${inner}</a>`;
  return `<div class="${cssClass}" title="${esc(attr || 'Illustration')}">${inner}</div>`;
}

function eiveHtml(p) {
  const labels = {M:'Humidité (M)', N:'Nutriments (N)', R:'Réaction du sol (R)'};
  const indicators = p.soil_indicators || [];
  if (!indicators.length) return '';
  const rows = indicators.map(i => {
    const width = i.niche_width == null ? '' : ` · largeur ${Number(i.niche_width).toFixed(2)}`;
    return `<div class="context-row"><span>${esc(labels[i.indicator] || i.indicator)}</span><strong>${Number(i.optimum).toFixed(2)} / ${esc(i.scale_max ?? 10)}</strong><small>${esc(width)}</small></div>`;
  }).join('');
  return `<div class="soil-context-block"><div class="context-title">Indicateurs écologiques experts EIVE</div>${rows}<div class="context-note">Échelle écologique européenne 0–10 conservée telle quelle ; aucune conversion en pH ou concentration de nutriments.</div></div>`;
}

function geographicPriorHtml(p) {
  const ctx = p.soil_geographic_context;
  if (!ctx || !ctx.variables) return '';
  const labels = {ph:'pH', cec_cmol_kg:'CEC', clay_pct:'Argile %', sand_pct:'Sable %', coarse_fragments_pct:'Fragments %', soc_g_kg:'Carbone org. g/kg', nitrogen_g_kg:'Azote g/kg'};
  const order = ['ph','cec_cmol_kg','clay_pct','sand_pct','coarse_fragments_pct','soc_g_kg','nitrogen_g_kg'];
  const rows = order.filter(key => ctx.variables[key]).map(key => {
    const v = ctx.variables[key];
    const lo = v.central_low; const hi = v.central_high; const med = v.region_median;
    return `<div class="context-row"><span>${esc(labels[key] || key)}</span><strong>${lo == null || hi == null ? '—' : `${esc(lo)}–${esc(hi)}`}</strong><small>${med == null ? '' : `médiane ${esc(med)}`}</small></div>`;
  }).join('');
  if (!rows) return '';
  return `<div class="soil-context-block prior"><div class="context-title">Contexte des sols de l’aire native</div>${rows}<div class="context-note">${esc(ctx.covered_region_count)} région(s) native(s) couverte(s). Contexte géographique uniquement : il n’entre jamais dans le score.</div></div>`;
}

function genusName(scientificName) {
  const parts = String(scientificName || '').trim().replace(/^×\s*/, '').split(/\s+/).filter(Boolean);
  return parts[0] || 'Genre non renseigné';
}


function numericScore(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function recommendationSortKeyScore(plant, mode) {
  if (mode === 'combined') return numericScore(plant.combined_score);
  if (mode === 'climate') return numericScore(plant.overall_score);
  if (mode === 'soil') return String(plant.soil?.status || 'UNKNOWN').toUpperCase() === 'UNKNOWN' ? null : numericScore(plant.soil?.score);
  return null;
}

function sortedRecommendations(recommendations, mode=state.sortMode) {
  const items = [...(recommendations || [])];
  if (mode === 'scientific') {
    return items.sort((a,b) => (a.__apiRank ?? 999999) - (b.__apiRank ?? 999999));
  }
  if (mode === 'name') {
    return items.sort((a,b) => String(a.scientific_name || '').localeCompare(String(b.scientific_name || ''), 'fr', {sensitivity:'base'}));
  }
  return items.sort((a,b) => {
    const av = recommendationSortKeyScore(a, mode);
    const bv = recommendationSortKeyScore(b, mode);
    if (av == null && bv != null) return 1;
    if (av != null && bv == null) return -1;
    if (av != null && bv != null && av !== bv) return bv - av;
    const ar = a.__apiRank ?? 999999, br = b.__apiRank ?? 999999;
    if (ar !== br) return ar - br;
    return String(a.scientific_name || '').localeCompare(String(b.scientific_name || ''), 'fr', {sensitivity:'base'});
  });
}

function renderCurrentRecommendations() {
  const results = $('results-list');
  if (!results) return;
  const ordered = sortedRecommendations(state.lastRecommendations, state.sortMode);
  const groups = ordered.length ? renderGroupedRecommendations(ordered) : '<div class="empty">Aucun candidat avec ces filtres.</div>';
  const shown = ordered.length;
  const canLoadMore = shown < state.lastEvaluatedCandidates && shown < state.recommendationMax;
  const remaining = Math.max(0, Math.min(state.recommendationStep, state.lastEvaluatedCandidates - shown));
  const more = canLoadMore
    ? `<div class="load-more-wrap"><button id="load-more" class="secondary load-more">Afficher ${remaining} de plus</button><div class="field-help">${shown} résultats affichés sur ${state.lastEvaluatedCandidates} candidats scorés.</div></div>`
    : (shown ? `<div class="list-end">${shown} résultats chargés.</div>` : '');
  results.innerHTML = groups + more;
  setResultsView(state.viewMode);
  const next = $('load-more');
  if (next) next.onclick = () => searchRecommendations(true);
}

function renderGroupedRecommendations(recommendations) {
  const groups = new Map();
  for (const plant of recommendations || []) {
    const genus = genusName(plant.scientific_name);
    if (!groups.has(genus)) groups.set(genus, []);
    groups.get(genus).push(plant);
  }
  let index = 0;
  return [...groups.entries()].map(([genus, plants]) => {
    const best = state.sortMode === 'scientific'
      ? (plants.find(p => p.combined_score != null)?.combined_score ?? plants.find(p => p.overall_score != null)?.overall_score)
      : recommendationSortKeyScore(plants[0], state.sortMode);
    const open = index++ === 0 ? ' open' : '';
    return `<details class="genus-group" data-genus="${esc(genus)}"${open}>
      <summary><span class="genus-summary-name"><em>${esc(genus)}</em></span><span class="genus-summary-meta"><span data-visible-count>${plants.length}</span> plante${plants.length > 1 ? 's' : ''}${best == null ? '' : ` · meilleur score ${esc(best)}`}</span><span class="genus-chevron">⌄</span></summary>
      <div class="genus-cards">${plants.map(plantCard).join('')}</div>
    </details>`;
  }).join('');
}

function plantCard(p) {
  const climateComp = (p.components || []).map(c => `<div class="component"><span class="muted">${esc(c.variable)}</span><span>${c.value == null ? '—' : esc(c.value)}</span><span class="status ${esc(c.status)}">${esc(c.status)}</span></div>`).join('');
  const soilComp = (p.soil?.components || []).map(c => `<div class="component"><span class="muted">${esc(c.variable)}</span><span>${c.value == null ? '—' : esc(c.value)}</span><span class="status ${esc(c.status)}">${esc(c.status)}</span></div>`).join('');
  const funcs = (p.functions || []).map(f => `<span>${esc(f)}</span>`).join('');
  const veto = p.regulatory_veto ? `<div class="veto">Veto distinct de la compatibilité${p.regulatory_reason ? ` · ${esc(p.regulatory_reason)}` : ''}</div>` : '';
  const soilStatus = p.soil?.status || 'UNKNOWN';
  const soilUsable = String(soilStatus).toUpperCase() !== 'UNKNOWN' && p.soil?.score != null;
  const soilScore = soilUsable ? esc(p.soil.score) : '—';
  const combinedScore = p.combined_score == null ? (p.overall_score == null ? '—' : esc(p.overall_score)) : esc(p.combined_score);
  const combinedStatus = p.combined_status || p.overall_status || 'UNKNOWN';
  return `<article class="plant-card" data-rank="${esc((p.__apiRank ?? 0) + 1)}" data-combined-score="${esc(p.combined_score ?? '')}" data-climate-score="${esc(p.overall_score ?? '')}" data-soil-score="${soilUsable ? esc(p.soil.score) : ''}" data-climate-status="${esc(p.overall_status || 'UNKNOWN')}" data-soil-status="${esc(soilStatus)}" data-veto="${p.regulatory_veto ? '1' : '0'}" data-has-image="${p?.image?.thumbnail_url ? '1' : '0'}">
    <div class="plant-top">
      <div class="plant-identity">${imageHtml(p)}<div><div class="plant-name"><em>${esc(p.scientific_name)}</em></div><div class="common">${esc(p.common_name || '')}</div></div></div>
      <div class="plant-scores">
        <div class="plant-score main-score"><div class="score">${combinedScore}</div><div class="score-label">Global</div><div class="status ${esc(combinedStatus)}">${esc(statusLabel(combinedStatus))}</div></div>
        <div class="plant-score"><div class="score">${p.overall_score == null ? '—' : esc(p.overall_score)}</div><div class="score-label">Climat</div><div class="status ${esc(p.overall_status)}">${esc(statusLabel(p.overall_status))}</div></div>
        <div class="plant-score"><div class="score">${soilScore}</div><div class="score-label">Sol</div><div class="status ${esc(soilStatus)}">${esc(statusLabel(soilStatus))}</div></div>
      </div>
    </div>
    ${veto}
    <div class="explain">${esc(p.explanation)} Confiance climat ${esc(p.confidence)} · couverture ${(Number(p.known_weight_fraction || 0)*100).toFixed(0)} %.</div>
    <div class="soil-explain">${esc(p.soil?.explanation || 'Compatibilité sol inconnue.')}</div>
    <div class="functions">${funcs}</div>
    <div class="card-actions">
      <button class="secondary trajectory-btn" data-taxon="${esc(p.taxon_id)}">Voir 2026 → 2100</button>
      <a class="secondary external-link" href="${esc(linkFor(p, 'powo', powoSearchUrl))}" target="_blank" rel="noopener noreferrer">POWO / Kew ↗</a>
      <a class="secondary external-link" href="${esc(linkFor(p, 'wikipedia', wikipediaUrl))}" target="_blank" rel="noopener noreferrer">Wikipédia ↗</a>
      <a class="secondary external-link" href="${esc(linkFor(p, 'qwant', qwantUrl))}" target="_blank" rel="noopener noreferrer">Qwant ↗</a>
    </div>
    <details class="components"><summary>Détail climat</summary>${climateComp || '<div class="empty small-empty">Aucun critère climatique disponible.</div>'}</details>
    <details class="components"><summary>Détail sol scoré</summary>${soilComp || '<div class="empty small-empty">Aucune préférence de sol directement comparable : UNKNOWN.</div>'}</details>
    ${(p.soil_indicators || []).length || p.soil_geographic_context ? `<details class="components soil-context"><summary>Contexte écologique du sol</summary>${eiveHtml(p)}${geographicPriorHtml(p)}</details>` : ''}
  </article>`;
}

function soilParams() {
  const params = {};
  if (!$('soil-manual').checked) return params;
  const fields = [
    ['soil_ph','soil-ph'], ['soil_clay','soil-clay'], ['soil_sand','soil-sand'], ['soil_silt','soil-silt'],
    ['soil_cec','soil-cec'], ['soil_coarse_fragments','soil-coarse'], ['soil_soc','soil-soc'],
    ['soil_nitrogen','soil-nitrogen'], ['soil_drainage','soil-drainage']
  ];
  fields.forEach(([param,id]) => { const node = $(id); if (!node) return; const value = node.value; if (value !== '') params[param] = value; });
  return params;
}
function appendSoilParams(params) { Object.entries(soilParams()).forEach(([key,value]) => params.append(key, value)); }

async function loadMeta() {
  const response = await fetch(apiUrl('meta'), {cache: 'no-store'}); if (!response.ok) throw new Error(`Métadonnées API ${response.status}`);
  state.meta = await response.json(); $('method-pill').textContent = `V2 · ${state.meta.method_version || 'moteur explicable'}`;
  const metaHorizons = Array.isArray(state.meta.horizons) ? state.meta.horizons : [];
  const metaScenarios = Array.isArray(state.meta.scenarios) ? state.meta.scenarios : [];
  const metaFunctions = Array.isArray(state.meta.functions) ? state.meta.functions : [];
  if (metaHorizons.length) $('horizons').innerHTML = metaHorizons.map(h => `<button class="${h.value === state.horizon ? 'active' : ''}" data-value="${esc(h.value)}">${esc(h.label)}</button>`).join('');
  if (metaScenarios.length) $('scenario').innerHTML = metaScenarios.map(s => `<option value="${esc(s.value)}" ${s.value === state.scenario ? 'selected' : ''}>${esc(s.label)} · ${esc(s.ssp)}</option>`).join('');
  if (metaFunctions.length) $('functions').innerHTML = `<button class="active" data-value="">Toutes</button>` + metaFunctions.map(f => `<button data-value="${esc(f.value)}">${esc(f.label)}</button>`).join('');
  document.querySelectorAll('#horizons button').forEach(btn => btn.onclick = () => { document.querySelectorAll('#horizons button').forEach(b => b.classList.remove('active')); btn.classList.add('active'); state.horizon = btn.dataset.value; });
  document.querySelectorAll('#functions button').forEach(btn => btn.onclick = () => { document.querySelectorAll('#functions button').forEach(b => b.classList.remove('active')); btn.classList.add('active'); state.fn = btn.dataset.value; });
  $('scenario').onchange = e => { state.scenario = e.target.value; updateScenarioChart(); };
  bindScenarioChart();
  window.dispatchEvent(new CustomEvent('climaflora:meta-loaded'));
}

async function searchRecommendations(loadMore=false) {
  if (!state.scientificReady) return loadReadiness();
  if (loadMore) state.recommendationLimit = Math.min(state.recommendationLimit + state.recommendationStep, state.recommendationMax); else state.recommendationLimit = state.recommendationStep;
  const btn = $('search'); btn.classList.add('loading'); btn.textContent = 'Calcul en cours…';
  const moreBtn = $('load-more'); if (moreBtn) { moreBtn.disabled = true; moreBtn.textContent = 'Chargement…'; }
  const params = new URLSearchParams({lat: $('lat').value, lon: $('lon').value, horizon: state.horizon, scenario: state.scenario, limit: String(state.recommendationLimit)});
  if (state.fn) params.append('function', state.fn); appendSoilParams(params);
  const selectedLifeButton = document.querySelector('.lifeform-grid button.active[data-lifeform]');
  const selectedLifeForm = selectedLifeButton?.dataset.lifeform || 'ALL';
  const recommendationEndpoint = selectedLifeForm === 'ALL' ? 'recommendations' : 'recommendations/by-life-form';
  if (selectedLifeForm !== 'ALL') params.append('life_form', selectedLifeForm);
  try {
    const response = await fetch(`${apiUrl(recommendationEndpoint)}?${params}`); if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json(); const shown = data.recommendations.length;
    state.lastRecommendations = (data.recommendations || []).map((plant, index) => ({...plant, __apiRank:index}));
    state.lastEvaluatedCandidates = Number(data.evaluated_candidates || shown);
    state.lastMethodVersion = data.method_version || '';
    $('results').classList.remove('hidden');
    $('result-title').classList.remove('hidden');
    $('result-title').textContent = `Résultats · ${state.horizon === 'NOW' ? 'Aujourd’hui' : state.horizon}`;
    const lifeLabel = selectedLifeForm === 'ALL' ? '' : (selectedLifeButton?.querySelector('strong')?.textContent || selectedLifeForm);
    const poolBeforeLife = Number(data.candidate_pool_before_life_form || 0);
    const candidateWording = selectedLifeForm === 'ALL'
      ? `${shown} chargés sur ${state.lastEvaluatedCandidates} candidats évalués`
      : `${shown} chargés sur ${state.lastEvaluatedCandidates} ${lifeLabel.toLowerCase()} évalué${state.lastEvaluatedCandidates > 1 ? 's' : ''}${poolBeforeLife ? ` · ${poolBeforeLife} pré-candidats avant filtre de forme` : ''}`;
    const baseSubtitle = `${candidateWording} · méthode ${state.lastMethodVersion}`;
    $('result-subtitle').dataset.base = baseSubtitle;
    $('result-subtitle').textContent = baseSubtitle;
    climateSummary(data.climate); soilSummary(data.soil);
    renderCurrentRecommendations();
    showWarning(userFacingWarnings(data.warnings || []));
  } catch (error) {
    $('results').classList.remove('hidden');
    $('results-list').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`;
  } finally {
    btn.classList.remove('loading'); btn.innerHTML = 'Trouver les plantes <span>→</span>';
  }
}

function renderPlantSuggestions(hits) {
  const root = $('plant-hits');
  if (!hits?.length) {
    root.innerHTML = '<div class="field-help">Aucune plante trouvée.</div>';
    return;
  }
  root.innerHTML = hits.map(hit => `
    <div class="plant-hit-row" data-suggestion-taxon="${esc(hit.taxon_id)}">
      <button class="plant-hit-select" type="button" data-select-taxon="${esc(hit.taxon_id)}" aria-label="Sélectionner ${esc(hit.scientific_name)}">
        ${imageHtml(hit, 'plant-hit-thumb')}
        <span class="plant-hit-label"><em>${esc(hit.scientific_name)}</em>${hit.common_name ? `<small>${esc(hit.common_name)}</small>` : ''}</span>
      </button>
      <button class="plant-hit-analyse" type="button" data-analyse-taxon="${esc(hit.taxon_id)}">Analyser</button>
      <span class="hit-links"><a href="${esc(hit.links?.powo || powoSearchUrl(hit.scientific_name))}" target="_blank" rel="noopener noreferrer">Kew ↗</a><a href="${esc(hit.links?.qwant || qwantUrl(hit.scientific_name))}" target="_blank" rel="noopener noreferrer">Qwant ↗</a></span>
    </div>`).join('');
  for (const hit of hits) {
    const row = root.querySelector(`[data-suggestion-taxon="${CSS.escape(String(hit.taxon_id))}"]`);
    const select = row?.querySelector('[data-select-taxon]');
    const analyse = row?.querySelector('[data-analyse-taxon]');
    if (select) select.onclick = () => selectPlantSuggestion(hit, row);
    if (analyse) analyse.onclick = () => { selectPlantSuggestion(hit, row); loadTrajectory(hit.taxon_id); };
  }
}

function selectPlantSuggestion(hit, row=null) {
  state.selectedPlant = hit;
  document.querySelectorAll('.plant-hit-row').forEach(node => node.classList.remove('selected'));
  if (row) row.classList.add('selected');
  $('plant-query').value = hit.scientific_name || hit.common_name || '';
  const btn = $('plant-search');
  btn.disabled = !state.scientificReady;
  btn.textContent = 'Analyser la sélection';
}

async function searchPlant({silent=false}={}) {
  if (!state.scientificReady) return loadReadiness();
  const q = $('plant-query').value.trim();
  if (q.length < 2) {
    state.selectedPlant = null;
    $('plant-search').disabled = true;
    $('plant-hits').innerHTML = q ? '<div class="field-help">Continuez à saisir pour voir les suggestions.</div>' : '';
    return;
  }
  const btn = $('plant-search');
  if (!silent) { btn.classList.add('loading'); btn.textContent = 'Recherche…'; }
  try {
    const response = await fetch(`${apiUrl('plants/search')}?${new URLSearchParams({q, limit:'20'})}`); if (!response.ok) throw new Error(`API ${response.status}`);
    const hits = await response.json();
    renderPlantSuggestions(hits);
  } catch (error) {
    $('plant-hits').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`;
  } finally {
    if (!silent) btn.classList.remove('loading');
    if (!state.selectedPlant) { btn.textContent = 'Analyser la sélection'; btn.disabled = true; }
  }
}

function schedulePlantAutocomplete() {
  state.selectedPlant = null;
  const btn = $('plant-search');
  btn.disabled = true;
  btn.textContent = 'Analyser la sélection';
  clearTimeout(state.plantSearchTimer);
  state.plantSearchTimer = setTimeout(() => searchPlant({silent:true}), 220);
}

function trajectoryHtml(data, enrichment=null) {
  const pointsData = Array.isArray(data.points) ? data.points : [];
  const hasAnyScore = pointsData.some(point => point?.result?.overall_score != null);
  const points = pointsData.map(point => {
    const result = point.result || {};
    const climateScore = result.overall_score == null ? null : Number(result.overall_score);
    const soilStatus = result.soil?.status || 'UNKNOWN';
    const soilScore = String(soilStatus).toUpperCase() === 'UNKNOWN' || result.soil?.score == null ? null : Number(result.soil.score);
    const width = climateScore == null ? 0 : Math.max(0, Math.min(100, climateScore));
    const veto = result.regulatory_veto ? '<span class="mini-veto">veto</span>' : '';
    const climateStatus = result.overall_status || 'UNKNOWN';
    return `<div class="trajectory-row"><div class="trajectory-year">${esc(point.horizon === 'NOW' ? 'Actuel' : point.horizon)}</div><div class="trajectory-bar ${climateScore == null ? 'unknown' : ''}"><span class="bar ${esc(climateStatus)}" style="width:${width}%"></span></div><div class="trajectory-metrics"><span class="trajectory-metric ${esc(climateStatus)}"><b>Climat</b> ${climateScore == null ? '—' : climateScore.toFixed(0)}</span><span class="trajectory-metric ${esc(soilStatus)}"><b>Sol</b> ${soilScore == null ? '—' : soilScore.toFixed(0)}</span>${veto}</div></div>`;
  }).join('');
  const powo = data.links?.powo || powoSearchUrl(data.scientific_name); const wiki = data.links?.wikipedia || wikipediaUrl(data.scientific_name); const qwant = data.links?.qwant || qwantUrl(data.scientific_name);
  const vernacular = enrichment?.vernacular_name_fr || enrichment?.vernacular_name_en || '';
  const uses = (enrichment?.uses || []).slice(0,6);
  const descriptors = [
    enrichment?.life_form ? `<span>${esc(lifeFormLabel(enrichment.life_form))}</span>` : '',
    ...uses.map(use => `<span>${esc(use.label_fr || use.label_en || use.code)}</span>`)
  ].filter(Boolean).join('');
  const gap = hasAnyScore ? '' : `<div class="trajectory-data-gap"><strong>Données de compatibilité insuffisantes pour ce taxon exact.</strong><p>ClimaFlora ne propage pas automatiquement les tolérances d’une espèce parente vers une sous-espèce ou un taxon voisin. La fiche reste donc UNKNOWN tant qu’aucune enveloppe climatique exacte n’est disponible.</p></div>`;
  return `<div class="trajectory-head"><div class="trajectory-identity">${imageHtml(data)}<div><h3><em>${esc(data.scientific_name)}</em>${vernacular ? `<small class="drawer-common-name">${esc(vernacular)}</small>` : ''}</h3>${descriptors ? `<div class="drawer-descriptors">${descriptors}</div>` : ''}<div class="inline-links"><a href="${esc(powo)}" target="_blank" rel="noopener noreferrer">POWO / Kew ↗</a><a href="${esc(wiki)}" target="_blank" rel="noopener noreferrer">Wikipédia ↗</a><a href="${esc(qwant)}" target="_blank" rel="noopener noreferrer">Qwant ↗</a></div></div></div><div class="trajectory-meta"><span class="trajectory-label">Trajectoire</span><div class="source-badge">${esc(scenarioLabel(data.scenario))}</div></div></div>${gap}${points}`;
}

async function fetchPlantEnrichment(taxonId) {
  const key = String(taxonId);
  if (state.enrichmentCache.has(key)) return state.enrichmentCache.get(key);
  try {
    const params = new URLSearchParams(); params.append('taxon_id', key);
    const response = await fetch(`${apiUrl('plants/enrichment')}?${params}`, {cache:'no-store'});
    if (!response.ok) return null;
    const payload = await response.json();
    const value = payload?.taxa?.[key] || null;
    state.enrichmentCache.set(key, value);
    return value;
  } catch (_) { return null; }
}

function trajectoryCacheKey(taxonId) {
  const {lat, lon} = currentCoords();
  const soil = new URLSearchParams();
  Object.entries(soilParams()).sort(([a],[b]) => a.localeCompare(b)).forEach(([key,value]) => soil.append(key, String(value)));
  return [String(taxonId), lat.toFixed(4), lon.toFixed(4), state.scenario, soil.toString()].join('|');
}

async function fetchTrajectoryBundle(taxonId) {
  const cacheKey = trajectoryCacheKey(taxonId);
  if (state.trajectoryCache.has(cacheKey)) return state.trajectoryCache.get(cacheKey);
  if (state.trajectoryPending.has(cacheKey)) return state.trajectoryPending.get(cacheKey);
  const {lat, lon} = currentCoords();
  const params = new URLSearchParams({lat, lon, scenario: state.scenario}); appendSoilParams(params);
  const promise = Promise.all([
    fetch(`${apiUrl(`plants/${encodeURIComponent(taxonId)}/trajectory`)}?${params}`).then(response => {
      if (!response.ok) throw new Error(`API ${response.status}`);
      return response.json();
    }),
    fetchPlantEnrichment(String(taxonId))
  ]).then(([data,enrichment]) => {
    const bundle = {data,enrichment};
    state.trajectoryCache.set(cacheKey,bundle);
    return bundle;
  }).finally(() => state.trajectoryPending.delete(cacheKey));
  state.trajectoryPending.set(cacheKey,promise);
  return promise;
}

function prefetchTrajectory(taxonId) {
  if (!state.scientificReady || !taxonId) return;
  fetchTrajectoryBundle(String(taxonId)).catch(() => {});
}

function openDrawer(content='<div class="empty">Chargement…</div>') {
  const drawer = $('plant-drawer'); const backdrop = $('drawer-backdrop');
  $('plant-drawer-content').innerHTML = content;
  drawer.classList.remove('hidden'); backdrop.classList.remove('hidden');
  drawer.setAttribute('aria-hidden','false'); backdrop.setAttribute('aria-hidden','false');
  document.body.classList.add('drawer-open');
  drawer.scrollTop = 0;
}

function closeDrawer() {
  const drawer = $('plant-drawer'); const backdrop = $('drawer-backdrop');
  drawer.classList.add('hidden'); backdrop.classList.add('hidden');
  drawer.setAttribute('aria-hidden','true'); backdrop.setAttribute('aria-hidden','true');
  document.body.classList.remove('drawer-open');
}

async function loadTrajectory(taxonId) {
  if (!state.scientificReady) return loadReadiness();
  openDrawer('<div class="drawer-loading">Chargement de la fiche…</div>');
  try {
    const {data, enrichment} = await fetchTrajectoryBundle(String(taxonId));
    $('plant-drawer-content').innerHTML = trajectoryHtml(data, enrichment);
  } catch (error) {
    $('plant-drawer-content').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`;
  }
}

function switchMode(mode) {
  state.mode = mode;
  document.querySelectorAll('.mode-tabs button').forEach(button => button.classList.toggle('active', button.dataset.mode === mode));
  $('explore-controls').classList.toggle('hidden', mode !== 'explore');
  $('plant-controls').classList.toggle('hidden', mode !== 'plant');
  if (mode !== 'explore') $('results').classList.add('hidden');
  closeDrawer();
}

$('lat').addEventListener('change', () => setPoint($('lat').value, $('lon').value)); $('lon').addEventListener('change', () => setPoint($('lat').value, $('lon').value));
$('search').onclick = searchRecommendations; $('plant-search').onclick = () => { if (state.selectedPlant?.taxon_id) loadTrajectory(state.selectedPlant.taxon_id); }; $('plant-query').addEventListener('input', schedulePlantAutocomplete); $('plant-query').addEventListener('keydown', event => { if (event.key === 'Enter' && state.selectedPlant?.taxon_id) { event.preventDefault(); loadTrajectory(state.selectedPlant.taxon_id); } });
function syncManualSoilFields() {
  const enabled = Boolean($('soil-manual').checked);
  const box = $('soil-manual-fields');
  box.classList.toggle('soil-grid-enabled', enabled);
  box.classList.toggle('soil-grid-disabled', !enabled);
  box.setAttribute('aria-disabled', String(!enabled));
  box.querySelectorAll('input, select').forEach(control => { control.disabled = !enabled; });
  const help = $('soil-manual-help');
  if (help) help.textContent = enabled
    ? 'Valeurs personnelles activées : seules les propriétés renseignées remplaceront SoilGrids au prochain calcul.'
    : 'Cochez la case pour activer ces champs. Les valeurs renseignées remplacent SoilGrids uniquement pour les propriétés concernées.';
}
$('soil-manual').addEventListener('change', syncManualSoilFields);
syncManualSoilFields();
$('geolocate').onclick = () => {
  if (!navigator.geolocation) return showWarning(['La géolocalisation n’est pas disponible dans ce navigateur.']);
  navigator.geolocation.getCurrentPosition(pos => { setPoint(pos.coords.latitude, pos.coords.longitude, true); showWarning([]); }, () => showWarning(['Impossible de récupérer la position. Vous pouvez toujours cliquer sur la carte.']));
};
document.querySelectorAll('.mode-tabs button').forEach(button => button.onclick = () => switchMode(button.dataset.mode));
document.addEventListener('click', event => { const target = event.target.closest('.trajectory-btn[data-taxon]'); if (target) loadTrajectory(target.dataset.taxon); });
$('drawer-close').onclick = closeDrawer; $('drawer-backdrop').onclick = closeDrawer; document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDrawer(); });

const resultSort = $('result-sort');
if (resultSort) {
  resultSort.value = state.sortMode;
  resultSort.onchange = () => {
    state.sortMode = resultSort.value || 'scientific';
    renderCurrentRecommendations();
  };
}
const viewGridButton = $('view-grid');
const viewListButton = $('view-list');
if (viewGridButton) viewGridButton.onclick = () => setResultsView('grid');
if (viewListButton) viewListButton.onclick = () => setResultsView('list');
setResultsView('grid');

initMap();
initCitySearch();
bindScenarioChart();


// Warm a trajectory only when the user shows intent to open a fiche.
document.addEventListener('pointerover', event => {
  const target = event.target.closest?.('[data-taxon], [data-analyse-taxon]');
  const taxonId = target?.dataset?.taxon || target?.dataset?.analyseTaxon;
  if (taxonId) prefetchTrajectory(taxonId);
});
document.addEventListener('focusin', event => {
  const target = event.target.closest?.('[data-taxon], [data-analyse-taxon]');
  const taxonId = target?.dataset?.taxon || target?.dataset?.analyseTaxon;
  if (taxonId) prefetchTrajectory(taxonId);
});

(async () => {
  try {
    await resolveApiBase();
  } catch (error) {
    setScientificAvailability(false, null);
    showWarning([error.message]);
    return;
  }

  const [metaResult, readinessResult] = await Promise.allSettled([loadMeta(), loadReadiness()]);
  if (metaResult.status === 'rejected') {
    showWarning([`Métadonnées indisponibles (${metaResult.reason?.message || 'erreur inconnue'}). Les valeurs par défaut restent affichées.`]);
  }
  if (readinessResult.status === 'rejected') {
    setScientificAvailability(false, null);
  }
})();

/* ---- ClimaFlora v1.8 descriptive UI enrichment ---- */
(() => {
  'use strict';

  const getApiBase = () => String(window.CLIMAFLORA_RUNTIME?.apiBase || 'https://gyamotab-climaflora-engine.hf.space/api/v1').replace(/\/$/, '');
  const lifeLabels = {
    ALL: 'Tous', TREE: 'Arbres', SHRUB: 'Arbustes', HERB: 'Herbacées',
    CLIMBER: 'Grimpantes', PALM: 'Palmiers', OTHER: 'Autres', UNKNOWN: 'Non renseigné'
  };
  const lifeIcons = {ALL:'❧', TREE:'♠', SHRUB:'♧', HERB:'✤', CLIMBER:'⌁', PALM:'♜', OTHER:'◇', UNKNOWN:'?'};
  const state = {life:'ALL', alpha:'ALL', lifeFilters:new Set(), statuses:new Set(['GREEN','ORANGE','RED','UNKNOWN']), uses:new Set(), constraints:new Set(), other:new Set(), enrichment:new Map()};
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
        const results = document.getElementById('results');
        if (results && !results.classList.contains('hidden')) {
          searchRecommendations(false);
        } else {
          applyFilters();
        }
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
      <details open class="alphabet-filter"><summary>Genres par lettre</summary><div id="alpha-filter-v4" class="alpha-filter"><button type="button" class="active" data-alpha="ALL">Tous</button></div></details>
      <details open><summary>Usages documentés</summary><div id="use-filter-v4" class="dynamic-filter-list"><p>Aucun usage v1.8 chargé pour l’instant.</p></div></details>
      <details open><summary>Type de plante</summary><div id="life-summary-v4" class="dynamic-filter-list"><p>Les types apparaîtront avec les résultats.</p></div></details>
      <details open><summary>Contraintes</summary><div id="constraint-filter-v4" class="dynamic-filter-list">
        <label><input type="checkbox" value="NO_VETO"> <span>Sans veto réglementaire</span><small data-filter-count="NO_VETO">0</small></label>
        <label><input type="checkbox" value="CLIMATE_KNOWN"> <span>Climat renseigné</span><small data-filter-count="CLIMATE_KNOWN">0</small></label>
        <label><input type="checkbox" value="SOIL_KNOWN"> <span>Sol renseigné</span><small data-filter-count="SOIL_KNOWN">0</small></label>
      </div></details>
      <details open><summary>Autres critères</summary><div id="other-filter-v4" class="dynamic-filter-list">
        <label><input type="checkbox" value="HAS_IMAGE"> <span>Avec image</span><small data-filter-count="HAS_IMAGE">0</small></label>
        <label><input type="checkbox" value="HAS_FR_NAME"> <span>Avec nom français</span><small data-filter-count="HAS_FR_NAME">0</small></label>
        <label><input type="checkbox" value="HAS_USES"> <span>Avec usages documentés</span><small data-filter-count="HAS_USES">0</small></label>
      </div></details>`;
    panel.querySelectorAll('#status-filter-v4 input').forEach(input => input.onchange = () => {
      input.checked ? state.statuses.add(input.value) : state.statuses.delete(input.value); applyFilters();
    });
    panel.querySelectorAll('#constraint-filter-v4 input').forEach(input => input.onchange = () => {
      input.checked ? state.constraints.add(input.value) : state.constraints.delete(input.value); applyFilters();
    });
    panel.querySelectorAll('#other-filter-v4 input').forEach(input => input.onchange = () => {
      input.checked ? state.other.add(input.value) : state.other.delete(input.value); applyFilters();
    });
    panel.querySelector('#reset-v4').onclick = () => {
      state.life='ALL'; state.alpha='ALL'; state.lifeFilters.clear(); state.statuses=new Set(['GREEN','ORANGE','RED','UNKNOWN']); state.uses.clear(); state.constraints.clear(); state.other.clear();
      document.querySelectorAll('.lifeform-grid button').forEach(b => b.classList.toggle('active', b.dataset.lifeform === 'ALL'));
      document.querySelectorAll('#alpha-filter-v4 button').forEach(b => b.classList.toggle('active', b.dataset.alpha === 'ALL'));
      panel.querySelectorAll('input[type="checkbox"]').forEach(i => { i.checked = i.closest('#status-filter-v4') ? true : false; });
      applyFilters();
    };
  }

  async function fetchEnrichment(ids) {
    const missing = ids.filter(id => !state.enrichment.has(id));
    if (!missing.length) return;
    const params = new URLSearchParams();
    missing.slice(0, 250).forEach(id => params.append('taxon_id', id));
    const response = await fetch(`${getApiBase()}/plants/enrichment?${params}`, {cache:'no-store'});
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
    card.dataset.hasUses = (data.uses || []).length ? '1' : '0';
    card.dataset.hasFrName = data.vernacular_name_fr ? '1' : '0';
    card.dataset.hasImage = card.querySelector('.plant-thumb img') ? '1' : '0';
    card.dataset.veto = card.querySelector('.veto') ? '1' : (card.dataset.veto || '0');
    const soilStatuses = [...card.querySelectorAll('.plant-scores .status')];
    card.dataset.soilStatus = soilStatuses[1]?.classList.contains('UNKNOWN') ? 'UNKNOWN' : (card.dataset.soilStatus || 'UNKNOWN');

    const identity = card.querySelector('.plant-identity>div:last-child');
    const common = card.querySelector('.common');
    if (common && data.vernacular_name_fr) common.textContent = data.vernacular_name_fr;
    if (identity) {
      const badges = document.createElement('div'); badges.className='descriptive-badges';
      if (data.life_form) badges.innerHTML += `<span title="Forme biologique documentée : ${esc(data.life_form)}">${esc(lifeLabels[category])}</span>`;
      (data.uses || []).slice(0,2).forEach(use => badges.innerHTML += `<span>${esc(use.label_fr || use.label_en || use.code)}</span>`);
      if (badges.children.length) identity.appendChild(badges);
    }
    const funcs = card.querySelector('.functions');
    if (funcs && (data.uses || []).length) {
      funcs.innerHTML = (data.uses || []).slice(0,4).map(use => `<span title="Usage rapporté · ${esc(use.source_id || '')}">${esc(use.label_fr || use.label_en || use.code)}</span>`).join('');
      funcs.insertAdjacentHTML('beforeend','<small>Usages rapportés : information descriptive, pas une recommandation de sécurité ou d’efficacité.</small>');
    }
    const action = card.querySelector('.trajectory-btn'); if (action) action.textContent='Voir la fiche →';
    const top = card.querySelector('.plant-top');
    if (top && !top.querySelector('.future-favorite')) { const fav=document.createElement('button'); fav.type='button'; fav.disabled=true; fav.className='future-favorite'; fav.title='Favoris bientôt disponibles'; fav.textContent='♡'; top.appendChild(fav); }
    card.dataset.enriched='1';
  }

  function rebuildAlphabetFilter() {
    const alpha=document.getElementById('alpha-filter-v4');
    if (!alpha) return;
    const plantCounts = new Map();
    let totalPlants = 0;
    document.querySelectorAll('.genus-group').forEach(group => {
      const letter = String(group.dataset.genus || '').trim().charAt(0).toUpperCase();
      const count = group.querySelectorAll('.plant-card').length;
      totalPlants += count;
      if (/^[A-ZÀ-ÖØ-Þ]$/.test(letter)) plantCounts.set(letter, (plantCounts.get(letter) || 0) + count);
    });
    const letters = [...plantCounts.keys()].sort((a,b)=>a.localeCompare(b,'fr'));
    alpha.innerHTML =
      `<div class="alpha-buttons"><button type="button" class="${state.alpha==='ALL'?'active':''}" data-alpha="ALL">Tous <small>${totalPlants}</small></button>` +
      letters.map(letter => `<button type="button" class="${state.alpha===letter?'active':''}" data-alpha="${esc(letter)}">${esc(letter)} <small>${plantCounts.get(letter)}</small></button>`).join('') +
      `</div><div class="alpha-filter-foot"><p class="alpha-filter-note">Lettres des résultats actuellement chargés. Les candidats évalués mais non encore chargés ne sont pas encore inclus.</p>${document.getElementById('load-more') ? '<button type="button" class="alpha-more">Afficher plus de résultats</button>' : ''}</div>`;
    alpha.querySelectorAll('button[data-alpha]').forEach(button => button.onclick = () => {
      state.alpha = button.dataset.alpha || 'ALL';
      alpha.querySelectorAll('button[data-alpha]').forEach(b => b.classList.toggle('active', b === button));
      applyFilters();
    });
    const more = alpha.querySelector('.alpha-more');
    if (more) more.onclick = () => document.getElementById('load-more')?.click();
  }

  function rebuildDynamicFilters() {
    const cards = [...document.querySelectorAll('.plant-card[data-enriched="1"]')];
    const counts={GREEN:0,ORANGE:0,RED:0,UNKNOWN:0}; const lifeCounts={}; const useMap=new Map();
    cards.forEach(card => {
      counts[card.dataset.status || 'UNKNOWN']++;
      lifeCounts[card.dataset.lifeform || 'UNKNOWN']=(lifeCounts[card.dataset.lifeform || 'UNKNOWN']||0)+1;
      const data=state.enrichment.get(cardTaxon(card));
      (data?.uses||[]).forEach(use => { const prev=useMap.get(use.code)||{count:0,label:use.label_fr||use.label_en||use.code}; prev.count++; useMap.set(use.code,prev); });
    });
    Object.entries(counts).forEach(([k,v]) => { const n=document.querySelector(`[data-count="${k}"]`); if(n)n.textContent=String(v); });

    const filterCounts = {
      NO_VETO: cards.filter(card => card.dataset.veto !== '1').length,
      CLIMATE_KNOWN: cards.filter(card => (card.dataset.climateStatus || card.dataset.status || 'UNKNOWN') !== 'UNKNOWN').length,
      SOIL_KNOWN: cards.filter(card => (card.dataset.soilStatus || 'UNKNOWN') !== 'UNKNOWN').length,
      HAS_IMAGE: cards.filter(card => card.dataset.hasImage === '1').length,
      HAS_FR_NAME: cards.filter(card => card.dataset.hasFrName === '1').length,
      HAS_USES: cards.filter(card => card.dataset.hasUses === '1').length
    };
    Object.entries(filterCounts).forEach(([key,value]) => {
      const node = document.querySelector(`[data-filter-count="${key}"]`);
      if (node) node.textContent = String(value);
    });

    rebuildAlphabetFilter();

    const life=document.getElementById('life-summary-v4');
    if (life) {
      life.innerHTML=Object.entries(lifeCounts).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<label><input type="checkbox" value="${esc(k)}" ${state.lifeFilters.has(k)?'checked':''}> <span>${esc(lifeLabels[k]||k)}</span><small>${v}</small></label>`).join('') || '<p>Aucune forme biologique chargée.</p>';
      life.querySelectorAll('input').forEach(input => input.onchange=()=>{ input.checked?state.lifeFilters.add(input.value):state.lifeFilters.delete(input.value); applyFilters(); });
    }
    const use=document.getElementById('use-filter-v4');
    if (use) {
      use.innerHTML=[...useMap.entries()].sort((a,b)=>b[1].count-a[1].count).slice(0,16).map(([code,item])=>`<label><input type="checkbox" value="${esc(code)}" ${state.uses.has(code)?'checked':''}> <span>${esc(item.label)}</span><small>${item.count}</small></label>`).join('') || '<p>Aucun usage v1.8 sur les résultats chargés.</p>';
      use.querySelectorAll('input').forEach(input => input.onchange=()=>{ input.checked?state.uses.add(input.value):state.uses.delete(input.value); applyFilters(); });
    }
  }

  function applyFilters() {
    const cards=[...document.querySelectorAll('.plant-card')]; let shown=0;
    const hasActiveFilters =
      state.life !== 'ALL' ||
      state.alpha !== 'ALL' ||
      state.lifeFilters.size > 0 ||
      state.statuses.size < 4 ||
      state.uses.size > 0 ||
      state.constraints.size > 0 ||
      state.other.size > 0;
    if (!hasActiveFilters) {
      cards.forEach(card => { card.hidden = false; shown++; });
      document.querySelectorAll('.genus-group').forEach(group => {
        group.hidden = false;
        const count = group.querySelector('[data-visible-count]');
        if (count) count.textContent = String(group.querySelectorAll('.plant-card').length);
      });
      const subtitle=document.getElementById('result-subtitle');
      if(subtitle && cards.length) {
        const base=subtitle.dataset.base || '';
        subtitle.textContent=`${shown} résultat${shown>1?'s':''} visible${shown>1?'s':''}${base?` · ${base}`:''}`;
      }
      return;
    }
    cards.forEach(card => {
      // The top life-form tiles are server-side filters applied before pagination.
      // Do not re-filter them client-side, otherwise a classification mismatch could hide valid results.
      const lifeTopOk=true;
      const lifePanelOk=!state.lifeFilters.size || state.lifeFilters.has(card.dataset.lifeform || 'UNKNOWN');
      const statusOk=state.statuses.has(card.dataset.status || 'UNKNOWN');
      const useCodes=new Set(String(card.dataset.uses||'').split(',').filter(Boolean));
      const useOk=!state.uses.size || [...state.uses].every(code=>useCodes.has(code));
      const constraintOk=[...state.constraints].every(code => {
        if(code==='NO_VETO') return card.dataset.veto!=='1';
        if(code==='CLIMATE_KNOWN') return (card.dataset.climateStatus || card.dataset.status || 'UNKNOWN')!=='UNKNOWN';
        if(code==='SOIL_KNOWN') return (card.dataset.soilStatus || 'UNKNOWN')!=='UNKNOWN';
        return true;
      });
      const otherOk=[...state.other].every(code => {
        if(code==='HAS_IMAGE') return card.dataset.hasImage==='1';
        if(code==='HAS_FR_NAME') return card.dataset.hasFrName==='1';
        if(code==='HAS_USES') return card.dataset.hasUses==='1';
        return true;
      });
      const visible=lifeTopOk && lifePanelOk && statusOk && useOk && constraintOk && otherOk;
      card.hidden=!visible; if(visible) shown++;
    });
    document.querySelectorAll('.genus-group').forEach(group => {
      const visible=[...group.querySelectorAll('.plant-card')].filter(card => !card.hidden).length;
      const genusLetter=String(group.dataset.genus || '').trim().charAt(0).toUpperCase();
      const alphaOk=state.alpha==='ALL' || genusLetter===state.alpha;
      group.hidden=visible===0 || !alphaOk;
      const count=group.querySelector('[data-visible-count]'); if(count) count.textContent=String(visible);
    });
    const subtitle=document.getElementById('result-subtitle');
    if(subtitle && cards.length) { const base=subtitle.dataset.base || ''; subtitle.textContent=`${shown} résultat${shown>1?'s':''} visible${shown>1?'s':''}${base?` · ${base}`:''}`; }
  }

  async function enrichVisibleCards() {
    if (enriching) {rerun=true;return;} enriching=true;
    try {
      const cards = [...document.querySelectorAll('.plant-card')];
      const ids = cards.map(cardTaxon).filter(Boolean);
      if (!ids.length) return;
      rebuildAlphabetFilter();
      await fetchEnrichment(ids);
      cards.forEach(decorateCard);
      rebuildDynamicFilters();
      applyFilters();
      document.body.classList.add('v18-enriched');
    } catch (error) {
      console.warn('ClimaFlora descriptive enrichment unavailable:', error);
      rebuildAlphabetFilter();
      applyFilters();
    } finally {
      enriching=false; if(rerun){rerun=false;setTimeout(enrichVisibleCards,50);}
    }
  }

  function observeResults() {
    const root = document.getElementById('results-list'); if (!root) return;
    let timer = null;
    new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(enrichVisibleCards, 80);
    }).observe(root, {childList:true,subtree:false});
  }

  function finishLayout() {
    installLifeFormChooser(); installResultsFilters(); observeResults();
    const heading=document.querySelector('.progress-step:last-child'); if(heading) heading.lastChild.textContent='Type de végétaux';
    setTimeout(enrichVisibleCards,100);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', finishLayout); else finishLayout();
})();
