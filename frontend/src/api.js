import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' }
})

// ── Projects ──────────────────────────────────────────
export const getProjects    = ()           => api.get('/api/projects/')
export const createProject  = (data)       => api.post('/api/projects/', data)
export const deleteProject  = (id)         => api.delete(`/api/projects/${id}`)

// ── Vault ─────────────────────────────────────────────
export const getDocuments   = (projectId, scope) =>
  api.get('/api/vault/documents', { params: { project_id: projectId, scope } })

export const uploadDocument = (file, projectId, scope = 'project') => {
  const form = new FormData()
  form.append('file', file)
  if (projectId) form.append('project_id', projectId)
  form.append('scope', scope)
  return api.post('/api/vault/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export const deleteDocument = (id) => api.delete(`/api/vault/documents/${id}`)

// ── Chat ──────────────────────────────────────────────
export const getChats       = (projectId) =>
  api.get('/api/chat/list', { params: { project_id: projectId } })

export const createChat     = (data)      => api.post('/api/chat/new', data)

export const sendMessage    = (data)      => api.post('/api/chat/message', data)

// Uses fetch (not axios) so we can read the response body as a stream
export const streamMessage  = (data)      =>
  fetch(`${API_BASE}/api/chat/message/stream`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(data),
  })

export const getMessages    = (chatId)    => api.get(`/api/chat/${chatId}/messages`)

export default api
