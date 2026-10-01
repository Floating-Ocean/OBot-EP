/**
 * @@NAME@@ 的路由。
 *
 * 每条 path 都要以 `manifest.home`（`/@@SLUG@@`）开头 —— 导航栏靠这个前缀判断
 * 「当前在哪个工具里」。
 */
export default [
  {
    path: '/@@SLUG@@',
    name: '@@SLUG@@-home',
    component: () => import('./views/ItemsView.vue'),
    meta: { title: '@@NAME@@' },
  },
  {
    // 通用审核台由框架提供（它只认提交单，不认具体工具），meta.plugin 由注册表自动写入。
    // 需要领域专属的对比视图时，再改成自己的组件。
    path: '/@@SLUG@@/review',
    name: '@@SLUG@@-review',
    component: () => import('@/views/admin/PluginReviewView.vue'),
    meta: { title: '@@NAME@@ 审核台', admin: true },
  },
]
