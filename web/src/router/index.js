import { createRouter, createWebHistory } from 'vue-router'
import { session } from '@/stores/session'

/**
 * 这个站点是「工具集合」：/ 是工具首页，每个工具挂在 /<工具名> 下。
 * 之后加新工具只需要往 TOOLS 与 routes 里各加一项。
 */
const routes = [
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
  {
    path: '/pickone',
    name: 'pickone-home',
    component: () => import('@/views/pickone/PickOneCategoriesView.vue'),
    meta: { title: 'Pick-one 类别' },
  },
  {
    path: '/pickone/categories/:imgKey',
    name: 'pickone-category',
    component: () => import('@/views/pickone/PickOneCategoryView.vue'),
    meta: { title: 'Pick-one 类别详情' },
  },
  {
    path: '/pickone/submissions',
    name: 'pickone-submissions',
    component: () => import('@/views/pickone/PickOneSubmissionsView.vue'),
    meta: { title: '我的提交' },
  },
  {
    path: '/pickone/review',
    name: 'pickone-review',
    component: () => import('@/views/pickone/PickOneReviewView.vue'),
    meta: { title: '审核台', admin: true },
  },
  {
    path: '/pickone/users',
    name: 'pickone-users',
    component: () => import('@/views/pickone/PickOneUsersView.vue'),
    meta: { title: '账号管理', admin: true },
  },
  {
    path: '/pickone/logs',
    name: 'pickone-logs',
    component: () => import('@/views/pickone/PickOneLogsView.vue'),
    meta: { title: '操作日志', admin: true },
  },
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
