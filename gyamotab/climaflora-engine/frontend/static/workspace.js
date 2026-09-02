(() => {
  'use strict';

  const auth = () => window.CLIMAFLORA_AUTH;
  const client = () => auth()?.client;
  const plan = () => String(auth()?.plan || 'FREE').toUpperCase();
  const entitlements = () => auth()?.entitlements || {
    plan: plan(), saved_projects: plan() === 'PRO' ? 250 : plan() === 'PLUS' ? 10 : 1,
    saved_sites: plan() === 'PRO' ? 50 : plan() === 'PLUS' ? 5 : 1,
    comparisons: plan() === 'PRO' ? 20 : plan() === 'PLUS' ? 5 : 0,
    monthly_exports: plan() === 'PRO' ? 100 : plan() === 'PLUS' ? 10 : 0,
    advanced_scenarios: ['PLUS','PRO'].includes(plan()), advanced_exports: plan() === 'PRO',
    commercial_use: plan() === 'PRO', palette: ['PLUS','PRO'].includes(plan())
  };
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const selectedTaxa = new Set();
  let activeTab = 'projects';

  const overlay = document.createElement('div');
  overlay.className = 'workspace-overlay';
  overlay.hidden = true;
  overlay.innerHTML = `<section class="workspace-panel" role="dialog" aria-modal="true" aria-labelledby="workspace-title">
    <header class="workspace-head"><div><p class="auth-kicker">Mon espace ClimaFlora</p><h2 id="workspace-title">Mes projets</h2></div><button data-workspace-close aria-label="Fermer" type="button">×</button></header>
    <nav class="workspace-tabs" aria-label="Fonctionnalités du compte">
      <button data-workspace-tab="projects" type="button">Mes projets</button>
      <button data-workspace-tab="palette" type="button">Ma palette</button>
      <button data-workspace-tab="compare" type="button">Comparateur</button>
      <button data-workspace-tab="exports" type="button">Exports</button>
    </nav>
    <p class="workspace-status" data-workspace-status hidden></p><div class="workspace-body" data-workspace-body></div>
  </section>`;
  document.body.appendChild(overlay);
  const body = overlay.querySelector('[data-workspace-body]');
  const title = overlay.querySelector('#workspace-title');
  const status = overlay.querySelector('[data-workspace-status]');

  function message(text, error = false) {
    status.textContent = text; status.hidden = !text; status.classList.toggle('error', error);
  }
  function requireLogin() {
    if (auth()?.authenticated) return true;
    auth()?.open(); return false;
  }
  function requiresPaid(tab) { return ['palette','compare','exports'].includes(tab); }
  function allowed(tab) {
    const access = entitlements();
    if (tab === 'palette') return Boolean(access.palette);
    if (tab === 'compare') return Number(access.comparisons || 0) > 0;
    if (tab === 'exports') return Number(access.monthly_exports || 0) > 0;
    return true;
  }
  function upgradeView(tab) {
    const labels = {palette:'La palette personnelle', compare:'Le comparateur', exports:'Les exports'};
    body.innerHTML = `<div class="workspace-upgrade"><span>ClimaFlora Plus</span><h3>${labels[tab]} est inclus dans Plus et Pro.</h3><p>Votre recherche scientifique reste accessible. Passez à une offre supérieure pour enregistrer, comparer et exporter vos sélections.</p><a href="tarifs.html">Comparer les offres</a></div>`;
  }
  function currentSearch() {
    return {
      latitude: Number(document.getElementById('lat')?.value),
      longitude: Number(document.getElementById('lon')?.value),
      horizon: document.querySelector('#horizons button.active')?.dataset.value || '2050',
      scenario: document.getElementById('scenario')?.value || 'MEDIUM'
    };
  }
  function readableError(error) {
    const text = String(error?.message || 'Opération impossible.');
    if (/project quota/i.test(text)) return 'Vous avez atteint le nombre maximal de projets de votre offre.';
    if (/site quota/i.test(text)) return 'Vous avez atteint le nombre maximal de sites de votre offre.';
    if (/monthly export quota/i.test(text)) return 'Votre quota mensuel d’exports est atteint.';
    return text;
  }

  async function projectsView() {
    const access = entitlements();
    body.innerHTML = '<p>Chargement des projets…</p>';
    const {data, error} = await client().from('climaflora_projects').select('*').order('updated_at', {ascending:false});
    if (error) throw error;
    const rows = Array.isArray(data) ? data : [];
    body.innerHTML = `<div class="workspace-toolbar"><div><strong>${rows.length} / ${Number(access.saved_projects || 1)} projets</strong><small>${Number(access.saved_sites || 1)} site${Number(access.saved_sites || 1) > 1 ? 's' : ''} maximum</small></div><button data-project-save type="button">Enregistrer la recherche actuelle</button></div>
      <div class="workspace-projects">${rows.length ? rows.map(project => `<article><div><strong>${esc(project.name)}</strong><span>${Number(project.latitude).toFixed(4)}, ${Number(project.longitude).toFixed(4)} · ${esc(project.horizon || '2050')}</span></div><div><button data-project-load="${esc(project.id)}" type="button">Ouvrir</button><button class="danger" data-project-delete="${esc(project.id)}" type="button">Supprimer</button></div></article>`).join('') : '<p class="workspace-empty">Aucun projet enregistré.</p>'}</div>`;
    body.querySelector('[data-project-save]')?.addEventListener('click', saveProject);
    body.querySelectorAll('[data-project-load]').forEach(button => button.addEventListener('click', () => loadProject(rows.find(row => row.id === button.dataset.projectLoad))));
    body.querySelectorAll('[data-project-delete]').forEach(button => button.addEventListener('click', async () => {
      if (!confirm('Supprimer ce projet ?')) return;
      const {error: deleteError} = await client().from('climaflora_projects').delete().eq('id', button.dataset.projectDelete);
      if (deleteError) throw deleteError; await projectsView();
    }));
  }
  async function saveProject() {
    const name = prompt('Nom du projet :', `Projet ${new Date().toLocaleDateString('fr-FR')}`)?.trim();
    if (!name) return;
    const values = {...currentSearch(), name, user_id:auth().session.user.id};
    const {error} = await client().from('climaflora_projects').insert(values);
    if (error) throw error; message('Projet enregistré.'); await projectsView();
  }
  function loadProject(project) {
    if (!project) return;
    window.CLIMAFLORA_SEARCH_V2?.resetSearch();
    const lat = document.getElementById('lat'); const lon = document.getElementById('lon');
    if (lat) { lat.value = project.latitude; lat.dispatchEvent(new Event('change', {bubbles:true})); }
    if (lon) { lon.value = project.longitude; lon.dispatchEvent(new Event('change', {bubbles:true})); }
    document.querySelector(`#horizons button[data-value="${CSS.escape(project.horizon || '2050')}"]`)?.click();
    const scenario = document.getElementById('scenario');
    if (scenario && project.scenario) { scenario.value = project.scenario; scenario.dispatchEvent(new Event('change', {bubbles:true})); }
    close(); document.getElementById('explorer')?.scrollIntoView({behavior:'smooth'});
  }

  async function paletteView() {
    body.innerHTML = '<p>Chargement de la palette…</p>';
    const {data, error} = await client().from('climaflora_palette_items').select('*').order('created_at', {ascending:false});
    if (error) throw error;
    const rows = Array.isArray(data) ? data : [];
    body.innerHTML = `<div class="workspace-toolbar"><div><strong>${rows.length} plante${rows.length > 1 ? 's' : ''}</strong><small>Sélectionnez-en pour les comparer.</small></div><button data-compare-selected type="button">Comparer la sélection</button></div>
      <div class="workspace-palette">${rows.length ? rows.map(item => `<article><label><input type="checkbox" data-palette-select="${esc(item.taxon_id)}" ${selectedTaxa.has(item.taxon_id) ? 'checked' : ''}><span><em>${esc(item.scientific_name || item.taxon_id)}</em><small>${esc(item.notes || '')}</small></span></label><button class="danger" data-palette-delete="${esc(item.id)}" type="button">Retirer</button></article>`).join('') : '<p class="workspace-empty">Ajoutez des plantes depuis les résultats de recherche.</p>'}</div>`;
    body.querySelectorAll('[data-palette-select]').forEach(input => input.addEventListener('change', () => input.checked ? selectedTaxa.add(input.dataset.paletteSelect) : selectedTaxa.delete(input.dataset.paletteSelect)));
    body.querySelector('[data-compare-selected]')?.addEventListener('click', () => open('compare'));
    body.querySelectorAll('[data-palette-delete]').forEach(button => button.addEventListener('click', async () => {
      const {error: deleteError} = await client().from('climaflora_palette_items').delete().eq('id', button.dataset.paletteDelete);
      if (deleteError) throw deleteError; await paletteView(); decorateCards();
    }));
  }

  async function compareView() {
    const limit = Number(entitlements().comparisons || 0);
    const {data, error} = await client().from('climaflora_palette_items').select('taxon_id,scientific_name,notes').order('created_at');
    if (error) throw error;
    const all = Array.isArray(data) ? data : [];
    const picked = all.filter(item => selectedTaxa.has(item.taxon_id)).slice(0, limit);
    if (selectedTaxa.size > limit) message(`Votre offre permet de comparer ${limit} plantes à la fois.`, true);
    body.innerHTML = `<div class="workspace-toolbar"><div><strong>${picked.length} / ${limit} plantes</strong><small>Sélection depuis votre palette</small></div><button data-comparison-save type="button" ${picked.length < 2 ? 'disabled' : ''}>Enregistrer</button></div>
      ${picked.length ? `<div class="workspace-comparison">${picked.map(item => {
        const card = document.querySelector(`.plant-card[data-workspace-taxon="${CSS.escape(item.taxon_id)}"]`);
        return `<article><em>${esc(item.scientific_name || item.taxon_id)}</em><dl><div><dt>Score global</dt><dd>${esc(card?.dataset.workspaceGlobal || '—')}</dd></div><div><dt>Climat</dt><dd>${esc(card?.dataset.climateScore || '—')}</dd></div><div><dt>Sol</dt><dd>${esc(card?.dataset.soilScore || '—')}</dd></div></dl></article>`;
      }).join('')}</div>` : '<p class="workspace-empty">Choisissez au moins deux plantes dans « Ma palette ».</p>'}`;
    body.querySelector('[data-comparison-save]')?.addEventListener('click', async () => {
      const name = prompt('Nom de la comparaison :', 'Ma comparaison')?.trim(); if (!name) return;
      const {error: saveError} = await client().from('climaflora_comparisons').insert({user_id:auth().session.user.id, name, taxon_ids:picked.map(item => item.taxon_id)});
      if (saveError) throw saveError; message('Comparaison enregistrée.');
    });
  }

  async function exportsView() {
    const access = entitlements();
    body.innerHTML = `<div class="workspace-export"><h3>Exporter la sélection affichée</h3><p>${Number(access.monthly_exports || 0)} exports par mois avec votre offre.</p><button data-export-csv type="button">Télécharger en CSV</button><button data-export-print type="button" ${access.advanced_exports ? '' : 'disabled'}>Rapport imprimable Pro</button>${access.advanced_exports ? '' : '<small>Le rapport imprimable avec usage client est réservé à Pro.</small>'}</div>`;
    body.querySelector('[data-export-csv]').addEventListener('click', exportCsv);
    body.querySelector('[data-export-print]').addEventListener('click', async () => { await recordExport('PRINT'); window.print(); });
  }
  function visibleRows() {
    return [...document.querySelectorAll('.plant-card')].filter(card => card.offsetParent !== null).map(card => ({
      taxon:card.dataset.workspaceTaxon || '', scientific_name:card.dataset.workspaceName || '',
      global:card.dataset.workspaceGlobal || '', climate:card.dataset.climateScore || '', soil:card.dataset.soilScore || ''
    }));
  }
  async function recordExport(kind) {
    const {data, error} = await client().rpc('climaflora_record_export', {p_kind:kind});
    if (error) throw error; message(`Export autorisé · ${data.remaining} restant${data.remaining > 1 ? 's' : ''} ce mois-ci.`); return data;
  }
  async function exportCsv() {
    const rows = visibleRows(); if (!rows.length) throw new Error('Lancez une recherche avant d’exporter.');
    await recordExport('CSV');
    const quote = value => `"${String(value).replaceAll('"','""')}"`;
    const csv = ['taxon_id;nom_scientifique;score_global;score_climat;score_sol', ...rows.map(row => Object.values(row).map(quote).join(';'))].join('\n');
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob(['\ufeff', csv], {type:'text/csv;charset=utf-8'}));
    link.download = `climaflora-${new Date().toISOString().slice(0,10)}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  async function render() {
    message('');
    overlay.querySelectorAll('[data-workspace-tab]').forEach(button => button.classList.toggle('active', button.dataset.workspaceTab === activeTab));
    title.textContent = {projects:'Mes projets',palette:'Ma palette',compare:'Comparateur',exports:'Exports'}[activeTab];
    if (requiresPaid(activeTab) && !allowed(activeTab)) return upgradeView(activeTab);
    try {
      if (activeTab === 'projects') await projectsView();
      if (activeTab === 'palette') await paletteView();
      if (activeTab === 'compare') await compareView();
      if (activeTab === 'exports') await exportsView();
    } catch (error) { message(readableError(error), true); }
  }
  function open(tab = 'projects') {
    if (!requireLogin()) return;
    activeTab = tab; overlay.hidden = false; document.body.classList.add('workspace-open'); render();
  }
  function close() { overlay.hidden = true; document.body.classList.remove('workspace-open'); }

  function syncNavigation() {
    const signedIn = Boolean(auth()?.authenticated); const access = entitlements();
    document.querySelectorAll('[data-workspace-nav]').forEach(button => {
      const tab = button.dataset.workspaceNav; button.disabled = false;
      const small = button.querySelector('small');
      if (small) small.textContent = !signedIn ? 'Connexion' : (requiresPaid(tab) && !allowed(tab) ? 'Plus' : 'Ouvrir');
      button.dataset.locked = String(signedIn && requiresPaid(tab) && !allowed(tab));
    });
    document.querySelectorAll('#horizons button[data-value="2070"],#horizons button[data-value="2100"]').forEach(button => {
      button.classList.toggle('subscription-locked', !access.advanced_scenarios);
      button.setAttribute('aria-label', access.advanced_scenarios ? button.textContent : `${button.textContent} · inclus dans Plus`);
    });
    decorateCards();
  }
  function decorateCards() {
    document.querySelectorAll('.plant-card').forEach(card => {
      const taxon = card.querySelector('[data-taxon]')?.dataset.taxon; if (!taxon) return;
      card.dataset.workspaceTaxon = taxon;
      card.dataset.workspaceName = card.querySelector('.plant-name em')?.textContent?.trim() || taxon;
      card.dataset.workspaceGlobal = card.querySelector('.main-score .score')?.textContent?.trim() || '';
      const actions = card.querySelector('.card-actions'); if (!actions || actions.querySelector('[data-palette-add]')) return;
      actions.insertAdjacentHTML('afterbegin', `<button class="secondary" data-palette-add="${esc(taxon)}" type="button">♡ Palette</button><button class="secondary" data-compare-add="${esc(taxon)}" type="button">⇄ Comparer</button>`);
    });
  }
  async function addToPalette(button, compareAfter = false) {
    if (!requireLogin()) return;
    if (!allowed('palette')) return open('palette');
    const taxon = button.dataset.paletteAdd || button.dataset.compareAdd;
    const card = button.closest('.plant-card');
    const {data: existing, error: lookupError} = await client().from('climaflora_palette_items').select('id').eq('taxon_id', taxon).is('project_id', null).maybeSingle();
    if (lookupError) throw lookupError;
    if (!existing) {
      const {error} = await client().from('climaflora_palette_items').insert({user_id:auth().session.user.id, taxon_id:taxon, scientific_name:card?.dataset.workspaceName || taxon});
      if (error && error.code !== '23505') throw error;
    }
    button.textContent = '✓ Ajoutée';
    if (compareAfter) { selectedTaxa.add(taxon); open('compare'); }
  }

  overlay.querySelector('[data-workspace-close]').addEventListener('click', close);
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  overlay.querySelectorAll('[data-workspace-tab]').forEach(button => button.addEventListener('click', () => { activeTab = button.dataset.workspaceTab; render(); }));
  document.addEventListener('click', event => {
    const nav = event.target.closest('[data-workspace-nav]'); if (nav) return open(nav.dataset.workspaceNav);
    const palette = event.target.closest('[data-palette-add]'); if (palette) addToPalette(palette).catch(error => alert(readableError(error)));
    const compare = event.target.closest('[data-compare-add]'); if (compare) addToPalette(compare, true).catch(error => alert(readableError(error)));
  });
  new MutationObserver(decorateCards).observe(document.getElementById('results-list'), {childList:true, subtree:true});
  window.addEventListener('climaflora:auth-changed', syncNavigation);
  window.addEventListener('climaflora:meta-loaded', syncNavigation);
  window.CLIMAFLORA_ACCESS = {open, canUseHorizon:value => !['2070','2100'].includes(String(value)) || Boolean(entitlements().advanced_scenarios)};
  syncNavigation();
})();
