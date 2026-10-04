/**
 * 算法竞赛列表前端插件包。前端注册表（@/plugins/registry）认这个默认导出的形状，
 * 后端对应 plugins/contestlist/。两边的 slug 必须一致。
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
   * 工具首页卡片上的统计。
   *
   * 约定的形状只有三个字段，文案由插件自己拼 —— 框架不认识「场比赛」「待审核」
   * 这类属于具体工具的词汇：
   *   ok      false 表示这个工具当前不可用（卡片会显示成告警）
   *   hint    不可用时给用户看的一句话
   *   label  正常时的页脚文案
   * 抛错或返回 null 都表示「拿不到统计」，卡片退化成「进入工具」。
   */
  async stat() {
    const data = await api.listItems()
    if (data.file_available === false) {
      return { ok: false, hint: '比赛列表文件不存在，等待 Bot 第一次导入比赛时创建' }
    }
    const parts = [`${data.total} 场比赛`]
    return { ok: true, label: parts.join(' · ') }
  },
}
