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
   * 获取项目登录态配置状态
   * @param {string} projectId
   * @returns {Promise<Object>} { status, cookie_count, localStorage_count }
   */
  async loginState(projectId) {
    const response = await axios.get(`/elements/login-state?project_id=${projectId}`)
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

  // ---------------- P3 会话式抓取工作台 ----------------

  /**
   * 创建抓取会话
   * @param {string} projectId
   * @returns {Promise<Object>} { session_id, project_id }
   */
  async createCaptureSession(projectId) {
    const response = await axios.post('/elements/capture/sessions', { project_id: projectId })
    return response.data
  },

  /**
   * 会话状态（工作台全量渲染数据）
   * @param {string} sessionId
   * @returns {Promise<Object>} { session_id, batches, elements, total_elements, included_count }
   */
  async getCaptureState(sessionId) {
    const response = await axios.get(`/elements/capture/sessions/${sessionId}`)
    return response.data
  },

  /** 丢弃会话 */
  async discardCaptureSession(sessionId) {
    const response = await axios.delete(`/elements/capture/sessions/${sessionId}`)
    return response.data
  },

  /**
   * 向会话追加抓取批次
   * @param {string} sessionId
   * @param {Object} data - { url, screenshot_url?, elements }
   * @returns {Promise<Object>} { batch_idx, batch_count, added, total_elements }
   */
  async addCaptureBatch(sessionId, data) {
    const response = await axios.post(`/elements/capture/sessions/${sessionId}/batches`, data)
    return response.data
  },

  /** 单元素勾选/取消 */
  async setCaptureElementIncluded(sessionId, tempId, included) {
    const response = await axios.post(
      `/elements/capture/sessions/${sessionId}/elements/included`,
      { temp_id: tempId, included }
    )
    return response.data
  },

  /** 全选/全不选 */
  async setCaptureAllIncluded(sessionId, included) {
    const response = await axios.post(
      `/elements/capture/sessions/${sessionId}/elements/included-all`,
      { included }
    )
    return response.data
  },

  /** 删除会话内单个元素 */
  async deleteCaptureElement(sessionId, tempId) {
    const response = await axios.delete(`/elements/capture/sessions/${sessionId}/elements`, {
      data: { temp_id: tempId }
    })
    return response.data
  },

  /** 删除会话内整批次 */
  async deleteCaptureBatch(sessionId, batchIdx) {
    const response = await axios.delete(`/elements/capture/sessions/${sessionId}/batches`, {
      data: { batch_idx: batchIdx }
    })
    return response.data
  },

  /**
   * 会话式入库（按勾选状态）
   * @param {Object} data - { session_id, page_id?, page_name?, page_url?, screenshot_url? }
   * @returns {Promise<Object>} { page_id, page_name, imported_count, failed_count, session_total }
   */
  async importFromCaptureSession(data) {
    const response = await axios.post(
      `/elements/capture/sessions/${data.session_id}/import`,
      data
    )
    return response.data
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
    // 注意: SSE 路由挂在 /api/sse（非 /api/v1/sse），且 EventSource 不走 axios baseURL
    return new EventSource(`/api/sse/element-fetch/${sessionId}`)
  }
}
