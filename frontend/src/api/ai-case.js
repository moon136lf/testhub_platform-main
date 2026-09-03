import axios from './axios'

const API_BASE = '/ai-case-generation'

export const aiCaseAPI = {
  // Step 2: 上传材料——走后端 /upload-document（base64 文本，pydantic bytes 接受 str），
  // 后端 parse_document_task 解析并缓存结果，用 getParseResult 轮询取文本
  // file_type 从文件扩展名推导（kind 标签 prd/design 不是解析器类型）
  async uploadDocument(projectId, file, docType = 'md') {
    const buf = new Uint8Array(await file.arrayBuffer())
    let bin = ''
    for (let i = 0; i < buf.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000))
    }
    const ext = (file.name || '').split('.').pop()?.toLowerCase()
    const fileType = ['docx', 'pdf', 'txt', 'md'].includes(ext) ? ext : (docType || 'md')
    const response = await axios.post(`${API_BASE}/upload-document`, {
      project_id: projectId,
      file_bytes: btoa(bin),   // base64 str（JSON 数字数组会被 pydantic bytes 拒绝 → 422）
      file_type: fileType
    })
    return response.data
  },

  // 轮询文档解析结果（parse_document_task 完成后写入 task_result:{session_id}）
  // 注意：axios 实例 baseURL=/api/v1，此端点挂在 /api/sse 下（非 /api/v1）。
  // 用 fetch + 完整路径，绕开 baseURL 拼接（此前 404 的根因：
  // `/sse/parse-result/..` 被 baseURL 拼成 /api/v1/sse/... ）
  async getParseResult(sessionId) {
    const resp = await fetch(`/api/sse/parse-result/${sessionId}`)
    return await resp.json()
  },

  // 纯文本输入也走 upload-document（text_content 分支），保证会话一致
  async uploadText(projectId, text) {
    const response = await axios.post(`${API_BASE}/upload-document`, {
      project_id: projectId,
      text_content: text
    })
    return response.data
  },

  async searchKnowledge(projectId, query, topK = 10) {
    const response = await axios.post(`${API_BASE}/knowledge/search`, {
      project_id: projectId,
      query,
      top_k: topK
    })
    return response.data
  },

  /**
   * Step 4: AI 识别测试点（W6 4 规则开关）
   * @param {string} projectId
   * @param {string} documentContent PRD 文本
   * @param {object} rules { automation_thinking, boundary_value, scenario_analysis, equivalence_partition }
   * @param {string[]} ruleIds
   * @param {string[]} knowledgeIds
   */
  async identifyTestPoints(projectId, documentContent, rules = {}, ruleIds = [], knowledgeIds = []) {
    const response = await axios.post(`${API_BASE}/identify-points`, {
      session_id: _genSessionId(),
      project_id: projectId,
      document_content: documentContent,
      rule_ids: ruleIds,
      knowledge_ids: knowledgeIds,
      rules
    })
    return response.data
  },

  async getTestPoints(projectId, skip = 0, limit = 100) {
    const response = await axios.get(`${API_BASE}/test-points`, {
      params: {
        project_id: projectId,
        skip,
        limit
      }
    })
    return response.data
  },

  async generateTestCases(projectId, testPointIds, generationMode = 'comprehensive', enableHallucinationCheck = true) {
    const response = await axios.post(`${API_BASE}/generate-cases`, {
      session_id: _genSessionId(),
      project_id: projectId,
      point_ids: testPointIds,
      hallucination_strategy: enableHallucinationCheck ? 'moderate' : 'permissive'
    })
    return response.data
  },

  async getTestCases(projectId, skip = 0, limit = 100) {
    const response = await axios.get(`${API_BASE}/test-cases`, {
      params: {
        project_id: projectId,
        skip,
        limit
      }
    })
    return response.data
  },

  async getGenerationSessions(projectId) {
    const response = await axios.get(`${API_BASE}/sessions`, {
      params: {
        project_id: projectId
      }
    })
    return response.data
  },

  async getSessionDetail(sessionId) {
    const response = await axios.get(`${API_BASE}/sessions/${sessionId}`)
    return response.data
  },

  // 生成会话列表（生成历史页）
  async listSessions(projectId = '', status = '', skip = 0, limit = 20) {
    const response = await axios.get(`${API_BASE}/sessions`, {
      params: { project_id: projectId || undefined, status: status || undefined, skip, limit }
    })
    return response.data
  },

  async deleteSession(sessionId) {
    const response = await axios.delete(`${API_BASE}/sessions/${sessionId}`)
    return response.data
  },

  // 知识库文档管理（知识库页）
  async listKnowledgeDocuments(projectId = '', docType = '', vectorStatus = '', skip = 0, limit = 20) {
    const response = await axios.get(`${API_BASE}/knowledge-documents`, {
      params: {
        project_id: projectId || undefined,
        doc_type: docType || undefined,
        vector_status: vectorStatus || undefined,
        skip, limit
      }
    })
    return response.data
  },

  async getKnowledgeDocument(docId) {
    const response = await axios.get(`${API_BASE}/knowledge-documents/${docId}`)
    return response.data
  },

  // 上传知识库文档（文件 base64；后端解析+异步向量化）
  async uploadKnowledgeDocument(projectId, docName, docType, file) {
    let fileB64 = null
    if (file) {
      const buf = new Uint8Array(await file.arrayBuffer())
      let bin = ''
      for (let i = 0; i < buf.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000))
      }
      fileB64 = btoa(bin)
    }
    const response = await axios.post(`${API_BASE}/knowledge-documents`, {
      project_id: projectId,
      doc_name: docName,
      doc_type: docType,
      file_bytes_b64: fileB64
    })
    return response.data
  },

  async deleteKnowledgeDocument(docId) {
    const response = await axios.delete(`${API_BASE}/knowledge-documents/${docId}`)
    return response.data
  },

  async revectorizeKnowledgeDocument(docId) {
    const response = await axios.post(`${API_BASE}/knowledge-documents/${docId}/revectorize`)
    return response.data
  },

  // 后端 RuleCreate 契约: {name(<=50), description(必填), prompt_template?}；
  // rule_type/content/created_by 非契约字段，不传（后端统一按自定义规则处理）
  async createRule(name, description, promptTemplate) {
    const response = await axios.post(`${API_BASE}/rules`, {
      name,
      description,
      prompt_template: promptTemplate || null
    })
    return response.data
  },

  // PUT /rules/{id} — RuleUpdate 契约: {name?, description?, prompt_template?}
  async updateRule(ruleId, name, description, promptTemplate) {
    const response = await axios.put(`${API_BASE}/rules/${ruleId}`, {
      name,
      description,
      prompt_template: promptTemplate || null
    })
    return response.data
  },

  // DELETE /rules/{id} — 软删除（status -> inactive），仅自定义规则
  async deleteRule(ruleId) {
    const response = await axios.delete(`${API_BASE}/rules/${ruleId}`)
    return response.data
  },

  async getRules(skip = 0, limit = 100) {
    const response = await axios.get(`${API_BASE}/rules`, {
      params: {
        skip,
        limit
      }
    })
    return response.data
  },

  async updateHallucinationConfig(projectId, forbiddenKeywords = [], penaltyScore = 0.5) {
    const response = await axios.post(`${API_BASE}/hallucination-config`, {
      project_id: projectId,
      forbidden_keywords: forbiddenKeywords,
      penalty_score: penaltyScore
    })
    return response.data
  },

  /**
   * W6 SSE 订阅（文字直播/进度/Token）
   * 重连限制：EventSource 断线会自动无限重连（后端 500 时每 3s 一次，
   * 用户只能停服务才能停）。这里计数，连续 3 次失败后主动 close 并回调 onError。
   * 收到消息即重置计数（正常流里连接刷新不算连续失败）。
   * @param {string} sessionId
   * @param {(msg: object) => void} onMessage 每条 SSE 消息回调
   * @param {(err: Event) => void} [onError] 首次失败与最终放弃时回调
   * @returns {EventSource}
   */
  subscribeSSE(sessionId, onMessage, onError) {
    const MAX_RETRIES = 3
    let retries = 0
    const es = new EventSource(`/api/sse/stream/${sessionId}`)
    es.onmessage = (e) => {
      retries = 0
      try {
        onMessage(JSON.parse(e.data))
      } catch (err) {
        // ignore malformed frames
      }
    }
    es.onerror = (err) => {
      retries += 1
      if (retries >= MAX_RETRIES) {
        es.close()  // 阻断 EventSource 内置的无限自动重连
        if (onError) onError(err)
      }
    }
    return es
  }
}

function _genSessionId() {
  // 前端生成会话ID（uuid v4 形态，后端校验 UUID 格式）
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
