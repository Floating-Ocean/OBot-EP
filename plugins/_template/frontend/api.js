import http from '@/api/http'

/** 本插件的后端前缀（后端 slug 见 plugins/@@SLUG@@/config.py）。 */
const BASE = '/plugins/@@SLUG@@'

/**
 * @@NAME@@ 的接口。
 *
 * 会被挂到 `api.@@SLUG@@.*` 上；只有名字全站唯一的方法才会同时平铺成 `api.*`，
 * 所以视图里请统一用 `api.@@SLUG@@.方法名()`。
 */
export default {
  listItems: () => http.get(`${BASE}/items`),
  getItem: (key) => http.get(`${BASE}/items/${encodeURIComponent(key)}`),
  listSubmissions: (params) => http.get(`${BASE}/submissions`, { params }),
  submitText: (payload) => http.post(`${BASE}/submissions`, payload),
  withdraw: (id) => http.delete(`${BASE}/submissions/${id}`),

  /**
   * 审核队列（框架接口 `/api/admin/queue` 的包装：注入 plugin 过滤）。
   * 队列本身是通用能力，实现在框架里。
   */
  reviewQueue: (params) =>
    http.get('/admin/queue', { params: { ...params, plugin: '@@SLUG@@' } }),
}
