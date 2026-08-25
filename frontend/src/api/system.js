import axios from './axios'

export const systemAPI = {
  // ---- settings ----
  listSettings(category) {
    return axios.get('/system/settings', { params: { category } }).then(r => r.data)
  },
  getSetting(key, category, reveal = false) {
    return axios.get(`/system/settings/${key}`, { params: { category, reveal } }).then(r => r.data)
  },
  updateSetting(key, category, body) {
    return axios.put(`/system/settings/${key}`, body, { params: { category } }).then(r => r.data)
  },
  testConnection(provider) {
    return axios.post('/system/settings/test-connection', { provider }).then(r => r.data)
  },

  // ---- runtime config ----
  getRuntimeConfig() {
    return axios.get('/system/runtime-config').then(r => r.data)
  },

  // ---- envs ----
  listEnvs() {
    return axios.get('/system/envs').then(r => r.data)
  },
  createEnv(body) {
    return axios.post('/system/envs', body).then(r => r.data)
  },
  updateEnv(id, body) {
    return axios.put(`/system/envs/${id}`, body).then(r => r.data)
  },
  deleteEnv(id) {
    return axios.delete(`/system/envs/${id}`).then(r => r.data)
  },

  // ---- operation logs ----
  listOpLogs(params = {}) {
    return axios.get('/system/operation-logs', { params }).then(r => r.data)
  },

  // ---- tokens ----
  tokenStatus(projectId) {
    return axios.get('/system/tokens/status', { params: { project_id: projectId } }).then(r => r.data)
  },
  getQuota(projectId) {
    return axios.get('/system/tokens/quota', { params: { project_id: projectId } }).then(r => r.data)
  },
  updateQuota(projectId, body) {
    return axios.put('/system/tokens/quota', body, { params: { project_id: projectId } }).then(r => r.data)
  },
  tokenUsage(projectId, days = 7) {
    return axios.get('/system/tokens/usage', { params: { project_id: projectId, days } }).then(r => r.data)
  }
}
