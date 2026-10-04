<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ToolShell from '@/layout/ToolShell.vue'
import { api } from '@/api'
import { session } from '@/stores/session'

const route = useRoute()

/**
 * 首次导航要等 `router/index.js` 的守卫跑完 `/api/meta` 才知道该去哪。
 * 在那之前 `route.matched` 是空的 —— 必须先什么都不渲染：否则 `route.meta.public`
 * 还是 undefined，会先把工具外壳（导航栏、版本号）画出来，再跳去登录页。
 */
const routeReady = computed(() => route.matched.length > 0)

/** 登录页等公开页面不套外壳（否则登录前也会看到工具导航）。 */
const useShell = computed(() => routeReady.value && !route.meta.public)

/** 审核台角标：管理员才需要，且只在有东西待处理时才拉一次。 */
const pendingCount = ref(0)

async function loadPending() {
  if (!session.isAdmin.value) {
    pendingCount.value = 0
    return
  }
  try {
    const data = await api.adminOverview()
    pendingCount.value = (data.pending_total ?? 0) + (data.submission_counts?.conflict ?? 0)
  } catch {
    pendingCount.value = 0
  }
}

function onRefreshSummary() {
  loadPending()
}

// 登录后（或切换账号后）重新取一次角标
watch(
  () => session.isAdmin.value,
  (isAdmin) => {
    if (isAdmin) loadPending()
    else pendingCount.value = 0
  },
)

onMounted(loadPending)
</script>

<template>
  <ToolShell
    v-if="useShell"
    :pending-count="pendingCount"
    @refresh-summary="onRefreshSummary"
  />
  <router-view v-else-if="routeReady" />
</template>
