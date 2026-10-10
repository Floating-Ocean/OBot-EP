/**
 * 前端插件注册表。
 *
 * 约定：每个插件是 `web/src/plugins/<slug>/` 下的一个目录，`index.js` 默认导出
 *
 *     export default {
 *       manifest: { slug, name, tag, icon, summary, accent, order, home, nav, adminNav },
 *       routes:   [ { path, name, component, meta } ],
 *       api:      { 方法名: 函数 },        // 会被挂到 api 门面上
 *       stat?:    async () => ({ ... })    // 可选，工具首页卡片上的统计
 *       navBadge?: async () => 12          // 可选，导航角标里本工具额外记上的待办数
 *     }
 *
 * `navBadge()` 只需要报「框架数不到的那部分」：待审核 / 冲突的提交单框架自己会数，
 * 插件再报一遍角标就翻倍。它只用于导航角标，拿不到数（抛错 / 返回 0）不影响别的工具。
 *
 * 这里是**自动发现**的：加一个工具只需要新建目录，不用改 router、不用改首页、
 * 不用改导航栏。后端对应的插件包见仓库根目录的 `plugins/<slug>/`。
 */
/**
 * 自动发现所有插件：`web/src/plugins/<slug>/index.js`。
 *
 * 排除 `_` 开头的目录，与后端 `server.plugin.discover_plugins()` 的规则保持一致 ——
 * 草稿和临时目录放 `_xxx/` 里就不会被加载。
 */
const modules = import.meta.glob(['./*/index.js', '!./_*/index.js'], { eager: true })

function byOrder(left, right) {
  const a = left.manifest.order ?? 100
  const b = right.manifest.order ?? 100
  return a - b || left.manifest.slug.localeCompare(right.manifest.slug)
}

export const plugins = Object.values(modules)
  .map((module) => module.default)
  .filter(Boolean)
  .sort(byOrder)

/** slug -> api 方法表，供 @/api 平铺合并 */
export const pluginApis = Object.fromEntries(
  plugins.filter((plugin) => plugin.api).map((plugin) => [plugin.manifest.slug, plugin.api]),
)

/** 所有插件的路由，已带上 plugin slug 供导航栏做归属判断 */
export const pluginRoutes = plugins.flatMap((plugin) =>
  (plugin.routes ?? []).map((route) => ({
    ...route,
    meta: { ...route.meta, plugin: plugin.manifest.slug },
  })),
)

/**
 * 找出当前路径属于哪个插件：按 home 前缀做最长匹配。
 * 返回 null 表示不在任何工具里（工具首页、登录页等）。
 */
export function currentPlugin(path) {
  const matches = plugins
    .filter((plugin) => plugin.manifest.home)
    .filter((plugin) => path === plugin.manifest.home || path.startsWith(`${plugin.manifest.home}/`))
    .sort((a, b) => b.manifest.home.length - a.manifest.home.length)
  return matches[0] ?? null
}

export function pluginBySlug(slug) {
  return plugins.find((plugin) => plugin.manifest.slug === slug) ?? null
}
