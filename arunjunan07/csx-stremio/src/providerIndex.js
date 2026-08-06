const DEFAULT_PROVIDER_INDEX_URL = 'https://raw.githubusercontent.com/Zenda-Cross/vega-providers/refs/heads/main/urls.json';

async function loadJsonFromUrl(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load provider index: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

function normalizeProviderRecords(data) {
  if (Array.isArray(data)) {
    return data.map((item, index) => ({
      id: item.id || item.name || `provider-${index + 1}`,
      name: item.name || item.title || `Provider ${index + 1}`,
      ...item,
    }));
  }

  if (data && Array.isArray(data.providers)) {
    return data.providers.map((item, index) => ({
      id: item.id || item.name || `provider-${index + 1}`,
      name: item.name || item.title || `Provider ${index + 1}`,
      ...item,
    }));
  }

  if (data && typeof data === 'object') {
    return Object.entries(data).map(([key, value], index) => ({
      id: value && value.id ? value.id : key || `provider-${index + 1}`,
      name: value && (value.name || value.title) ? (value.name || value.title) : key || `Provider ${index + 1}`,
      ...value,
    }));
  }

  return [];
}

async function loadProviderIndex() {
  const providerIndexUrl = process.env.PROVIDER_INDEX_URL || DEFAULT_PROVIDER_INDEX_URL;
  const rawData = await loadJsonFromUrl(providerIndexUrl);
  return normalizeProviderRecords(rawData);
}

module.exports = {
  loadProviderIndex,
  normalizeProviderRecords,
};
