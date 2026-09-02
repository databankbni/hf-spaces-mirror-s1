const state = {
  horizon: '2050', scenario: 'MEDIUM', fn: '', marker: null, map: null, meta: null, mode: 'explore',
  scientificReady: false, readiness: null, recommendationLimit: 50, recommendationStep: 50, recommendationMax: 1000
};
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const apiBase = String(window.CLIMAFLORA_CONFIG?.apiBase || 'api/v1').replace(/\/$/, '');
const apiUrl = (path) => `${apiBase}/${path}`;
const wikipediaUrl = (scientificName) => `https://fr.wikipedia.org/wiki/Special:Search?search=${encodeURIComponent(String(scientificName || ''))}&go=Go`;
const powoSearchUrl = (scientificName) => `https://powo.science.kew.org/results?q=${encodeURIComponent(String(scientificName || ''))}`;
const qwantUrl = (scientificName) => `https://www.qwant.com/?q=${encodeURIComponent(String(scientificName || ''))}`;

function setScientificAvailability(ready, readiness=null) {
  state.scientificReady = Boolean(ready); state.readiness = readiness;
  const search = $('search'); const plantSearch = $('plant-search');
  search.disabled = !state.scientificReady; plantSearch.disabled = !state.scientificReady;
  if (state.scientificReady) { search.textContent = 'Trouver les plantes'; plantSearch.textContent = 'Rechercher la plante'; showWarning([]); return; }
  const phase = readiness?.master?.phase || 'initialisation';
  const masterPresent = Boolean(readiness?.master?.present || readiness?.master?.master_present);
  const climateReady = Boolean(readiness?.climate?.ready); const plantsReady = Boolean(readiness?.plants?.scientific_ready);
  search.textContent = 'Moteur scientifique en préparation'; plantSearch.textContent = 'Moteur scientifique en préparation';
  $('result-title').textContent = 'Initialisation scientifique en cours';
  $('result-subtitle').textContent = `Base maître : ${masterPresent ? 'chargée' : phase} · CHELSA : ${climateReady ? 'configuré' : 'en attente'} · enveloppes végétales : ${plantsReady ? 'validées' : 'en construction'}`;
  $('results-list').innerHTML = '<div class="empty">Initialisation en cours…</div>';
  showWarning([]);
}

async function loadReadiness() {
  try {
    const response = await fetch(apiUrl('readiness'), {cache: 'no-store'}); if (!response.ok) throw new Error(`readiness ${response.status}`);
    const readiness = await response.json(); setScientificAvailability(Boolean(readiness.ready && readiness.scientific_ready), readiness);
  } catch (error) { setScientificAvailability(false, null); showWarning([`Le moteur scientifique ne répond pas encore (${error.message}).`]); }
}

function statusLabel(status) { return {GREEN:'Favorable', ORANGE:'Sous contrainte', RED:'À risque', UNKNOWN:'Inconnu'}[status] || status; }
function metric(label, value, unit='') { return `<div class="metric"><div class="v">${value == null ? '—' : esc(value)}${value == null ? '' : unit}</div><div class="k">${esc(label)}</div></div>`; }
function currentCoords() { return {lat: Number($('lat').value), lon: Number($('lon').value)}; }
function setPoint(lat, lon, pan=false) {
  lat = Math.max(-90, Math.min(90, Number(lat))); lon = Math.max(-180, Math.min(180, Number(lon)));
  $('lat').value = lat.toFixed(4); $('lon').value = lon.toFixed(4); if (state.marker) state.marker.setLatLng([lat, lon]);
  if (pan && state.map) state.map.setView([lat, lon], Math.max(state.map.getZoom(), 7));
}
function showWarning(messages=[]) { if (messages.length) { $('warning').textContent = messages.join(' '); $('warning').classList.remove('hidden'); } else $('warning').classList.add('hidden'); }

function climateSummary(climate) {
  const v = climate.variables || {};
  $('climate-summary').innerHTML = [
    metric('Temp. annuelle', v.bio01, ' °C'), metric('Mois le + chaud', v.bio05, ' °C'), metric('Mois le + froid', v.bio06, ' °C'),
    metric('Précipitations', v.bio12, ' mm'), metric('Saisonnalité pluie', v.bio15, ''), metric('Scénario', climate.scenario, '')
  ].join('');
  $('climate-source').textContent = `${climate.provider} · ${climate.period}`;
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

function plantCard(p) {
  const climateComp = (p.components || []).map(c => `<div class="component"><span class="muted">${esc(c.variable)}</span><span>${c.value == null ? '—' : esc(c.value)}</span><span class="status ${esc(c.status)}">${esc(c.status)}</span></div>`).join('');
  const soilComp = (p.soil?.components || []).map(c => `<div class="component"><span class="muted">${esc(c.variable)}</span><span>${c.value == null ? '—' : esc(c.value)}</span><span class="status ${esc(c.status)}">${esc(c.status)}</span></div>`).join('');
  const funcs = (p.functions || []).map(f => `<span>${esc(f)}</span>`).join('');
  const veto = p.regulatory_veto ? `<div class="veto">Veto distinct de la compatibilité${p.regulatory_reason ? ` · ${esc(p.regulatory_reason)}` : ''}</div>` : '';
  const soilScore = p.soil?.score == null ? '—' : esc(p.soil.score);
  const soilStatus = p.soil?.status || 'UNKNOWN';
  return `<article class="plant-card">
    <div class="plant-top">
      <div class="plant-identity">${imageHtml(p)}<div><div class="plant-name"><em>${esc(p.scientific_name)}</em></div><div class="common">${esc(p.common_name || '')}</div></div></div>
      <div class="plant-scores">
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
  state.meta = await response.json(); $('method-pill').textContent = `V2 · ${state.meta.method_version}`;
  $('horizons').innerHTML = state.meta.horizons.map(h => `<button class="${h.value === state.horizon ? 'active' : ''}" data-value="${esc(h.value)}">${esc(h.label)}</button>`).join('');
  $('scenario').innerHTML = state.meta.scenarios.map(s => `<option value="${esc(s.value)}" ${s.value === state.scenario ? 'selected' : ''}>${esc(s.label)} · ${esc(s.ssp)}</option>`).join('');
  $('functions').innerHTML = `<button class="active" data-value="">Toutes</button>` + state.meta.functions.map(f => `<button data-value="${esc(f.value)}">${esc(f.label)}</button>`).join('');
  document.querySelectorAll('#horizons button').forEach(btn => btn.onclick = () => { document.querySelectorAll('#horizons button').forEach(b => b.classList.remove('active')); btn.classList.add('active'); state.horizon = btn.dataset.value; });
  document.querySelectorAll('#functions button').forEach(btn => btn.onclick = () => { document.querySelectorAll('#functions button').forEach(b => b.classList.remove('active')); btn.classList.add('active'); state.fn = btn.dataset.value; });
  $('scenario').onchange = e => state.scenario = e.target.value;
  state.map = L.map('map', {worldCopyJump: true}).setView([47.16, -1.27], 5);
  L.tileLayer(state.meta.map.tile_url, {maxZoom: state.meta.map.max_zoom, attribution: state.meta.map.attribution}).addTo(state.map);
  state.marker = L.circleMarker([47.16, -1.27], {radius: 7, weight: 2, fillOpacity: .8}).addTo(state.map);
  state.map.on('click', e => setPoint(e.latlng.lat, e.latlng.lng));
}

async function searchRecommendations(loadMore=false) {
  if (!state.scientificReady) return loadReadiness();
  if (loadMore) state.recommendationLimit = Math.min(state.recommendationLimit + state.recommendationStep, state.recommendationMax); else state.recommendationLimit = state.recommendationStep;
  const btn = $('search'); btn.classList.add('loading'); btn.textContent = 'Calcul en cours…';
  const moreBtn = $('load-more'); if (moreBtn) { moreBtn.disabled = true; moreBtn.textContent = 'Chargement…'; }
  $('trajectory').classList.add('hidden');
  const params = new URLSearchParams({lat: $('lat').value, lon: $('lon').value, horizon: state.horizon, scenario: state.scenario, limit: String(state.recommendationLimit)});
  if (state.fn) params.append('function', state.fn); appendSoilParams(params);
  try {
    const response = await fetch(`${apiUrl('recommendations')}?${params}`); if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json(); const shown = data.recommendations.length;
    $('result-title').textContent = `${Number(data.climate.latitude).toFixed(3)}, ${Number(data.climate.longitude).toFixed(3)} · ${state.horizon}`;
    $('result-subtitle').textContent = `${data.evaluated_candidates} candidats évalués · ${shown} affichés · méthode ${data.method_version}`;
    climateSummary(data.climate); soilSummary(data.soil);
    const cards = shown ? data.recommendations.map(plantCard).join('') : '<div class="empty">Aucun candidat avec ces filtres.</div>';
    const canLoadMore = shown < data.evaluated_candidates && shown < state.recommendationMax;
    const remaining = Math.max(0, Math.min(state.recommendationStep, data.evaluated_candidates - shown));
    const more = canLoadMore ? `<div class="load-more-wrap"><button id="load-more" class="secondary load-more">Afficher ${remaining} de plus</button><div class="field-help">${shown} résultats affichés sur ${data.evaluated_candidates} candidats scorés.</div></div>` : (shown ? `<div class="list-end">${shown} résultats affichés.</div>` : '');
    $('results-list').innerHTML = cards + more; const next = $('load-more'); if (next) next.onclick = () => searchRecommendations(true); showWarning(data.warnings || []);
  } catch (error) { $('results-list').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`; }
  finally { btn.classList.remove('loading'); btn.textContent = 'Trouver les plantes'; }
}

async function searchPlant() {
  if (!state.scientificReady) return loadReadiness(); const q = $('plant-query').value.trim();
  if (q.length < 2) { $('plant-hits').innerHTML = '<div class="field-help">Saisissez au moins 2 caractères.</div>'; return; }
  const btn = $('plant-search'); btn.classList.add('loading'); btn.textContent = 'Recherche…';
  try {
    const response = await fetch(`${apiUrl('plants/search')}?${new URLSearchParams({q, limit:'20'})}`); if (!response.ok) throw new Error(`API ${response.status}`);
    const hits = await response.json();
    $('plant-hits').innerHTML = hits.length ? hits.map(hit => `<div class="plant-hit-row"><button class="plant-hit" data-taxon="${esc(hit.taxon_id)}">${imageHtml(hit, 'plant-hit-thumb')}<span><em>${esc(hit.scientific_name)}</em><small>${esc(hit.common_name || '')}</small></span><span>Analyser →</span></button><span class="hit-links"><a href="${esc(hit.links?.powo || powoSearchUrl(hit.scientific_name))}" target="_blank" rel="noopener noreferrer">Kew ↗</a><a href="${esc(hit.links?.qwant || qwantUrl(hit.scientific_name))}" target="_blank" rel="noopener noreferrer">Qwant ↗</a></span></div>`).join('') : '<div class="field-help">Aucune plante trouvée.</div>';
  } catch (error) { $('plant-hits').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`; }
  finally { btn.classList.remove('loading'); btn.textContent = 'Rechercher la plante'; }
}

function trajectoryHtml(data) {
  const points = data.points.map(point => {
    const result = point.result; const score = result.overall_score == null ? null : Number(result.overall_score); const width = score == null ? 0 : Math.max(0, Math.min(100, score));
    const veto = result.regulatory_veto ? '<span class="mini-veto">veto</span>' : '';
    return `<div class="trajectory-row"><div class="trajectory-year">${esc(point.horizon === 'NOW' ? 'Actuel' : point.horizon)}</div><div class="trajectory-bar"><span class="bar ${esc(result.overall_status)}" style="width:${width}%"></span></div><div class="trajectory-score">${score == null ? '—' : score.toFixed(0)} ${veto}</div></div>`;
  }).join('');
  const powo = data.links?.powo || powoSearchUrl(data.scientific_name); const wiki = data.links?.wikipedia || wikipediaUrl(data.scientific_name); const qwant = data.links?.qwant || qwantUrl(data.scientific_name);
  return `<div class="trajectory-head"><div class="trajectory-identity">${imageHtml(data)}<div><div class="eyebrow">Trajectoire</div><h3><em>${esc(data.scientific_name)}</em></h3><div class="inline-links"><a href="${esc(powo)}" target="_blank" rel="noopener noreferrer">POWO / Kew ↗</a><a href="${esc(wiki)}" target="_blank" rel="noopener noreferrer">Wikipédia ↗</a><a href="${esc(qwant)}" target="_blank" rel="noopener noreferrer">Qwant ↗</a></div></div></div><div class="source-badge">${esc(data.scenario)}</div></div><p>Compatibilité climatique par horizon. Le sol local est stable entre horizons et reste évalué séparément lorsqu’une préférence édaphique sourcée existe.</p>${points}`;
}

async function loadTrajectory(taxonId) {
  if (!state.scientificReady) return loadReadiness(); const {lat, lon} = currentCoords();
  $('trajectory').innerHTML = '<div class="empty">Calcul de la trajectoire…</div>'; $('trajectory').classList.remove('hidden');
  try {
    const params = new URLSearchParams({lat, lon, scenario: state.scenario}); appendSoilParams(params);
    const response = await fetch(`${apiUrl(`plants/${encodeURIComponent(taxonId)}/trajectory`)}?${params}`); if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json(); $('trajectory').innerHTML = trajectoryHtml(data); $('result-title').textContent = data.scientific_name;
    $('result-subtitle').textContent = `Trajectoire complète · ${lat.toFixed(3)}, ${lon.toFixed(3)}`; $('results-list').innerHTML = '';
    climateSummary(data.points.find(p => p.horizon === state.horizon)?.climate || data.points[0].climate); soilSummary(data.soil);
  } catch (error) { $('trajectory').innerHTML = `<div class="warning">Erreur : ${esc(error.message)}</div>`; }
}

function switchMode(mode) {
  state.mode = mode; document.querySelectorAll('.mode-tabs button').forEach(button => button.classList.toggle('active', button.dataset.mode === mode));
  $('explore-controls').classList.toggle('hidden', mode !== 'explore'); $('plant-controls').classList.toggle('hidden', mode !== 'plant'); $('trajectory').classList.add('hidden');
  $('results-list').innerHTML = `<div class="empty">${mode === 'explore' ? 'Lancez une analyse pour classer les plantes.' : 'Recherchez une plante puis calculez sa trajectoire.'}</div>`;
}

$('lat').addEventListener('change', () => setPoint($('lat').value, $('lon').value)); $('lon').addEventListener('change', () => setPoint($('lat').value, $('lon').value));
$('search').onclick = searchRecommendations; $('plant-search').onclick = searchPlant; $('plant-query').addEventListener('keydown', event => { if (event.key === 'Enter') searchPlant(); });
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
document.addEventListener('click', event => { const target = event.target.closest('[data-taxon]'); if (target && (target.classList.contains('trajectory-btn') || target.classList.contains('plant-hit'))) loadTrajectory(target.dataset.taxon); });

(async () => { try { await loadMeta(); await loadReadiness(); } catch (error) { $('results-list').innerHTML = `<div class="warning">Initialisation impossible : ${esc(error.message)}</div>`; } })();
