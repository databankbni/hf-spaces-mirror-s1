(() => {
  'use strict';
  const apiBase = String(window.CLIMAFLORA_CONFIG?.apiBase || 'api/v1').replace(/\/$/, '');
  const cache = new Map();
  let loading = false, rerun = false;
  const lifeLabels = {TREE:'Arbre',SHRUB:'Arbuste',HERB:'Herbacée',CLIMBER:'Grimpante',PALM:'Palmier',OTHER:'Autre',UNKNOWN:'Non renseigné'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const cardTaxon = card => card.querySelector('[data-taxon]')?.dataset.taxon || '';
  const scientificName = card => card.querySelector('.plant-name')?.textContent?.trim() || '';
  const commonName = card => card.querySelector('.common')?.textContent?.trim() || '';

  function classifyLifeForm(value) {
    const v = String(value || '').toLowerCase();
    if (!v) return 'UNKNOWN';
    if (/palm|arecaceae|palmae/.test(v)) return 'PALM';
    if (/climb|liana|vine|grimp/.test(v)) return 'CLIMBER';
    if (/shrub|bush|arbust/.test(v)) return 'SHRUB';
    if (/tree|arbores|arbre/.test(v)) return 'TREE';
    if (/herb|forb|graminoid|grass|herbac|annual|biennial|perennial|geophyte|epiphyte|lithophyte|helophyte|hydrophyte|bamboo/.test(v)) return 'HERB';
    return 'OTHER';
  }

  function createDrawer() {
    if (document.getElementById('media-v1-drawer')) return;
    const overlay = document.createElement('div');
    overlay.id = 'media-v1-overlay'; overlay.className = 'media-v1-overlay'; overlay.hidden = true;
    overlay.innerHTML = `<aside id="media-v1-drawer" class="media-v1-drawer" role="dialog" aria-modal="true" aria-labelledby="media-v1-title"><button type="button" class="media-v1-close" aria-label="Fermer">×</button><div id="media-v1-content"></div></aside>`;
    document.body.appendChild(overlay);
    const close = () => { overlay.hidden = true; document.body.classList.remove('media-v1-open'); };
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.querySelector('.media-v1-close').addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !overlay.hidden) close(); });
  }

  function fallbackThumb(node) {
    if (!node) return null;
    const replacement = document.createElement('div');
    replacement.className = 'plant-thumb plant-thumb-placeholder media-v1-fallback media-v1-brand-fallback';
    replacement.setAttribute('role','img'); replacement.setAttribute('aria-label','Illustration générique ClimaFlora');
    replacement.title = 'Aucune photo admissible disponible pour ce taxon';
    node.replaceWith(replacement); return replacement;
  }

  function exactImage(enrichment) {
    const image = enrichment?.image || null;
    if (!image?.thumbnail_url || !image?.source_page_url) return null;
    if (image.source_name !== 'wikimedia_commons') return null;
    if (image.display_blurred) return null; // doute taxonomique => pas d'image dans la BETA consolidée
    return image;
  }

  function openDrawer(card, image, enrichment) {
    createDrawer();
    const overlay = document.getElementById('media-v1-overlay');
    const content = document.getElementById('media-v1-content');
    const scientific = scientificName(card);
    const common = enrichment?.vernacular_name_fr || commonName(card);
    const credit = image.attribution || [image.author, image.license, 'Wikimedia Commons'].filter(Boolean).join(' · ');
    content.innerHTML = `<div class="media-v1-drawer-image"><img src="${esc(image.image_url || image.thumbnail_url)}" alt="Illustration de ${esc(scientific)}" decoding="async" /></div><div class="media-v1-drawer-body"><div class="media-v1-kicker">Illustration botanique</div><h3 id="media-v1-title"><em>${esc(scientific)}</em></h3>${common ? `<p class="media-v1-common">${esc(common)}</p>` : ''}<p class="media-v1-credit-full">Photo : ${esc(credit || 'Wikimedia Commons')}</p><a class="media-v1-source" href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">Voir la source et la licence sur Wikimedia Commons ↗</a><p class="media-v1-science-note">Cette image est illustrative. Elle n’intervient jamais dans le score ClimaFlora.</p></div>`;
    content.querySelector('img')?.addEventListener('error', e => fallbackThumb(e.currentTarget), {once:true});
    overlay.hidden = false; document.body.classList.add('media-v1-open');
  }

  function decorateText(card, data) {
    const common = card.querySelector('.common');
    if (common && data?.vernacular_name_fr) common.textContent = data.vernacular_name_fr;
    const identity = card.querySelector('.plant-identity > div:last-child');
    if (identity && !identity.querySelector('.descriptive-badges')) {
      const badges = document.createElement('div'); badges.className='descriptive-badges';
      const life = classifyLifeForm(data?.life_form);
      if (data?.life_form) badges.innerHTML += `<span title="Forme biologique documentée">${esc(lifeLabels[life] || life)}</span>`;
      (data?.uses || []).slice(0,2).forEach(use => badges.innerHTML += `<span>${esc(use.label_fr || use.label_en || use.code)}</span>`);
      if (badges.children.length) identity.appendChild(badges);
    }
    const funcs = card.querySelector('.functions');
    if (funcs && (data?.uses || []).length) {
      funcs.innerHTML = (data.uses || []).slice(0,4).map(use => `<span title="Fonction documentée · ${esc(use.source_id || '')}">${esc(use.label_fr || use.label_en || use.code)}</span>`).join('');
    }
    const top = card.querySelector('.plant-top');
    if (top && !top.querySelector('.future-favorite')) {
      const fav=document.createElement('button'); fav.type='button'; fav.disabled=true; fav.className='future-favorite'; fav.title='Favoris bientôt disponibles'; fav.textContent='♡'; top.appendChild(fav);
    }
  }

  function decorateImage(card, data) {
    const oldThumb = card.querySelector('.plant-thumb'); if (!oldThumb) return;
    const image = exactImage(data);
    if (!image) {
      if (card.dataset.mediaAsset !== 'fallback') { fallbackThumb(oldThumb); card.querySelector('.media-v1-credit')?.remove(); card.dataset.mediaAsset='fallback'; }
      return;
    }
    const key = image.asset_id || image.thumbnail_url; if (card.dataset.mediaAsset === key) return;
    const button=document.createElement('button'); button.type='button'; button.className='plant-thumb media-v1-thumb'; button.title='Ouvrir la photo et ses crédits';
    button.innerHTML=`<img src="${esc(image.thumbnail_url)}" alt="Illustration de ${esc(scientificName(card))}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />`;
    button.querySelector('img')?.addEventListener('error', () => { fallbackThumb(button); card.dataset.mediaAsset='fallback'; card.querySelector('.media-v1-credit')?.remove(); }, {once:true});
    button.addEventListener('click', () => openDrawer(card,image,data)); oldThumb.replaceWith(button);
    const identity=card.querySelector('.plant-identity > div:last-child');
    if(identity){ identity.querySelector('.media-v1-credit')?.remove(); const credit=document.createElement('div'); credit.className='media-v1-credit'; credit.innerHTML=`Photo : ${image.author ? esc(image.author)+' · ' : ''}${esc(image.license || '')} · <a href="${esc(image.source_page_url)}" target="_blank" rel="noopener noreferrer">Wikimedia Commons ↗</a>`; identity.appendChild(credit); }
    card.dataset.mediaAsset=key;
  }

  async function fetchEnrichment(ids) {
    const missing = ids.filter(id => !cache.has(id));
    for (let start=0; start<missing.length; start+=250) {
      const batch=missing.slice(start,start+250); const params=new URLSearchParams(); batch.forEach(id=>params.append('taxon_id',id));
      const response=await fetch(`${apiBase}/plants/enrichment?${params}`,{cache:'no-store'}); if(!response.ok) throw new Error(`enrichment ${response.status}`);
      const payload=await response.json(); Object.entries(payload.taxa || {}).forEach(([id,data])=>cache.set(id,data)); batch.forEach(id=>{if(!cache.has(id))cache.set(id,null);});
    }
  }

  async function enrichCards() {
    if (loading) { rerun=true; return; } loading=true;
    try {
      const cards=[...document.querySelectorAll('.plant-card')]; const ids=cards.map(cardTaxon).filter(Boolean); if(!ids.length)return;
      await fetchEnrichment(ids); cards.forEach(card=>{const data=cache.get(cardTaxon(card)); if(data){decorateText(card,data);decorateImage(card,data);} else decorateImage(card,null);});
    } catch(error){ console.warn('ClimaFlora enrichment unavailable:',error); }
    finally { loading=false; if(rerun){rerun=false;setTimeout(enrichCards,80);} }
  }

  function installViewSwitch(){
    const buttons=[...document.querySelectorAll('.view-switch button')]; if(buttons.length<2)return; const [grid,list]=buttons; grid.disabled=false;list.disabled=false;
    const apply=mode=>{const root=document.getElementById('results-list');if(!root)return;root.classList.toggle('media-v1-list-mode',mode==='list');grid.classList.toggle('active',mode==='grid');list.classList.toggle('active',mode==='list');};
    grid.addEventListener('click',()=>apply('grid')); list.addEventListener('click',()=>apply('list')); apply('grid');
  }

  function init(){ createDrawer(); installViewSwitch(); const root=document.getElementById('results-list'); if(root)new MutationObserver(()=>setTimeout(enrichCards,30)).observe(root,{childList:true,subtree:true}); setTimeout(enrichCards,120); }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
