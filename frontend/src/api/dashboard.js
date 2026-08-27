import axios from './axios'

export const dashboardAPI = {
  getOverview(params) {
    return axios.get('/dashboard/overview', { params }).then(r => r.data)
  }
}
