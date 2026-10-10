<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ToolShell from '@/layout/ToolShell.vue'
import { api } from '@/api'
import { plugins } from '@/plugins/registry'
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

/**
 * 导航角标，**按工具分开算**。
 *
 * 角标的含义是「这个工具的待办还有几件」，所以两个来源都要落到具体工具上：
 *   框架数得到的 —— 这个工具自己的待审核 / 冲突提交单（`plugin_counts`）；
 *   插件自报的   —— 不走提交单的待办（PickOne 的上游待审图片），见 `navBadge()`。
 *
 * 之前这里用的是**全站**数（所有插件的提交单）再加插件报的那份，于是每个工具的
 * 审核台都显示同一个数字，还混进了别的工具的量。
 */
const badges = ref({})

async function loadFrameworkCounts() {
  try {
    const data = await api.adminOverview()
    return Object.fromEntries(
      Object.entries(data.plugin_counts ?? {}).map(([slug, counts]) => [
        slug,
        (counts.pending ?? 0) + (counts.conflict ?? 0),
      ]),
    )
  } catch {
    // 框架这份读不到就只算插件报的那部分，不要让角标整块消失
    return {}
  }
}

async function loadReportedCounts() {
  const entries = await Promise.all(
    plugins.map(async (plugin) => {
      if (typeof plugin.navBadge !== 'function') return [plugin.manifest.slug, 0]
      try {
        return [plugin.manifest.slug, Number(await plugin.navBadge()) || 0]
      } catch {
        // 单个插件报不出数，不该把别的工具的待办一起抹掉
        return [plugin.manifest.slug, 0]
      }
    }),
  )
  return Object.fromEntries(entries)
}

async function loadBadges() {
  if (!session.isAdmin.value) {
    badges.value = {}
    return
  }
  const [framework, reported] = await Promise.all([loadFrameworkCounts(), loadReportedCounts()])
  const slugs = new Set([...Object.keys(framework), ...Object.keys(reported)])
  badges.value = Object.fromEntries(
    [...slugs].map((slug) => [slug, (framework[slug] ?? 0) + (reported[slug] ?? 0)]),
  )
}

function onRefreshSummary() {
  loadBadges()
}

// 登录后（或切换账号后）重新取一次角标
watch(
  () => session.isAdmin.value,
  (isAdmin) => {
    if (isAdmin) loadBadges()
    else badges.value = {}
  },
)

onMounted(loadBadges)
</script>

<template>
  <ToolShell v-if="useShell" :badges="badges" @refresh-summary="onRefreshSummary" />
  <router-view v-else-if="routeReady" />
</template>
