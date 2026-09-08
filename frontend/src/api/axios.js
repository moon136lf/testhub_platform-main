import axios from 'axios'

const API_BASE = '/api/v1'

// 配置 axios
axios.defaults.baseURL = API_BASE
// 注意：不要全局默认 'Content-Type: application/json'——会覆盖 FormData 的
// multipart boundary，后端解析不出 file 字段报 422。axios 遇 FormData 会自动
// 设正确 Content-Type，JSON 请求 axios 默认也是 application/json，无需手动设。

// 响应拦截器
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default axios
