import axios from 'axios'

/** 后端 API 客户端。/api 与前端同源，会话通过 HttpOnly Cookie 携带。 */
const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

/** 后端统一用 {detail: "..."} 报错，这里抽成 Error.message。 */
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const detail = error?.response?.data?.detail
    let message = '请求失败，请稍后重试'
    if (typeof detail === 'string' && detail) {
      message = detail
    } else if (Array.isArray(detail) && detail.length) {
      message = detail.map((item) => item.msg ?? String(item)).join('；')
    } else if (error?.code === 'ECONNABORTED') {
      message = '请求超时'
    } else if (!error?.response) {
      message = '无法连接后端服务'
    }

    const wrapped = new Error(message)
    wrapped.status = error?.response?.status
    return Promise.reject(wrapped)
  },
)

export default http
