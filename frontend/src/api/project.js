import axios from './axios'

/**
 * 项目 API
 */
export const projectAPI = {
  /**
   * 获取项目列表
   * @param {Object} params - { skip?, limit?, status? }
   * @returns {Promise<Array>}
   */
  async list(params = {}) {
    const response = await axios.get('/projects/', { params })
    return response.data
  },

  /**
   * 获取项目详情
   * @param {string} projectId
   * @returns {Promise<Object>}
   */
  async get(projectId) {
    const response = await axios.get(`/projects/${projectId}`)
    return response.data
  },

  /**
   * 创建项目
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  async create(data) {
    const response = await axios.post('/projects/', data)
    return response.data
  },

  /**
   * 更新项目
   * @param {string} projectId
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  async update(projectId, data) {
    const response = await axios.put(`/projects/${projectId}`, data)
    return response.data
  },

  /**
   * 删除项目
   * @param {string} projectId
   * @returns {Promise<Object>}
   */
  async delete(projectId) {
    const response = await axios.delete(`/projects/${projectId}`)
    return response.data
  }
}
