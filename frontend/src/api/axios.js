import axios from 'axios'

const API_BASE = '/api/v1'

// 配置 axios
axios.defaults.baseURL = API_BASE
axios.defaults.headers.common['Content-Type'] = 'application/json'

// 响应拦截器
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default axios
