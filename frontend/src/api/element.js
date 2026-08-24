import axios from './axios'

/**
 * 元素库 API - 对接 backend/app/api/v1/elements.py (Task 15 重构后)
 */
export const elementAPI = {
  /**
   * 触发元素抓取任务（Celery + SSE 直播）
   * @param {Object} data - { project_id, url, username?, password? }
   * @returns {Promise<Object>} { session_id, sse_url }
   */
  async fetchElements(data) {
    const response = await axios.post('/elements/fetch', data)
    return response.data
  },

  /**
   * 批量导入元素到库
   * @param {Object} data - { project_id, page_id?, page_name?, page_url?, screenshot_url?, selected_element_ids, elements_data }
   * @returns {Promise<Object>} { page_id, page_name, imported_count, failed_count }
   */
  async importElements(data) {
    const response = await axios.post('/elements/import', data)
    return response.data
  },

  // 兼容旧调用名
  async batchImport(data) {
    return this.importElements(data)
  },

  /**
   * 获取项目的所有页面
   * @param {string} projectId
   * @returns {Promise<Array>} PageResponse 列表
   */
  async listPages(projectId) {
    const response = await axios.get('/elements/pages', {
      params: { project_id: projectId }
    })
    return response.data
  },

  // 兼容旧调用名
  async getPages(projectId) {
    return this.listPages(projectId)
  },

  /**
   * 获取页面的所有 active 元素
   * @param {string} pageId
   * @returns {Promise<Array>} ElementResponse 列表
   */
  async getPageElements(pageId) {
    const response = await axios.get(`/elements/pages/${pageId}/elements`)
    return response.data
  },

  /**
   * 获取页面的抓取历史（最近 10 条）
   * @param {string} pageId
   * @returns {Promise<Array>} FetchHistoryResponse 列表
   */
  async getFetchHistory(pageId) {
    const response = await axios.get(`/elements/pages/${pageId}/history`)
    return response.data
  },

  /**
   * 删除元素（软删除）
   * @param {string} elementId
   * @returns {Promise<Object>}
   */
  async deleteElement(elementId) {
    const response = await axios.delete(`/elements/elements/${elementId}`)
    return response.data
  },

  /**
   * ELEM-05: 触发变更检测
   * @param {string} pageId
   * @returns {Promise<Object>} 变更检测记录
   */
  async triggerChangeDetection(pageId) {
    const response = await axios.post('/elements/change-detection', null, {
      params: { page_id: pageId }
    })
    return response.data
  },

  /**
   * ELEM-07: 一键更新受影响元素的定位器
   * @param {string} detectionId
   * @returns {Promise<Object>} { updated_count, failed_count, updated_elements }
   */
  async fixChangeDetection(detectionId) {
    const response = await axios.post(`/elements/change-detection/${detectionId}/fix`)
    return response.data
  },

  /**
   * 创建 SSE 连接（抓取进度直播）
   * @param {string} sessionId
   * @returns {EventSource}
   */
  createSSEConnection(sessionId) {
    return new EventSource(`/api/v1/sse/element-fetch/${sessionId}`)
  }
}
