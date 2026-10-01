/**
 * PickOne 前端插件包。前端插件注册表（@/plugins/registry）认这个默认导出的形状，
 * 后端对应 `plugins/pickone/`。两边的 slug 必须一致。
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
   * 约定的形状只有三个字段，文案由插件自己拼 —— 框架不认识「张图」「缺描述」
   * 这类属于具体工具的词汇：
   *   ok      false 表示这个工具当前不可用（卡片会显示成告警）
   *   hint    不可用时给用户看的一句话
   *   label  正常时的页脚文案
   * 抛错或返回 null 都表示「拿不到统计」，卡片退化成「进入工具」。
   */
  async stat() {
    const summary = await api.categorySummary()
    if (summary.lib_available === false) {
      return { ok: false, hint: '数据目录不可用' }
    }

    const prefix = `${summary.category_count} 个类别 · ${summary.image_count} 张图`
    const label =
      summary.missing_ocr > 0
        ? `${prefix} · ${summary.missing_ocr} 张缺描述`
        : `${prefix} · 描述已补全`
    return { ok: true, label }
  },
}
