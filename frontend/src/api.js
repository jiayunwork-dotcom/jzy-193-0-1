// 极简 fetch 封装
async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const errors = data?.detail?.errors
    const err = new Error(data?.detail?.message || `HTTP ${res.status}`)
    err.errors = errors
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  listExperiments: () => request('GET', '/api/experiments'),
  createExperiment: (payload) => request('POST', '/api/experiments', payload),
  getExperiment: (id) => request('GET', `/api/experiments/${id}`),
  pushBatch: (id, payload) => request('POST', `/api/experiments/${id}/batches`, payload),
  listBatches: (id) => request('GET', `/api/experiments/${id}/batches`),
  listCorrections: (id) => request('GET', `/api/experiments/${id}/corrections`),
  createView: (id, trigger = 'manual') =>
    request('POST', `/api/experiments/${id}/views`, { trigger }),
  listViews: (id) => request('GET', `/api/experiments/${id}/views`),
  trajectory: (id) => request('GET', `/api/experiments/${id}/trajectory`),
  replay: (id) => request('POST', `/api/experiments/${id}/replay`),
}
