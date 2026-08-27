import axios from './axios'
import { testCaseAPI } from './testCase.js'

export const reviewAPI = {
  getStats(projectId) {
    return axios.get('/reviews/stats', { params: { project_id: projectId } }).then(r => r.data)
  },
  batchRefine(projectId, caseIds) {
    return axios.post('/reviews/batch-refine', { project_id: projectId, case_ids: caseIds }).then(r => r.data)
  },
  getRefinementReport(projectId) {
    return axios.get('/reviews/refinement-report', { params: { project_id: projectId } }).then(r => r.data)
  },
  batchReview(projectId, caseIds, reviewStatus, reviewComment) {
    return axios.post('/reviews/batch-review', {
      project_id: projectId, case_ids: caseIds,
      review_status: reviewStatus, review_comment: reviewComment
    }).then(r => r.data)
  },
  // 单条精修/应用建议复用 #3 API（testCase.js: refineCase / applySuggestions(caseId, suggestionIds=null)）
  refineCase: (caseId) => testCaseAPI.refineCase(caseId),
  applySuggestions: (caseId, suggestionIds = null) => testCaseAPI.applySuggestions(caseId, suggestionIds),
}
