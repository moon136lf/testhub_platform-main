import axios from './axios'

export const whitescanAPI = {
  triggerScan(projectId, repoUrl, branch = 'main') {
    return axios.post('/whitescan/scan', { project_id: projectId, repo_url: repoUrl, branch }).then(r => r.data)
  },
  listScans(projectId, page = 1, pageSize = 20) {
    return axios.get('/whitescan/scans', { params: { project_id: projectId, page, page_size: pageSize } }).then(r => r.data)
  },
  getScan(scanId) {
    return axios.get(`/whitescan/scans/${scanId}`).then(r => r.data)
  },
  listIssues(scanId, params = {}) {
    return axios.get(`/whitescan/scans/${scanId}/issues`, { params }).then(r => r.data)
  },
  updateIssue(issueId, status) {
    return axios.patch(`/whitescan/issues/${issueId}`, { status }).then(r => r.data)
  },
  aiFix(issueId, projectId) {
    return axios.post(`/whitescan/issues/${issueId}/ai-fix`, null, { params: { project_id: projectId } }).then(r => r.data)
  },
  generateCases(scanId, projectId) {
    return axios.post(`/whitescan/scans/${scanId}/generate-cases`, null, { params: { project_id: projectId } }).then(r => r.data)
  },
  exportUrl(scanId, format = 'xlsx') {
    return `/whitescan/scans/${scanId}/export?format=${format}`
  },
}
