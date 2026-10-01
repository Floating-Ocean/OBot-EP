import http from './http'

/**
 * 框架级接口：认证、元信息、插件清单、账号、日志、审核队列。
 *
 * 这些接口对所有工具通用，`plugin` 参数用来过滤某个工具的提交单。
 * 具体工具自己的接口写在 `web/src/plugins/<slug>/api.js` 里。
 */
export const coreApi = {
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
  /** 已加载的插件清单 + 各自的健康状态 */
  plugins: () => http.get('/plugins'),

  // ---- 审核流程（与具体工具无关，只操作提交单）----
  /** `params.plugin` 只看某个工具的提交单，留空就是全部 */
  reviewQueue: (params) => http.get('/admin/queue', { params }),
  review: (id, payload) => http.post(`/admin/review/${id}`, payload),
  reviewBatch: (payload) => http.post('/admin/review/batch', payload),
  /** 撤回审核：把「已通过待下发」的退回「待审核」，重新审 */
  unreview: (id) => http.post(`/admin/unreview/${id}`),
  adminOverview: () => http.get('/admin/overview'),

  // ---- 插件约定接口 ----
  // 「一键下发」属于插件（只有它知道自己的数据长什么样），但路径是框架定死的约定：
  //   POST /api/plugins/<slug>/admin/apply
  //   GET  /api/plugins/<slug>/admin/apply/preview
  //   GET  /api/plugins/<slug>/admin/overview
  // 有了这个约定，框架才能提供一个对所有工具都通用的审核台
  // （web/src/views/admin/PluginReviewView.vue），新插件不必自己写审核界面。
  pluginApply: (slug) => http.post(`/plugins/${encodeURIComponent(slug)}/admin/apply`, {}),
  pluginApplyPreview: (slug) =>
    http.get(`/plugins/${encodeURIComponent(slug)}/admin/apply/preview`),
  pluginOverview: (slug) => http.get(`/plugins/${encodeURIComponent(slug)}/admin/overview`),

  // ---- 账号与审计日志 ----
  logs: (params) => http.get('/admin/logs', { params }),
  users: () => http.get('/admin/users'),
  createUser: (payload) => http.post('/admin/users', payload),
  updateUser: (id, payload) => http.patch(`/admin/users/${id}`, payload),
  deleteUser: (id) => http.delete(`/admin/users/${id}`),
}

export default coreApi
