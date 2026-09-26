<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { session } from '@/stores/session'

const router = useRouter()
const summary = ref(null)
const loading = ref(true)

const TOOLS = [
  {
    name: 'PickOne 表情包',
    path: '/pickone',
    tag: '表情包数据',
    icon: 'Grid',
    summary: '维护「来只」表情包的图片描述、类别别名与点赞评论。',
    accent: {
      tint: 'rgba(122, 92, 255, 0.10)',
      tint_strong: 'rgba(122, 92, 255, 0.26)',
      ink: '#5a3ec8',
      track: 'rgba(122, 92, 255, 0.2)',
      glow: 'rgba(122, 92, 255, 0.32)',
    },
  },
]

const tools = computed(() =>
  TOOLS.map((tool) => {
    if (tool.path !== '/pickone' || !summary.value) return { ...tool, stat: null }
    return {
      ...tool,
      stat: {
        todo: summary.value.missing_ocr,
        total: summary.value.image_count,
        categories: summary.value.category_count,
      },
    }
  }),
)

async function load() {
  loading.value = true
  try {
    summary.value = await api.categorySummary()
  } catch {
    summary.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ep-page">
    <div class="ep-page-head">
      <div>
        <h1 class="ep-title">你好，{{ session.label.value }}</h1>
        <p class="ep-subtitle">
          这里是 OBot-ACM 的公开数据维护入口，你可以发起数据修改请求，通过审核的内容将被 Bot 采用。
        </p>
      </div>
    </div>

    <!-- 只在连不上数据目录时提示；正常情况不占位置 -->
    <el-alert
      v-if="summary && !summary.lib_available"
      type="error"
      :closable="false"
      show-icon
      class="ep-mb"
      title="数据目录不可用"
      :description="`后端读不到 ${summary.lib_dir}，页面只能浏览，提交会失败。`"
    />

    <p class="ep-section-label">可用工具</p>

    <div class="ep-grid tool-grid" v-loading="loading">
      <button
        v-for="tool in tools"
        :key="tool.path"
        class="ep-tile tool-tile"
        :style="{
          '--ep-accent-tint': tool.accent.tint,
          '--ep-accent-strong': tool.accent.tint_strong,
          '--ep-accent-ink': tool.accent.ink,
          '--ep-accent-track': tool.accent.track,
          '--ep-accent-glow': tool.accent.glow,
        }"
        @click="router.push(tool.path)"
      >
        <span class="tool-head">
          <span class="tool-icon"><el-icon><component :is="tool.icon" /></el-icon></span>
          <span class="ep-chip ep-chip--accent">{{ tool.tag }}</span>
        </span>

        <span class="ep-tile-name">{{ tool.name }}</span>
        <span class="ep-tile-aliases">{{ tool.summary }}</span>

        <span class="ep-tile-foot">
          <span v-if="tool.stat && tool.stat.todo > 0">
            {{ tool.stat.categories }} 个类别 · {{ tool.stat.total }} 张图 ·
            <b>{{ tool.stat.todo }}</b> 张缺描述
          </span>
          <span v-else-if="tool.stat">
            {{ tool.stat.categories }} 个类别 · {{ tool.stat.total }} 张图 · 描述已补全
          </span>
          <span v-else>进入工具</span>
          <el-icon><Right /></el-icon>
        </span>

        <span class="ep-tile-bar"><i style="width: 100%" /></span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.tool-grid {
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 22px;
}

.tool-tile {
  min-height: 232px;
  padding: 30px 30px 34px;
  font: inherit;
  color: inherit;
}

/* 图标与标签做成等高方块，避免一高一矮 */
.tool-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.tool-head .ep-chip {
  height: 42px;
  padding: 0 18px;
  border-radius: 13px;
  font-size: 13px;
}

.tool-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 13px;
  background-image: linear-gradient(145deg, var(--ep-accent-strong), var(--ep-accent-tint));
  border: 1px solid var(--ep-accent-track);
  font-size: 21px;
  color: var(--ep-accent-ink);
  flex: none;
}

.tool-name {
  font-size: 24px;
  font-weight: 700;
  color: var(--ep-accent-ink);
  letter-spacing: -0.02em;
}

.tool-tile b {
  font-weight: 700;
}
</style>
