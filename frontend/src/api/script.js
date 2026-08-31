import axios from './axios'

const API_BASE = '/scripts'

export const scriptAPI = {
  async convert(projectId, caseIds, aiOptimize = false) {
    const response = await axios.post(`${API_BASE}/convert`, {
      project_id: projectId,
      case_ids: caseIds,
      ai_optimize: aiOptimize,
    })
    return response.data
  },

  async list(params = {}) {
    const response = await axios.get(API_BASE, { params })
    return response.data
  },

  async get(scriptId) {
    const response = await axios.get(`${API_BASE}/${scriptId}`)
    return response.data
  },

  async confirm(scriptId) {
    const response = await axios.put(`${API_BASE}/${scriptId}/confirm`)
    return response.data
  },

  async diagnose(scriptId, payload) {
    const response = await axios.post(`${API_BASE}/${scriptId}/diagnose`, payload)
    return response.data
  },

  async run(scriptId, config = {}) {
    const response = await axios.post(`${API_BASE}/run`, {
      script_id: scriptId,
      config: { headless: config.headless ?? true, timeout: config.timeout ?? 60, max_failures: config.max_failures ?? 8 },
    })
    return response.data
  },

  async batchRun(scriptIds, config = {}) {
    const response = await axios.post(`${API_BASE}/batch-run`, {
      script_ids: scriptIds,
      config: { headless: config.headless ?? true, timeout: config.timeout ?? 60, max_failures: config.max_failures ?? 8 },
    })
    return response.data
  },

  async quickRun(scriptContent, targetUrl, headless = true) {
    const response = await axios.post(`${API_BASE}/quick-run`, {
      script_content: scriptContent, target_url: targetUrl, headless,
    })
    return response.data
  },

  async stats(projectId) {
    const response = await axios.get(`${API_BASE}/stats`, { params: { project_id: projectId } })
    return response.data
  },

  /**
   * SSE 订阅转脚本文字直播
   * @param {string} sessionId
   * @param {(msg: object) => void} onMessage
   * @param {(err: Event) => void} [onError]
   * @returns {EventSource}
   */
  subscribe(sessionId, onMessage, onError) {
    const es = new EventSource(`/api/sse/stream/${sessionId}`)
    es.onmessage = (ev) => {
      try { onMessage(JSON.parse(ev.data)) } catch { onMessage({ content: ev.data }) }
    }
    if (onError) es.onerror = onError
    return es
  },
}
