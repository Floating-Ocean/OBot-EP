/**
 * PickOne 的路由。
 *
 * 路径都以 manifest.home（`/pickone`）为前缀，`currentPlugin()` 靠这个前缀
 * 判断当前在哪个工具里。这里只写相对路径的部分会更容易看错，所以写全。
 */
export default [
  {
    path: '/pickone',
    name: 'pickone-home',
    component: () => import('./views/CategoriesView.vue'),
    meta: { title: 'Pick-one 类别' },
  },
  {
    path: '/pickone/categories/:imgKey',
    name: 'pickone-category',
    component: () => import('./views/CategoryView.vue'),
    meta: { title: 'Pick-one 类别详情' },
  },
  {
    path: '/pickone/submissions',
    name: 'pickone-submissions',
    component: () => import('./views/SubmissionsView.vue'),
    meta: { title: '我的提交' },
  },
  {
    path: '/pickone/review',
    name: 'pickone-review',
    component: () => import('./views/ReviewView.vue'),
    meta: { title: '审核台', admin: true },
  },
]
