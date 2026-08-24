import axios from './axios'

/**
 * 测试用例 API
 */
export const testCaseAPI = {
  /**
   * 获取测试用例列表
   * @param {Object} params - { project_id?, title?, priority?, status?, tags?, skip?, limit? }
   * @returns {Promise<Object>} { items: Array, total: number }
   */
  async list(params = {}) {
    const response = await axios.get('/test-cases/', { params })
    return response.data
  },

  /**
   * 获取测试用例详情
   * @param {string} caseId - 用例ID
   * @returns {Promise<Object>}
   */
  async get(caseId) {
    const response = await axios.get(`/test-cases/${caseId}`)
    return response.data
  },

  /**
   * 创建测试用例
   * @param {Object} data - { project_id, title, description?, priority, tags?, preconditions?, steps }
   * @returns {Promise<Object>}
   */
  async create(data) {
    const response = await axios.post('/test-cases/', data)
    return response.data
  },

  /**
   * 更新测试用例
   * @param {string} caseId - 用例ID
   * @param {Object} data - { title?, description?, priority?, status?, tags?, preconditions?, steps? }
   * @returns {Promise<Object>}
   */
  async update(caseId, data) {
    const response = await axios.put(`/test-cases/${caseId}`, data)
    return response.data
  },

  /**
   * 删除测试用例
   * @param {string} caseId - 用例ID
   * @returns {Promise<Object>}
   */
  async delete(caseId) {
    const response = await axios.delete(`/test-cases/${caseId}`)
    return response.data
  },

  /**
   * 批量操作测试用例
   * @param {Object} data - { operation: 'delete' | 'update_status' | 'update_priority' | 'add_tags' | 'remove_tags', case_ids: string[], update_data?: Object }
   * @returns {Promise<Object>} { success_count: number, failed_count: number, results: Array }
   */
  async batchOperation(data) {
    const response = await axios.post('/test-cases/batch', data)
    return response.data
  },

  /**
   * 获取测试用例统计信息
   * @param {string} projectId - 项目ID
   * @returns {Promise<Object>} { total_cases, by_priority, by_status, by_tags }
   */
  async getStats(projectId) {
    const response = await axios.get('/test-cases/stats', {
      params: { project_id: projectId }
    })
    return response.data
  }
}
