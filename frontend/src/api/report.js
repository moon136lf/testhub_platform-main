import axios from './axios'

export const reportAPI = {
  listRecords(params) {
    return axios.get('/reports/records', { params }).then(r => r.data)
  },
  getDetail(execId) {
    return axios.get(`/reports/records/${execId}`).then(r => r.data)
  },
  listDetails(execId, status = 'fail') {
    return axios.get(`/reports/records/${execId}/details`, { params: { status } }).then(r => r.data)
  },
  getTrend(projectId, days = 7) {
    return axios.get('/reports/trend', { params: { project_id: projectId, days } }).then(r => r.data)
  },
  generateReport(execId, force = false) {
    return axios.post(`/reports/${execId}/generate`, null, { params: { force } }).then(r => r.data)
  },
  exportUrl(execId, format = 'html') {
    return `/reports/${execId}/export?format=${format}`
  }
}
