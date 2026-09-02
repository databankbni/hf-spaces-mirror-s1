(() => {
  'use strict';

  const apiBase = String(window.CLIMAFLORA_CONFIG?.apiBase || 'api/v1').replace(/\/$/, '');
  const cache = new Map();
  let loading = false;
  let rerun = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  function cardTaxon(card) {
    return card.querySelector('[data-taxon]')?.dataset.taxon || '';
  }

  function scientificName(card) {
    return card.querySelector('.plant-name')?.textContent?.trim() || '';
  }

  function commonName(card) {
    return card.querySelector('.common')?.textContent?.trim() || '';
  }

  function ambiguityLabel(reason) {
    return {
      ambiguous_media_label: 'Identification visuelle incertaine',
      category_member_without_explicit_taxon_name: 'Image issue de la catégorie exacte du taxon, sans nom explicite dans le fichier'
    }[reason] || 'Image illustrative à confirmer';
  }

  function createDrawer() {
    if (document.getElementById('media-v1-drawer')) return;
    const overlay = document.createElement('div');
    overlay.id = 'media-v1-overlay';
    overlay.className = 'media-v1-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <aside id="media-v1-drawer" class="media-v1-drawer" role="dialog" aria-modal="true" aria-labelledby="media-v1-title">
        <button type="button" class="media-v1-close" aria-label="Fermer">×</button>
        <div id="media-v1-content"></div>
      </aside>`;
    document.body.appendChild(overlay);
    const close = () => {
      overlay.hidden = true;
      document.body.classList.remove('media-v1-open');
    };
    overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
    overlay.querySelector('.media-v1-close').addEventListener('click', close);
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !overlay.hidden) close(); });
  }

  function openDrawer(card, image, enrichment) {
    createDrawer();
    const overlay = document.getElementById('media-v1-overlay');
    const content = document.getElementById('media-v1-content');
    const scientific = scientificName(card);
    const common = enrichment?.vernacular_name_fr || commonName(card);
    const credit = image.attribution || [image.author, image.license, 'Wikimedia Commons'].filter(Boolean).join(' · ');
    const uncertain = Boolean(image.display_blurred);
    const uncertainty = uncertain ? `<p class="media-v1-uncertain-note">${esc(ambiguityLabel(image.ambiguity_reason))}. L’image est volontairement floutée.</p>` : '';
    content.innerHTML = `
      <div class="media-v1-drawer-image ${uncertain ? 'media-v1-blurred' : ''}">
        <img src="${esc(image.image_url || image.thumbnail_url)}" alt="Illustration de ${esc(scientific)}" decoding="async" />
        ${uncertain ? '<span class="media-v1-uncertain-badge">Image incertaine</span>' : ''}
      </div>
      <div class="media-v1-drawer-body">
        <div class="media-v1-kicker">Illustration botanique</div>
        <h3 id="media-v1-title"><em>${esc(scientific)}</em></h3>
        ${common ? `<p class="media-v1-common">${esc(common)}</p>` : ''}
        ${uncertainty}
        <p class="media-v1-credit-full">Photo : ${esc(credit || 'Wikimedia Commons')}</p>
        <a class="media-v1-source" href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">Voir la source et la licence sur Wikimedia Commons ↗</a>
        <p class="media-v1-science-note">Cette image est illustrative. Elle ne sert ni à l’identification botanique, ni au calcul du score ClimaFlora.</p>
      </div>`;
    const img = content.querySelector('img');
    img.addEventListener('error', () => {
      const fallback = document.createElement('div');
      fallback.className = 'media-v1-drawer-fallback media-v1-brand-fallback';
      fallback.setAttribute('aria-label', 'Illustration générique ClimaFlora');
      img.replaceWith(fallback);
    }, {once:true});
    overlay.hidden = false;
    document.body.classList.add('media-v1-open');
  }

  function fallbackThumb(node) {
    const replacement = document.createElement('div');
    replacement.className = 'plant-thumb plant-thumb-placeholder media-v1-fallback media-v1-brand-fallback';
    replacement.setAttribute('role', 'img');
    replacement.setAttribute('aria-label', 'Illustration générique ClimaFlora');
    replacement.title = 'Aucune photo admissible disponible pour ce taxon';
    node.replaceWith(replacement);
    return replacement;
  }

  function decorateCard(card, enrichment) {
    if (!card) return;
    const image = enrichment?.image || null;
    const oldThumb = card.querySelector('.plant-thumb');
    if (!oldThumb) return;

    if (!image?.thumbnail_url || !image?.source_page_url || image.source_name !== 'wikimedia_commons') {
      if (card.dataset.mediaV1Asset !== 'fallback') {
        fallbackThumb(oldThumb);
        card.querySelector('.media-v1-credit')?.remove();
        card.dataset.mediaV1Asset = 'fallback';
      }
      return;
    }
    const assetKey = `${image.asset_id || image.thumbnail_url}:${image.display_blurred ? 'blur' : 'clear'}`;
    if (card.dataset.mediaV1Asset === assetKey) return;

    const uncertain = Boolean(image.display_blurred);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `plant-thumb media-v1-thumb${uncertain ? ' media-v1-blurred' : ''}`;
    button.title = uncertain ? `${ambiguityLabel(image.ambiguity_reason)} — ouvrir la source` : 'Ouvrir la fiche image et les crédits';
    button.setAttribute('aria-label', uncertain ? 'Image incertaine, ouvrir la source et les crédits' : 'Ouvrir la source et les crédits image');
    button.innerHTML = `<img src="${esc(image.thumbnail_url)}" alt="Illustration de ${esc(scientificName(card))}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />${uncertain ? '<span class="media-v1-uncertain-badge">Incertaine</span>' : ''}`;
    const img = button.querySelector('img');
    img.addEventListener('error', () => {
      fallbackThumb(button);
      card.dataset.mediaV1Asset = 'fallback';
      card.querySelector('.media-v1-credit')?.remove();
    }, {once:true});
    button.addEventListener('click', () => openDrawer(card, image, enrichment));
    oldThumb.replaceWith(button);

    const identityText = card.querySelector('.plant-identity > div:last-child');
    if (identityText) {
      identityText.querySelector('.media-v1-credit')?.remove();
      const credit = document.createElement('div');
      credit.className = 'media-v1-credit';
      const author = image.author ? `${image.author} · ` : '';
      const uncertaintyText = uncertain ? ` · ${ambiguityLabel(image.ambiguity_reason)}` : '';
      credit.innerHTML = `Photo : ${esc(author)}${esc(image.license || '')} · <a href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">Wikimedia Commons ↗</a>${esc(uncertaintyText)}`;
      identityText.appendChild(credit);
    }
    card.dataset.mediaV1Asset = assetKey;
  }

  async function fetchEnrichment(ids) {
    const missing = ids.filter(id => !cache.has(id));
    for (let start = 0; start < missing.length; start += 250) {
      const batch = missing.slice(start, start + 250);
      const params = new URLSearchParams();
      batch.forEach(id => params.append('taxon_id', id));
      const response = await fetch(`${apiBase}/plants/enrichment?${params}`, {cache:'no-store'});
      if (!response.ok) throw new Error(`media enrichment ${response.status}`);
      const payload = await response.json();
      Object.entries(payload.taxa || {}).forEach(([id, data]) => cache.set(id, data));
      batch.forEach(id => { if (!cache.has(id)) cache.set(id, null); });
    }
  }

  async function enrichCards() {
    if (loading) { rerun = true; return; }
    loading = true;
    try {
      const cards = [...document.querySelectorAll('.plant-card')];
      const ids = cards.map(cardTaxon).filter(Boolean);
      if (!ids.length) return;
      await fetchEnrichment(ids);
      cards.forEach(card => decorateCard(card, cache.get(cardTaxon(card))));
    } catch (error) {
      console.warn('ClimaFlora media layer unavailable:', error);
      document.querySelectorAll('.plant-card').forEach(card => {
        const thumb = card.querySelector('.plant-thumb');
        if (thumb && !thumb.classList.contains('media-v1-brand-fallback')) fallbackThumb(thumb);
      });
    } finally {
      loading = false;
      if (rerun) { rerun = false; setTimeout(enrichCards, 80); }
    }
  }

  function installViewSwitch() {
    const buttons = [...document.querySelectorAll('.view-switch button')];
    if (buttons.length < 2 || buttons[0].dataset.mediaV1 === '1') return;
    const grid = buttons[0];
    const list = buttons[1];
    grid.disabled = false;
    list.disabled = false;
    grid.dataset.mediaV1 = '1';
    list.dataset.mediaV1 = '1';
    const apply = mode => {
      const root = document.getElementById('results-list');
      if (!root) return;
      root.classList.toggle('media-v1-list-mode', mode === 'list');
      grid.classList.toggle('active', mode === 'grid');
      list.classList.toggle('active', mode === 'list');
      grid.setAttribute('aria-pressed', String(mode === 'grid'));
      list.setAttribute('aria-pressed', String(mode === 'list'));
    };
    grid.addEventListener('click', () => apply('grid'));
    list.addEventListener('click', () => apply('list'));
    apply('grid');
  }

  function observeResults() {
    const root = document.getElementById('results-list');
    if (!root) return;
    new MutationObserver(() => setTimeout(enrichCards, 30)).observe(root, {childList:true, subtree:true});
  }

  function init() {
    createDrawer();
    installViewSwitch();
    observeResults();
    setTimeout(enrichCards, 120);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
