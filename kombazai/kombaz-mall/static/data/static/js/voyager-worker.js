// voyager-worker.js
// Runs Voyager calculations without blocking UI

const LAUNCH_DATE_V1 = new Date(1977, 8, 5, 12, 56, 0).getTime();
const LAUNCH_DATE_V2 = new Date(1977, 8, 20, 14, 29, 0).getTime();
const SPEED_KMS = 17;  // km/s average
const AU_KM = 149597870.7;  // 1 AU in km

function calculateVoyagerData() {
  const now = Date.now();
  
  // Voyager 1
  const elapsedV1 = (now - LAUNCH_DATE_V1) / 1000;  // seconds
  const distanceKmV1 = elapsedV1 * SPEED_KMS;
  const auV1 = (distanceKmV1 / AU_KM).toFixed(2);
  const lightDelayV1 = (distanceKmV1 / 299792.458 / 60).toFixed(2);  // minutes
  
  // Voyager 2
  const elapsedV2 = (now - LAUNCH_DATE_V2) / 1000;
  const distanceKmV2 = elapsedV2 * SPEED_KMS;
  const auV2 = (distanceKmV2 / AU_KM).toFixed(2);
  const lightDelayV2 = (distanceKmV2 / 299792.458 / 60).toFixed(2);
  
  return {
    v1: {
      au: parseFloat(auV1),
      km: distanceKmV1,
      lightDelay: parseFloat(lightDelayV1),
      status: 'Operational'
    },
    v2: {
      au: parseFloat(auV2),
      km: distanceKmV2,
      lightDelay: parseFloat(lightDelayV2),
      status: 'Operational'
    },
    timestamp: now
  };
}

// Send update every 30 seconds
setInterval(() => {
  const data = calculateVoyagerData();
  self.postMessage({
    type: 'voyager_update',
    data: data
  });
}, 30000);

// Also respond to immediate requests
self.addEventListener('message', (event) => {
  if (event.data.type === 'request_voyager') {
    const data = calculateVoyagerData();
    self.postMessage({
      type: 'voyager_update',
      data: data
    });
  }
});
