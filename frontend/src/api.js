const BASE = ''

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : {}
  if (!res.ok) {
    const err = new Error(data.detail || data.error || `HTTP ${res.status}`)
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export const api = {
  listExperiments: () => request('/api/experiments'),
  createExperiment: (body) =>
    request('/api/experiments', { method: 'POST', body: JSON.stringify(body) }),
  getExperiment: (id) => request(`/api/experiments/${id}`),
  pushBatch: (id, body) =>
    request(`/api/experiments/${id}/batches`, { method: 'POST', body: JSON.stringify(body) }),
  listBatches: (id) => request(`/api/experiments/${id}/batches`),
  listEvents: (id) => request(`/api/experiments/${id}/events`),
  listLooks: (id) => request(`/api/experiments/${id}/looks`),
  createLook: (id, trigger = 'manual') =>
    request(`/api/experiments/${id}/looks`, {
      method: 'POST',
      body: JSON.stringify({ trigger }),
    }),
  replay: (id) => request(`/api/experiments/${id}/replay`, { method: 'POST' }),
  trajectory: (id) => request(`/api/experiments/${id}/trajectory`),
}

export function formatNum(x, digits = 4) {
  if (x === null || x === undefined) return '—'
  return Number(x).toFixed(digits)
}
