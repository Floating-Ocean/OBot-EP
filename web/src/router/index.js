import { createRouter, createWebHistory } from 'vue-router'
import { session } from '@/stores/session'
import { pluginRoutes } from '@/plugins/registry'

/**
 * 这个站点是「工具集合」：`/` 是工具首页，每个工具挂在 `/<工具名>` 下。
 *
 * **加新工具不需要改这个文件** —— 插件路由由 `@/plugins/registry` 自动发现
 * （见 `web/src/plugins/registry.js`）。这里只放框架自己的页面。
 */
const coreRoutes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    name: 'hub',
    component: () => import('@/views/ToolHubView.vue'),
    meta: { title: '工具' },
  },
  // 账号与审计日志是框架能力（所有工具共用一套账号），所以不挂在任何工具下
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/AdminUsersView.vue'),
    meta: { title: '账号管理', admin: true },
  },
  {
    path: '/admin/logs',
    name: 'admin-logs',
    component: () => import('@/views/admin/AdminLogsView.vue'),
    meta: { title: '操作日志', admin: true },
  },
]

const routes = [
  ...coreRoutes,
  ...pluginRoutes,
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  if (!session.state.ready) {
    await session.loadMe()
  }

  if (to.meta.public) {
    return session.isLoggedIn.value && to.name === 'login' ? { name: 'hub' } : true
  }

  if (!session.isLoggedIn.value) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.meta.admin && !session.isAdmin.value) {
    return { name: 'hub' }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · OBot's Endpoint` : 'OBot\'s Endpoint'
})

export default router
