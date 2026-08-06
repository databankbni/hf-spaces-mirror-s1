// Aletheia API client — mirrors backend/api.py exactly. The frontend never
// talks to cognee; everything goes through these endpoints.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  status: () => request('/api/status'),
  sources: () => request('/api/sources'),
  graph: () => request('/api/graph'),
  changelog: () => request('/api/changelog'),

  addSource: ({ title, kind, text, url }) =>
    request('/api/sources', {
      method: 'POST',
      body: JSON.stringify({ title, kind, text, url }),
    }),

  ask: (question) =>
    request('/api/ask', { method: 'POST', body: JSON.stringify({ question }) }),

  retract: (sourceId, reason) =>
    request(`/api/sources/${encodeURIComponent(sourceId)}/retract`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  seedDemo: () => request('/api/demo/seed', { method: 'POST' }),
  ingestRetraction: () => request('/api/demo/ingest-retraction', { method: 'POST' }),
}
