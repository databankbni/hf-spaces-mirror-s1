const CACHE='kombaz-synth-v7';
const ASSETS=['./','./index.html','./manifest.webmanifest','./icon-192.png','./icon-512.png','./icon-180.png'];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const url=new URL(e.request.url);
  /* only ever touch the exact static app-shell files this service
     worker is meant to make available offline. Everything else —
     /config, /create-checkout-session, /verify-session, /api/*, any
     future endpoint — passes straight through untouched. Previously
     this excluded only /api/, which left /config (and any other
     non-/api/ endpoint) exposed to the cache-then-network-fallback
     logic below: a single failed/slow network request would silently
     resolve to the cached index.html instead of the real JSON
     response, which is exactly what broke Supabase config loading. */
  const isKnownAsset=ASSETS.some(a=>url.pathname===a.replace('./','/')||(a==='./'&&url.pathname==='/'));
  if(!isKnownAsset)return;
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{
    const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy)).catch(()=>{});
    return resp;
  }).catch(()=>caches.match('./index.html'))));
});
