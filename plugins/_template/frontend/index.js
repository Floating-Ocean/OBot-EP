/**
 * @@NAME@@ 前端插件包。前端注册表（@/plugins/registry）认这个默认导出的形状，
 * 后端对应 plugins/@@SLUG@@/。两边的 slug 必须一致。
 *
 * 注意：这里 import 的是**本插件自己的** `./api`，不要 import `@/api`。
 * 注册表是 `@/api` 的上游（`@/api` → registry → 本文件），在这里反向引用
 * `@/api` 会在模块求值期读到还没建好的门面对象。视图里用 `@/api` 就没问题，
 * 因为视图是路由懒加载的。
 */
import manifest from './manifest'
import routes from './routes'
import api from './api'

export default {
  manifest,
  routes,
  api,

  /**
   * 工具首页卡片上的统计。框架只认这三个字段，文案由插件自己拼：
   *   ok=false 时卡片显示成告警，正文用 hint；否则显示 label。
   * 抛错或返回 null 都表示「拿不到统计」，卡片退化成「进入工具」。
   */
  async stat() {
    const data = await api.listItems()
    const label =
      data.missing_text > 0
        ? `${data.total} 个条目 · ${data.missing_text} 个待补充`
        : `${data.total} 个条目 · 已补全`
    return { ok: true, label }
  },
}
