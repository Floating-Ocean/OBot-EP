<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { plugins } from '@/plugins/registry'
import { session } from '@/stores/session'

const router = useRouter()
const loading = ref(true)

/**
 * 工具列表来自插件注册表 —— 加一个工具不需要改这个文件。
 * stat 是可选的：拿不到统计（没登录、上游数据目录不在、接口报错）就退化成
 * 「进入工具」，一个工具坏掉不影响别的卡片。
 */
const tiles = ref(
  plugins.map((plugin) => ({ plugin, stat: null, error: '' })),
)

const DEFAULT_ACCENT = {
  tint: 'rgba(56, 189, 214, 0.10)',
  tint_strong: 'rgba(56, 189, 214, 0.26)',
  ink: '#0f6f85',
  track: 'rgba(56, 189, 214, 0.2)',
  glow: 'rgba(56, 189, 214, 0.3)',
}

function accentStyle(manifest) {
  const accent = { ...DEFAULT_ACCENT, ...(manifest.accent ?? {}) }
  return {
    '--ep-accent-tint': accent.tint,
    '--ep-accent-strong': accent.tint_strong,
    '--ep-accent-ink': accent.ink,
    '--ep-accent-track': accent.track,
    '--ep-accent-glow': accent.glow,
  }
}

async function load() {
  loading.value = true
  try {
    await Promise.all(
      tiles.value.map(async (tile) => {
        if (typeof tile.plugin.stat !== 'function') return
        try {
          tile.stat = await tile.plugin.stat()
        } catch (error) {
          tile.stat = null
          tile.error = error.message
        }
      }),
    )
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

    <p class="ep-section-label">可用工具</p>

    <div class="ep-grid tool-grid" v-loading="loading">
      <button
        v-for="tile in tiles"
        :key="tile.plugin.manifest.slug"
        class="ep-tile tool-tile"
        :style="accentStyle(tile.plugin.manifest)"
        @click="router.push(tile.plugin.manifest.home)"
      >
        <span class="tool-head">
          <span class="tool-icon">
            <el-icon><component :is="tile.plugin.manifest.icon" /></el-icon>
          </span>
          <span class="ep-chip ep-chip--accent">{{ tile.plugin.manifest.tag }}</span>
        </span>

        <span class="ep-tile-name">{{ tile.plugin.manifest.name }}</span>
        <span class="ep-tile-aliases">{{ tile.plugin.manifest.summary }}</span>

        <span class="ep-tile-foot">
          <!--
            stat() 的返回值只有三种含义，框架不解释它的内容 ——
            文案由插件自己拼（`label` / `hint`），否则框架就得知道
            「张图」「缺描述」这些属于某个具体工具的词汇。
          -->
          <template v-if="tile.error">
            <el-icon><WarningFilled /></el-icon> {{ tile.error }}
          </template>
          <template v-else-if="tile.stat && tile.stat.ok === false">
            <el-icon><WarningFilled /></el-icon> {{ tile.stat.hint || '暂不可用' }}
          </template>
          <template v-else-if="tile.stat && tile.stat.label">
            {{ tile.stat.label }}
          </template>
          <template v-else>进入工具</template>
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
