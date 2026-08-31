import axios from './axios.js'

// 注意: axios baseURL 已含 /api/v1, url 不能再带前缀
const BASE = '/regression'

export const regressionAPI = {
  async list(projectId, category = '', keyword = '') {
    const params = { project_id: projectId }
    if (category) params.category = category
    if (keyword) params.keyword = keyword
    const resp = await axios.get(`${BASE}/list`, { params })
    return resp.data
  },

  async setMembers(projectId, scriptIds, action) {
    const resp = await axios.post(`${BASE}/members`, {
      project_id: projectId, script_ids: scriptIds, action,
    })
    return resp.data
  },

  async identify(projectId) {
    const resp = await axios.post(`${BASE}/identify`, { project_id: projectId })
    return resp.data
  },

  async stats(projectId) {
    const resp = await axios.get(`${BASE}/stats`, { params: { project_id: projectId } })
    return resp.data
  },

  async run(projectId, config) {
    const resp = await axios.post(`${BASE}/run`, { project_id: projectId, config })
    return resp.data
  },

  async latestExecution(scriptId) {
    const resp = await axios.get(`${BASE}/latest-execution`, { params: { script_id: scriptId } })
    return resp.data
  },

  async push(execId) {
    const resp = await axios.post(`${BASE}/${execId}/push`)
    return resp.data
  },

  async reportSummary(projectId) {
    const resp = await axios.get(`${BASE}/report-summary`, { params: { project_id: projectId } })
    return resp.data
  },
}
