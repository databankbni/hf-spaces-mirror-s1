// ClimaFlora public frontend configuration.
window.CLIMAFLORA_CONFIG = Object.freeze({
  apiBase: 'https://gyamotab-climaflora-engine.hf.space/api/v1',
  sostagoraLoginUrl: 'https://shugoan.com/wp-admin/admin-post.php?action=climaflora_sostagora_start',
  supabaseUrl: 'https://haclvcuxadvuigtefeqz.supabase.co',
  supabasePublishableKey: 'sb_publishable_nmZ0ruh9PieRqbP3oJll6g_fDZzaIYe'
});

// Media v2 is loaded from the same static frontend package. Keeping this
// bootstrap here avoids coupling image enrichment to scientific search code.
(() => {
  const version = 'media-v2-3-wikimedia-p18-20260825';
  if (!document.querySelector('link[data-climaflora-media-v2]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `static/media-v2.css?v=${version}`;
    link.dataset.climafloraMediaV2 = '1';
    document.head.appendChild(link);
  }
  if (!document.querySelector('script[data-climaflora-media-v2]')) {
    const script = document.createElement('script');
    script.src = `static/media-v2.js?v=${version}`;
    script.defer = true;
    script.dataset.climafloraMediaV2 = '1';
    document.head.appendChild(script);
  }
})();
