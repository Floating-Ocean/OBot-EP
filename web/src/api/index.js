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

export const api = {
  // ---- 认证 ----
  authConfig: () => http.get('/auth/config'),
  login: (payload) => http.post('/auth/login', payload),
  logout: () => http.post('/auth/logout'),
  me: () => http.get('/auth/me'),
  register: (payload) => http.post('/auth/register', payload),
  changePassword: (payload) => http.post('/auth/password', payload),

  // ---- 元信息 ----
  meta: () => http.get('/meta/info'),
  versions: () => http.get('/meta/versions'),

  // ---- 类别 ----
  categories: (params) => http.get('/categories', { params }),
  categorySummary: () => http.get('/categories/summary'),
  categoryCounts: () => http.get('/categories/counts'),
  category: (imgKey) => http.get(`/categories/${encodeURIComponent(imgKey)}`),

  // ---- 图片 ----
  images: (imgKey, params) => http.get(`/images/${encodeURIComponent(imgKey)}`, { params }),
  imageStats: (imgKey) => http.get(`/images/${encodeURIComponent(imgKey)}/stats`),
  image: (imgKey, name) =>
    http.get(`/images/${encodeURIComponent(imgKey)}/item/${encodeURIComponent(name)}`),
  lookupHashId: (imgKey, hashId) =>
    http.get(`/images/${encodeURIComponent(imgKey)}/hash-id/${encodeURIComponent(hashId)}`),
  thumbUrl: (imgKey, name) =>
    `/api/images/${encodeURIComponent(imgKey)}/thumb/${encodeURIComponent(name)}`,
  rawUrl: (imgKey, name) =>
    `/api/images/${encodeURIComponent(imgKey)}/raw/${encodeURIComponent(name)}`,

  // ---- 提交 ----
  submissions: (params) => http.get('/submissions', { params }),
  mySubmissions: () => http.get('/submissions/mine'),
  submit: (imgKey, type, payload) =>
    http.post('/submissions', payload, { params: { img_key: imgKey, type } }),
  submitBatch: (imgKey, payload) =>
    http.post('/submissions/batch', payload, { params: { img_key: imgKey } }),
  withdraw: (id) => http.delete(`/submissions/${id}`),

  // ---- 管理 ----
  reviewQueue: (params) => http.get('/admin/queue', { params }),
  review: (id, payload) => http.post(`/admin/review/${id}`, payload),
  reviewBatch: (payload) => http.post('/admin/review/batch', payload),
  /** 撤回审核：把「已通过待下发」的退回「待审核」，重新审 */
  unreview: (id) => http.post(`/admin/unreview/${id}`),
  applyPreview: () => http.get('/admin/apply/preview'),
  /**
   * 真正写盘。不要再传参数：老签名是 `apply(dryRun)`，写成 `api.apply({})` 会让
   * dry_run 变成真值，结果只做了预览没写盘。要预览请用 applyPreview()。
   */
  apply: () => http.post('/admin/apply', { dry_run: false }),
  conflicts: (params) => http.get('/admin/conflicts', { params }),
  resolveConflict: (id, keepNew) =>
    http.post(`/admin/conflicts/${id}/resolve`, { keep_new: keepNew }),
  logs: (params) => http.get('/admin/logs', { params }),
  users: () => http.get('/admin/users'),
  createUser: (payload) => http.post('/admin/users', payload),
  updateUser: (id, payload) => http.patch(`/admin/users/${id}`, payload),
  deleteUser: (id) => http.delete(`/admin/users/${id}`),
  adminOverview: () => http.get('/admin/overview'),
}

export default http
