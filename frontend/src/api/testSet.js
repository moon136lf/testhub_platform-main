import axios from './axios'

export const testSetAPI = {
  async listSets(projectId, { page = 1, pageSize = 20, name = '' } = {}) {
    const response = await axios.get('/test-sets', { params: { project_id: projectId, page, page_size: pageSize, name } })
    return response.data
  },
  async createSet(projectId, name, caseIds, source = 'convert_page', description = '') {
    const response = await axios.post('/test-sets', {
      project_id: projectId, name, case_ids: caseIds, source, description
    })
    return response.data
  },
  async updateSet(setId, fields) {
    const response = await axios.put(`/test-sets/${setId}`, fields)
    return response.data
  },
  async deleteSet(setId) {
    const response = await axios.delete(`/test-sets/${setId}`)
    return response.data
  },
  async addCases(setId, caseIds) {
    const response = await axios.post(`/test-sets/${setId}/cases`, { case_ids: caseIds })
    return response.data
  },
  async removeCase(setId, caseId) {
    const response = await axios.delete(`/test-sets/${setId}/cases/${caseId}`)
    return response.data
  },
  async runSet(setId, { headless = true, failFast = false, timeout = 60 } = {}) {
    const response = await axios.post(`/test-sets/${setId}/run`, {
      headless, fail_fast: failFast, timeout
    })
    return response.data
  },
  async getSet(setId) {
    const response = await axios.get(`/test-sets/${setId}`)
    return response.data
  },
  async getRecords(setId, { page = 1, pageSize = 20, result = 'all' } = {}) {
    const response = await axios.get(`/test-sets/${setId}/records`, {
      params: { page, page_size: pageSize, result },
    })
    return response.data
  },
  async getTrend(setId, limit = 10) {
    const response = await axios.get(`/test-sets/${setId}/trend`, { params: { limit } })
    return response.data
  },
  async getReport(setId) {
    const response = await axios.get(`/test-sets/${setId}/report`)
    return response.data
  },
}
