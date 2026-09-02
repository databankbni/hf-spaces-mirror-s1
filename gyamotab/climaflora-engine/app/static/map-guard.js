(() => {
  'use strict';

  function ensureMap() {
    const target = document.getElementById('map');
    if (!target || typeof window.L === 'undefined') return;
    if (target.querySelector('.leaflet-map-pane') || target.classList.contains('leaflet-container')) return;

    const latNode = document.getElementById('lat');
    const lonNode = document.getElementById('lon');
    const lat = Number(latNode?.value || 47.16);
    const lon = Number(lonNode?.value || -1.27);

    try {
      const map = window.L.map(target, {worldCopyJump: true}).setView([lat, lon], 6);
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(map);
      const marker = window.L.circleMarker([lat, lon], {radius: 7, weight: 2, fillOpacity: 0.8}).addTo(map);
      map.on('click', event => {
        const nextLat = event.latlng.lat;
        const nextLon = event.latlng.lng;
        if (latNode) latNode.value = nextLat.toFixed(4);
        if (lonNode) lonNode.value = nextLon.toFixed(4);
        marker.setLatLng([nextLat, nextLon]);
      });
      setTimeout(() => map.invalidateSize(), 50);
      target.dataset.fallbackMap = '1';
      console.warn('ClimaFlora: fallback OpenStreetMap initialized because the primary map was not ready.');
    } catch (error) {
      console.warn('ClimaFlora fallback map unavailable:', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(ensureMap, 1800));
  } else {
    setTimeout(ensureMap, 1800);
  }
})();
