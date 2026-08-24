import axios from 'axios'

const API_BASE = '/api/v1/ai-case-generation'

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

  async identifyTestPoints(projectId, prdContent, ruleIds = [], knowledgeIds = []) {
    const response = await axios.post(`${API_BASE}/test-points/identify`, {
      project_id: projectId,
      prd_content: prdContent,
      rule_ids: ruleIds,
      knowledge_ids: knowledgeIds
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
    const response = await axios.post(`${API_BASE}/test-cases/generate`, {
      project_id: projectId,
      test_point_ids: testPointIds,
      generation_mode: generationMode,
      enable_hallucination_check: enableHallucinationCheck
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

  async createRule(name, ruleType, content, createdBy = 'system') {
    const response = await axios.post(`${API_BASE}/rules`, {
      name,
      rule_type: ruleType,
      content,
      created_by: createdBy
    })
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
  }
}
