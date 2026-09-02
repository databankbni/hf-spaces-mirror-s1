(() => {
  'use strict';

  const apiBase = String(window.CLIMAFLORA_CONFIG?.apiBase || 'api/v1').replace(/\/$/, '');
  const acceptedSources = new Set(['plantnet_gbif', 'atlas_living_australia_apii', 'dryades_flora_italia', 'world_flora_online', 'wikimedia_commons']);
  const sourceLabels = {
    plantnet_gbif: 'Pl@ntNet / GBIF',
    atlas_living_australia_apii: 'Australian Plant Image Index / ALA',
    dryades_flora_italia: 'Dryades / Flora d’Italia',
    world_flora_online: 'World Flora Online',
    wikimedia_commons: 'Wikimedia Commons'
  };
  const cache = new Map();
  let loading = false;
  let rerun = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  function taxonId(card) {
    return card.querySelector('[data-taxon]')?.dataset.taxon || card.dataset.taxon || '';
  }

  function scientificName(card) {
    return card.querySelector('.plant-name')?.textContent?.trim() || '';
  }

  function sourceLabel(image) {
    return sourceLabels[image?.source_name] || 'Source botanique';
  }

  function photoSubject(card, image) {
    if (image?.taxonomic_fallback && image?.illustrated_taxon_name) return image.illustrated_taxon_name;
    return scientificName(card);
  }

  function fallbackPrefix(image) {
    if (!image?.taxonomic_fallback || !image?.illustrated_taxon_name) return '';
    return `Photo de l’espèce de référence ${image.illustrated_taxon_name}`;
  }

  function validImage(data) {
    const image = data?.image || null;
    if (!image?.thumbnail_url || !image?.image_url || !image?.source_page_url) return null;
    if (!acceptedSources.has(image.source_name)) return null;
    if (!/^https:\/\//i.test(image.thumbnail_url) || !/^https:\/\//i.test(image.image_url)) return null;
    return image;
  }

  function fallbackThumb(node) {
    if (!node) return null;
    const replacement = document.createElement('div');
    replacement.className = 'plant-thumb plant-thumb-placeholder media-v2-fallback';
    replacement.setAttribute('role', 'img');
    replacement.setAttribute('aria-label', 'Aucune photographie disponible');
    replacement.title = 'Aucune photographie admissible disponible pour ce taxon';
    replacement.textContent = '🌿';
    node.replaceWith(replacement);
    return replacement;
  }

  function createDrawer() {
    if (document.getElementById('media-v2-overlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'media-v2-overlay';
    overlay.className = 'media-v2-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <aside class="media-v2-drawer" role="dialog" aria-modal="true" aria-labelledby="media-v2-title">
        <button type="button" class="media-v2-close" aria-label="Fermer">×</button>
        <div id="media-v2-content"></div>
      </aside>`;
    document.body.appendChild(overlay);
    const close = () => {
      overlay.hidden = true;
      document.body.classList.remove('media-v2-open');
    };
    overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
    overlay.querySelector('.media-v2-close')?.addEventListener('click', close);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !overlay.hidden) close();
    });
  }

  function openDrawer(card, image) {
    createDrawer();
    const overlay = document.getElementById('media-v2-overlay');
    const content = document.getElementById('media-v2-content');
    if (!overlay || !content) return;
    const source = sourceLabel(image);
    const credit = image.attribution || [image.author, image.license, source].filter(Boolean).join(' · ');
    const fallbackNote = fallbackPrefix(image);
    content.innerHTML = `
      <div class="media-v2-drawer-image">
        <img src="${esc(image.image_url)}" alt="Photographie de ${esc(photoSubject(card, image))}" decoding="async" referrerpolicy="no-referrer" />
      </div>
      <div class="media-v2-drawer-body">
        <div class="media-v2-kicker">Illustration botanique</div>
        <h3 id="media-v2-title"><em>${esc(scientificName(card))}</em></h3>
        ${fallbackNote ? `<p class="media-v2-credit-full"><strong>${esc(fallbackNote)}</strong> — cette photo illustre l’espèce parente et non le taxon infraspécifique exact.</p>` : ''}
        <p class="media-v2-credit-full">Photo : ${esc(credit)}</p>
        <a class="media-v2-source" href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">Voir la source et la licence — ${esc(source)} ↗</a>
        <p class="media-v2-science-note">Cette image est illustrative. Elle n’intervient jamais dans le calcul du score ClimaFlora.</p>
      </div>`;
    content.querySelector('img')?.addEventListener('error', event => fallbackThumb(event.currentTarget), {once: true});
    overlay.hidden = false;
    document.body.classList.add('media-v2-open');
  }

  function decorateCard(card, data) {
    if (!card) return;
    const oldThumb = card.querySelector('.plant-thumb');
    if (!oldThumb) return;
    const image = validImage(data);
    if (!image) {
      if (card.dataset.mediaV2Asset !== 'fallback') {
        fallbackThumb(oldThumb);
        card.querySelector('.media-v2-credit')?.remove();
        card.dataset.mediaV2Asset = 'fallback';
      }
      return;
    }
    const key = image.asset_id || image.thumbnail_url;
    if (card.dataset.mediaV2Asset === key) return;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'plant-thumb media-v2-thumb';
    const fallbackNote = fallbackPrefix(image);
    button.title = fallbackNote || 'Ouvrir la photo, sa source et sa licence';
    button.setAttribute('aria-label', fallbackNote ? `${fallbackNote}, ouvrir les crédits` : `Photo ${sourceLabel(image)}, ouvrir les crédits`);
    button.innerHTML = `<img src="${esc(image.thumbnail_url)}" alt="Photographie de ${esc(photoSubject(card, image))}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />`;
    button.querySelector('img')?.addEventListener('error', () => {
      fallbackThumb(button);
      card.querySelector('.media-v2-credit')?.remove();
      card.dataset.mediaV2Asset = 'fallback';
    }, {once: true});
    button.addEventListener('click', () => openDrawer(card, image));
    oldThumb.replaceWith(button);

    const identity = card.querySelector('.plant-identity > div:last-child');
    if (identity) {
      identity.querySelector('.media-v2-credit')?.remove();
      const credit = document.createElement('div');
      credit.className = 'media-v2-credit';
      const parent = fallbackNote ? `${esc(fallbackNote)} · ` : '';
      credit.innerHTML = `${parent}${image.author ? `${esc(image.author)} · ` : ''}${esc(image.license || '')} · <a href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">${esc(sourceLabel(image))} ↗</a>`;
      identity.appendChild(credit);
    }
    card.dataset.mediaV2Asset = key;
  }

  async function fetchEnrichment(ids) {
    const missing = ids.filter(id => !cache.has(id));
    for (let start = 0; start < missing.length; start += 250) {
      const batch = missing.slice(start, start + 250);
      const params = new URLSearchParams();
      batch.forEach(id => params.append('taxon_id', id));
      const response = await fetch(`${apiBase}/plants/enrichment?${params}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`media v2 enrichment ${response.status}`);
      const payload = await response.json();
      Object.entries(payload.taxa || {}).forEach(([id, data]) => cache.set(id, data));
      batch.forEach(id => { if (!cache.has(id)) cache.set(id, null); });
    }
  }

  async function enrichCards() {
    if (loading) {
      rerun = true;
      return;
    }
    loading = true;
    try {
      const cards = [...document.querySelectorAll('.plant-card')];
      const ids = [...new Set(cards.map(taxonId).filter(Boolean))];
      if (!ids.length) return;
      await fetchEnrichment(ids);
      cards.forEach(card => decorateCard(card, cache.get(taxonId(card))));
    } catch (error) {
      console.warn('ClimaFlora Media v2 unavailable:', error);
    } finally {
      loading = false;
      if (rerun) {
        rerun = false;
        setTimeout(enrichCards, 80);
      }
    }
  }

  function init() {
    createDrawer();
    const root = document.getElementById('results-list');
    if (root) {
      new MutationObserver(() => setTimeout(enrichCards, 30)).observe(root, {childList: true, subtree: true});
    }
    setTimeout(enrichCards, 120);
  }

  window.CLIMAFLORA_MEDIA_V2 = {refresh: enrichCards};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
