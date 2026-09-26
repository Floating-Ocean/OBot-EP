<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ToolShell from '@/layout/ToolShell.vue'
import { api } from '@/api'
import { session } from '@/stores/session'

const route = useRoute()

/** 登录页等公开页面不套外壳（否则登录前也会看到工具导航）。 */
const useShell = computed(() => !route.meta.public)

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
  <router-view v-else />
</template>
