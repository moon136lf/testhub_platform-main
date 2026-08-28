import axios from './axios.js'

const BASE = 'diagnostics'

export const diagnosticsAPI = {
  // TRANS-05: execution_id 自动取数诊断
  // detailId: ExecutionDetail 主键直取 (batch 多脚本同 step 场景, 优先于 execution_id+step)
  async analyze(executionId, step = null, errorData = null, detailId = null) {
    const payload = { execution_id: executionId }
    if (step) payload.step = step
    if (errorData) payload.error_data = errorData
    if (detailId) payload.detail_id = detailId
    const resp = await axios.post(`${BASE}/analyze`, payload)
    return resp.data
  },
  // TRANS-06: 应用修复 (回写元素库)
  async apply(payload) {
    const resp = await axios.post(`${BASE}/apply`, payload)
    return resp.data
  },
}
