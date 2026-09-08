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

  /**
   * 获取项目的页面树（按 parent_id 组装）
   * @param {string} projectId
   * @returns {Promise<Object>} { code, data: [嵌套页面节点] }
   */
  async getPageTree(projectId) {
    const response = await axios.get('/elements/pages/tree', {
      params: { project_id: projectId }
    })
    return response.data
  },

  // ---- 元素管理（阶段1） ----
  async listElementsAsset(projectId, { scope, pageId, keyword } = {}) {
    const response = await axios.get('/elements-asset', { params: {
      project_id: projectId,
      scope: scope || undefined,
      page_id: pageId || undefined,
      keyword: keyword || undefined,
    }})
    return response.data
  },
  async createElementAsset(data) {
    const response = await axios.post('/elements-asset', data)
    return response.data
  },
  async updateElement(elementId, fields) {
    const response = await axios.put(`/elements/${elementId}`, fields)
    return response.data
  },
  async addLocator(elementId, type, value, score = 50) {
    const response = await axios.post(`/elements/${elementId}/locators`, { type, value, score })
    return response.data
  },
  async reorderLocator(elementId, index, direction) {
    const response = await axios.post(`/elements/${elementId}/locators/reorder`, { index, direction })
    return response.data
  },
  async verifyLocator(elementId, locatorType, locatorValue) {
    const response = await axios.post(`/elements/${elementId}/locators/verify`,
      { locator_type: locatorType, locator_value: locatorValue })
    return response.data
  },
  async elementReferences(elementId, projectId) {
    const response = await axios.get(`/elements/${elementId}/references`, { params: { project_id: projectId } })
    return response.data
  },
  async recycleElement(elementId) {
    const response = await axios.post(`/elements/${elementId}/recycle`)
    return response.data
  },
  async restoreElement(elementId) {
    const response = await axios.post(`/elements/${elementId}/restore`)
    return response.data
  },
  async recycleBin(projectId) {
    const response = await axios.get('/recycle-bin', { params: { project_id: projectId } })
    return response.data
  },
  async createSubPage(data) {
    const response = await axios.post('/pages-tree', data)
    return response.data
  },
  async renamePage(pageId, pageName) {
    const response = await axios.put(`/pages-tree/${pageId}`, { page_name: pageName })
    return response.data
  },
  async movePage(pageId, direction) {
    const response = await axios.post(`/pages-tree/${pageId}/move`, { direction })
    return response.data
  },
  async deletePageNode(pageId, moveToPageId, force) {
    const response = await axios.delete(`/pages-tree/${pageId}`, { params: {
      move_to_page_id: moveToPageId || undefined, force: force || undefined } })
    return response.data
  },
  async exportElements(projectId) {
    const response = await axios.get('/elements-export', { params: { project_id: projectId } })
    return response.data
  },
  async importElementsAsset(projectId, payload) {
    const response = await axios.post('/elements-import', { project_id: projectId, payload })
    return response.data
  },

  // ---------------- P3 会话式抓取（浏览器会话主循环） ----------------

  /**
   * 打开（或复用）会话浏览器并导航到 url
   * @param {Object} data - { project_id, url, need_login }
   * @returns {Promise<Object>} { session_id, state }  state: awaiting_login | ready
   */
  async openBrowserSession(data) {
    const response = await axios.post('/elements/capture/browser/open', data)
    return response.data.data
  },

  /**
   * 浏览器会话状态 + 实时截图
   * @returns {Promise<Object>} { state, url, title, screenshot_b64 }
   */
  async getBrowserStatus(sessionId) {
    const response = await axios.get(`/elements/capture/browser/${sessionId}/status`)
    return response.data.data
  },

  /**
   * 抓当前页元素 → staging 批次
   * @returns {Promise<Object>} { elements, total_count, batch_idx, batch_count, staging_session_id }
   */
  async captureBrowserPage(sessionId) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/capture`)
    return response.data.data
  },

  /**
   * 点选补抓：按坐标命中元素 → 定位卡片数据
   * @returns {Promise<Object>} element 字典（temp_id/element_type/element_text/locator_strategies...）
   */
  async pickBrowserElement(sessionId, x, y) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/pick-element`, { x, y })
    return response.data.data.element
  },

  /** 释放页面：关浏览器保留会话数据 */
  async releaseBrowser(sessionId) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/release`)
    return response.data.data
  },

  /**
   * 点选面包屑：按坐标命中元素 → 祖先链（每层含 tag/css_path/index_in_parent）
   * @returns {Promise<Object>} { chain, current_index }
   */
  async getNodeInfo(sessionId, x, y) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/node-info`, { x, y })
    return response.data.data
  },

  /**
   * 面包屑层级高亮：css_path 查节点 → 橙色闪烁 2 秒
   * @returns {Promise<Object>} { found }
   */
  async highlightNode(sessionId, cssPath) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/node-highlight`, { css_path: cssPath })
    return response.data.data
  },

  /**
   * 面包屑切层级：对 css_path 节点重跑定位器流水线
   * @returns {Promise<Object>} { element, siblings: [{tag, text, css_path}] }
   */
  async getNodeLocators(sessionId, cssPath) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/node-locators`, { css_path: cssPath })
    return response.data.data
  },

  /** 关闭并删除整个浏览器会话 */
  async closeBrowserSession(sessionId) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/close`)
    return response.data.data
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
