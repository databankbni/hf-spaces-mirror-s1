// ClimaFlora public frontend configuration.
// The OVH static frontend talks directly to the production Hugging Face API.
window.CLIMAFLORA_CONFIG = Object.freeze({
  apiBase: 'https://gyamotab-climaflora-engine.hf.space/api/v1'
});

// Small production hotfix layer: keeps Leaflet below the application chrome.
(() => {
  const href = 'static/hotfix-20260820.css?rev=20260820-1158';
  if (!document.querySelector(`link[href="${href}"]`)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }
})();

// Exhaustive search/facets v1 is loaded after the existing UI controllers so it can
// replace recommendation discovery without disturbing media and card enrichment.
(() => {
  const cssHref = 'static/search-v1.css?rev=20260822-2';
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = cssHref;
    document.head.appendChild(link);
  }

  const install = () => setTimeout(() => {
    if (document.querySelector('script[data-climaflora-search-v1]')) return;
    const script = document.createElement('script');
    script.src = 'static/search-v1.js?rev=20260822-2';
    script.dataset.climafloraSearchV1 = '1';
    script.onload = () => {
      if (document.querySelector('script[data-climaflora-funnel-v1]')) return;
      const funnel = document.createElement('script');
      funnel.src = 'static/funnel-v1.js?rev=20260822-2';
      funnel.dataset.climafloraFunnelV1 = '1';
      document.body.appendChild(funnel);
    };
    document.body.appendChild(script);
  }, 0);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once: true});
  } else {
    install();
  }
})();
