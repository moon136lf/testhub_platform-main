import axios from './axios'

const API_BASE = '/ai-case-generation'

export const aiCaseAPI = {
  async uploadDocument(projectId, file, docType = 'prd') {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('doc_type', docType)

    const response = await axios.post(
      `${API_BASE}/projects/${projectId}/documents/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      }
    )
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
   * @param {string} sessionId
   * @param {(msg: object) => void} onMessage 每条 SSE 消息回调
   * @param {(err: Event) => void} [onError]
   * @returns {EventSource}
   */
  subscribeSSE(sessionId, onMessage, onError) {
    const es = new EventSource(`/api/sse/stream/${sessionId}`)
    es.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data))
      } catch (err) {
        // ignore malformed frames
      }
    }
    es.onerror = onError || (() => {})
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
