import axios from './axios'

/**
 * 测试用例 API
 */
export const testCaseAPI = {
  /**
   * 获取测试用例列表
   * @param {Object} params - { project_id, point_id?, priority?, case_type?, automation_status?,
   *                            is_finalized?, hallucination_status?, review_status?, keyword?,
   *                            page?, page_size? }
   * @returns {Promise<Object>} { total, page, page_size, items: Array }
   */
  async list(params = {}) {
    const response = await axios.get('/test-cases/', { params })
    return response.data
  },

  /**
   * 获取测试用例详情
   */
  async get(caseId) {
    const response = await axios.get(`/test-cases/${caseId}`)
    return response.data
  },

  /**
   * 创建测试用例
   * @param {Object} data - { project_id, name, priority, case_type, automation_status?,
   *                           precondition?, steps, expected_result, created_by? }
   */
  async create(data) {
    const response = await axios.post('/test-cases/', data)
    return response.data
  },

  /**
   * 更新测试用例
   */
  async update(caseId, data) {
    const response = await axios.put(`/test-cases/${caseId}`, data)
    return response.data
  },

  async delete(caseId) {
    const response = await axios.delete(`/test-cases/${caseId}`)
    return response.data
  },

  // ---- 批次（生成记录）----
  /** 生成记录列表 @returns {Promise<Object>} { items, total, page, page_size } */
  async listBatches(params = {}) {
    const response = await axios.get('/test-cases/batches', { params })
    return response.data
  },

  /** 批内用例列表 @returns {Promise<Array>} */
  async listBatchCases(batchId) {
    const response = await axios.get(`/test-cases/batches/${batchId}/cases`)
    return response.data
  },

  /** 删除生成记录（含批内用例） */
  async deleteBatch(batchId) {
    const response = await axios.delete(`/test-cases/batches/${batchId}`)
    return response.data
  },

  /**
   * 批量操作：delete|finalize|unfinalize|update_priority|update_automation_status|mark_hallucination|update_review
   */
  async batchOperation(data) {
    const response = await axios.post('/test-cases/batch', data)
    return response.data
  },

  async getStats(projectId) {
    const response = await axios.get('/test-cases/stats', {
      params: { project_id: projectId }
    })
    return response.data
  },

  // ---- W3 版本历史 ----
  async listVersions(caseId) {
    const response = await axios.get(`/test-cases/${caseId}/versions`)
    return response.data
  },

  async getVersion(caseId, version) {
    const response = await axios.get(`/test-cases/${caseId}/versions/${version}`)
    return response.data
  },

  async rollback(caseId, version) {
    const response = await axios.post(`/test-cases/${caseId}/rollback`, null, {
      params: { version }
    })
    return response.data
  },

  // ---- W4 导入导出 ----
  async exportCases(projectId, format) {
    return axios.get('/test-cases/export', {
      params: { project_id: projectId, format },
      responseType: 'blob'
    })
  },

  async importCases(projectId, file, format) {
    const form = new FormData()
    form.append('file', file)
    const response = await axios.post('/test-cases/import', form, {
      params: { project_id: projectId, format }
    })
    return response.data
  },

  // ---- 智能导入：模板 / 预览 / 确认 ----
  async importTemplate() {
    const response = await axios.get('/test-cases/import-template', { responseType: 'blob' })
    return response
  },

  async importPreview(file, format = 'xlsx', aiOptimize = false) {
    const form = new FormData()
    form.append('file', file)
    const response = await axios.post('/test-cases/import/preview', form, {
      params: { format, ai_optimize: aiOptimize },
      timeout: 300000  // AI 标准化逐条调 LLM，耗时较长
    })
    return response.data
  },

  async importConfirm(projectId, cases, aiOptimize) {
    const response = await axios.post('/test-cases/import/confirm', {
      cases, ai_optimize: aiOptimize
    }, { params: { project_id: projectId }, timeout: 300000 })
    return response.data
  },

  // ---- W5 评审 / 精修 ----
  async refineCase(caseId) {
    const response = await axios.post(`/test-cases/${caseId}/refine`)
    return response.data
  },

  async getRefinementReport(caseId) {
    const response = await axios.get(`/test-cases/${caseId}/refinement-report`)
    return response.data
  },

  async applySuggestions(caseId, suggestionIds = null) {
    const response = await axios.post(`/test-cases/${caseId}/apply-suggestions`, {
      suggestion_ids: suggestionIds
    })
    return response.data
  },

  async updateReview(caseId, data) {
    const response = await axios.patch(`/test-cases/${caseId}/review`, data)
    return response.data
  }
}
