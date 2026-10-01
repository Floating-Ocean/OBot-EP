<script setup>
/**
 * 通用审核台：任何一个插件都能直接用。
 *
 * 审核流程（提交 → 审核 → 下发）是**框架**的能力 —— 它只操作提交单表，
 * 不认识任何具体工具的数据。所以这个界面也应该是框架的，插件不该各写一份。
 *
 * 插件只需要在 routes.js 里挂一条路由指向它，并在 meta 里写明 slug：
 *
 *     {
 *       path: '/mytool/review',
 *       name: 'mytool-review',
 *       component: () => import('@/views/admin/PluginReviewView.vue'),
 *       meta: { title: '审核台', admin: true, plugin: 'mytool' },
 *     }
 *
 * 「一键下发」走约定路径 `POST /api/plugins/<slug>/admin/apply`，所以插件那边
 * 只要提供这个接口（脚手架生成的插件自带）就能用。
 *
 * 需要展示领域专属的改动对比（例如 PickOne 的类别 {id, keys}）或冲突裁定界面时，
 * 插件再写自己的审核视图 —— 见 web/src/plugins/pickone/views/ReviewView.vue。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'

const route = useRoute()
const slug = computed(() => route.meta.plugin ?? '')

const TABS = [
  { name: 'pending', label: '待审核', hint: '等待管理员裁决' },
  { name: 'approved', label: '待下发', hint: '已通过，等「一键下发」写回数据' },
  { name: 'conflict', label: '冲突待裁定', hint: '下发时发现原值已被改动' },
  { name: 'applied', label: '已下发', hint: '已经写回数据文件' },
  { name: 'rejected', label: '已驳回', hint: '未采纳的提交' },
  { name: 'all', label: '全部', hint: '' },
]

const activeTab = ref('pending')
const items = ref([])
const counts = ref({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const overview = ref(null)
const applying = ref(false)
const imgKey = ref('')

const pendingCount = computed(() => counts.value.pending ?? 0)

async function load() {
  if (!slug.value) {
    ElMessage.error('这条路由缺少 meta.plugin，无法确定要审核哪个工具')
    return
  }
  loading.value = true
  try {
    const data = await api.reviewQueue({
      plugin: slug.value,
      status: activeTab.value,
      img_key: imgKey.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
    if (data.counts) counts.value = data.counts
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadOverview() {
  try {
    overview.value = await api.pluginOverview(slug.value)
    counts.value = overview.value.submission_counts ?? counts.value
  } catch {
    /* 概览失败不影响队列本身 */
  }
}

function reload() {
  page.value = 1
  return Promise.all([load(), loadOverview()])
}

function switchTab(name) {
  activeTab.value = name
  page.value = 1
  load()
}

function onPageChange(value) {
  page.value = value
  load()
}

async function review(row, approve) {
  try {
    const comment = approve ? '' : await promptRejectReason()
    if (comment === null) return
    await api.review(row.id, { approve, comment: comment ?? '' })
    ElMessage.success(approve ? '已通过' : '已驳回')
    await reload()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.message ?? String(error))
  }
}

async function promptRejectReason() {
  try {
    const result = await ElMessageBox.prompt('驳回理由（可留空）', '驳回提交', {
      inputPlaceholder: '例如：描述与图片不符',
      inputValidator: (value) => (value ?? '').length <= 200 || '最多 200 字',
    })
    return result.value ?? ''
  } catch {
    return null
  }
}

async function unreview(row) {
  try {
    await api.unreview(row.id)
    ElMessage.success('已退回待审核')
    await reload()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function applyAll() {
  try {
    const preview = await api.pluginApplyPreview(slug.value)
    const summary = `将下发 ${preview.submissions ?? 0} 条提交`
    await ElMessageBox.confirm(summary, '一键下发', { type: 'warning' })
  } catch {
    return // 用户取消，或预览失败（预览失败会在下面重新报出来）
  }

  applying.value = true
  try {
    const result = await api.pluginApply(slug.value)
    ElMessage.success(`已下发 ${result.applied ?? result.submissions ?? 0} 条提交`)
    await reload()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    applying.value = false
  }
}

/** 改动内容只有插件自己看得懂，框架就原样展示 JSON。 */
function valueText(value) {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

watch(() => route.fullPath, reload)
onMounted(reload)
</script>

<template>
  <div class="ep-page">
    <div class="ep-page-head">
      <div>
        <h1 class="ep-title">审核台</h1>
        <p class="ep-subtitle">
          审核通过后再点「一键下发」才会写回数据文件；下发前可以在这里再核对一遍。
        </p>
      </div>
      <div class="ep-actions">
        <el-button :loading="loading" @click="reload">刷新</el-button>
        <el-button
          type="primary"
          :disabled="(counts.approved ?? 0) === 0"
          :loading="applying"
          @click="applyAll"
        >
          一键下发
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="overview && overview.lib_available === false"
      type="error"
      :closable="false"
      show-icon
      class="ep-mb"
      title="数据目录不可用"
      description="后端读不到这个工具的数据目录，现在只能审核，下发会失败。"
    />

    <div class="ep-stats ep-section">
      <div class="ep-stat">
        <div class="ep-stat-label">待审核</div>
        <div class="ep-stat-value" :class="{ 'is-warn': pendingCount > 0 }">{{ pendingCount }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">已通过待下发</div>
        <div class="ep-stat-value" :class="{ 'is-ok': (counts.approved ?? 0) > 0 }">
          {{ counts.approved ?? 0 }}
        </div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">冲突待裁定</div>
        <div class="ep-stat-value" :class="{ 'is-danger': (counts.conflict ?? 0) > 0 }">
          {{ counts.conflict ?? 0 }}
        </div>
        <div class="ep-stat-hint">
          {{ overview?.lib_available === false ? '数据目录不可用' : '' }}
        </div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">累计已下发</div>
        <div class="ep-stat-value">{{ counts.applied ?? 0 }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">已驳回</div>
        <div class="ep-stat-value">{{ counts.rejected ?? 0 }}</div>
      </div>
    </div>

    <el-tabs :model-value="activeTab" @tab-change="switchTab">
      <el-tab-pane
        v-for="tab in TABS"
        :key="tab.name"
        :name="tab.name"
        :label="`${tab.label} (${tab.name === 'all' ? total : (counts[tab.name] ?? 0)})`"
      />
    </el-tabs>

    <div class="filters ep-mb">
      <el-input
        v-model="imgKey"
        placeholder="按资源标识过滤"
        clearable
        style="max-width: 260px"
        @keyup.enter="reload"
      />
      <el-button @click="reload">查询</el-button>
      <span class="ep-muted">共 {{ total }} 条</span>
    </div>

    <el-table :data="items" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column label="资源 / 目标" min-width="180">
        <template #default="{ row }">
          <b>{{ row.img_key }}</b>
          <span v-if="row.target" class="ep-muted"> / {{ row.target }}</span>
        </template>
      </el-table-column>
      <el-table-column label="改动" min-width="240">
        <template #default="{ row }">
          <div class="diff">
            <div class="diff-line">
              <span class="diff-tag">原</span>{{ valueText(row.base_value) }}
            </div>
            <div class="diff-line">
              <span class="diff-tag is-new">新</span>{{ valueText(row.submitted_value) }}
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="type_label" label="类型" width="110" />
      <el-table-column prop="author_name" label="提交者" width="120" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button size="small" type="primary" @click="review(row, true)">通过</el-button>
            <el-button size="small" @click="review(row, false)">驳回</el-button>
          </template>
          <el-button
            v-else-if="row.status === 'approved'"
            size="small"
            @click="unreview(row)"
          >
            撤回审核
          </el-button>
          <span v-else class="ep-muted">—</span>
        </template>
      </el-table-column>
      <template #empty>暂无数据</template>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      class="ep-pager"
      layout="prev, pager, next"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      @current-change="onPageChange"
    />
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
}

.diff {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
}

.diff-line {
  display: flex;
  gap: 6px;
  word-break: break-all;
}

.diff-tag {
  flex: none;
  color: var(--ep-ink-faint);
}

.diff-tag.is-new {
  color: var(--ep-brand-b);
  font-weight: 700;
}

.ep-pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
