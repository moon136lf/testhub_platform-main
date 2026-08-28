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

  /**
   * 用例列表（含评审字段）。
   * W7 review I1 修复后：后端 CaseResponse 列表项已含 4 个评审字段
   * （review_status/feasibility_level/refinement_report/refined_at），
   * 探测钩子（review_status === undefined）直接命中，detail 扇出不再触发。
   * 保留兼容逻辑：若后端回退到不含字段的列表，仍自动补拉 detail。
   */
  async listCasesWithReview(projectId, pageSize = 100) {
    const res = await testCaseAPI.list({ project_id: projectId, page: 1, page_size: pageSize })
    const items = res?.items || []
    const missing = items.filter(c => c.review_status === undefined)
    if (!missing.length) return items
    const details = await Promise.allSettled(missing.map(c => testCaseAPI.get(c.id)))
    const byId = new Map()
    for (const d of details) {
      if (d.status === 'fulfilled' && d.value?.id) byId.set(d.value.id, d.value)
    }
    return items.map(c => {
      const d = byId.get(c.id)
      return d ? {
        ...c,
        review_status: d.review_status,
        feasibility_level: d.feasibility_level,
        refinement_report: d.refinement_report,
        refined_at: d.refined_at,
      } : c
    })
  },
}
