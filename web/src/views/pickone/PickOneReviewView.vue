<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import SubmissionTable from '@/components/SubmissionTable.vue'
import ConflictResolveDialog from '@/components/ConflictResolveDialog.vue'
import { fieldLabel, renderLikeDelta, renderValue } from '@/utils/format'

const emit = defineEmits(['refresh-summary'])

const TABS = [
  { name: 'pending', label: '待审核' },
  { name: 'approved', label: '待下发' },
  { name: 'conflict', label: '冲突待裁定' },
  { name: 'applied', label: '已下发' },
  { name: 'rejected', label: '已驳回' },
  { name: 'all', label: '全部' },
]

/** 这些标签页里可以勾选做批量审核 */
const BATCH_TABS = new Set(['pending', 'conflict'])

const activeTab = ref('pending')
const loading = ref(false)
const items = ref([])
const total = ref(0)
const counts = ref({})
const overview = ref(null)
const selection = ref([])

const preview = ref(null)
const previewOpen = ref(false)
/** 展开的类别分组（默认全展开，用户可以自己收起来） */
const previewOpenGroups = ref([])
const previewing = ref(false)
const applying = ref(false)

const conflictOpen = ref(false)
const activeConflict = ref(null)

const query = reactive({ img_key: '', page: 1, page_size: 20 })

const reviewDialog = reactive({
  open: false,
  row: null,
  approve: true,
  comment: '',
  submitting: false,
})

const pendingCount = computed(() => counts.value.pending ?? 0)
const approvedCount = computed(() => counts.value.approved ?? 0)
const conflictCount = computed(() => counts.value.conflict ?? 0)
const appliedCount = computed(() => counts.value.applied ?? 0)
const rejectedCount = computed(() => counts.value.rejected ?? 0)

/** 本轮下拉会被挂起的冲突 */
const previewConflicts = computed(() => preview.value?.conflicts ?? [])

const batchIds = computed(() =>
  selection.value.filter((row) => row.status === 'pending').map((row) => row.id),
)

/** 只有能批量操作的标签页才给勾选框，否则勾了也没地方用 */
const batchEnabled = computed(() => BATCH_TABS.has(activeTab.value))

/**
 * 标签上的数字。
 * counts 里只有具体状态，没有 all —— 「全部」用队列返回的 total，
 * 否则会一直显示 (0)。
 */
function tabLabel(tab) {
  const value = tab.name === 'all' ? total.value : (counts.value[tab.name] ?? 0)
  return `${tab.label} (${value})`
}

async function load() {
  loading.value = true
  try {
    const data = await api.reviewQueue({
      status: activeTab.value,
      img_key: query.img_key.trim() || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    items.value = data.items
    total.value = data.total
    if (data.counts) counts.value = data.counts
    selection.value = []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadOverview() {
  try {
    overview.value = await api.adminOverview()
    counts.value = overview.value.submission_counts ?? {}
  } catch {
    /* 概览失败不影响队列本身 */
  }
}

/**
 * 一键下发的启用看的是「已通过待下发」的条数。
 * counts 来自队列接口，每次加载都会刷新，所以审核完按钮立刻可用，
 * 不再依赖单独拉一次 id 列表（那样在别的标签页会拿到旧值）。
 */
async function loadAll() {
  await Promise.all([load(), loadOverview()])
}

function switchTab(name) {
  activeTab.value = name
  query.page = 1
  load()
}

function jumpToConflicts() {
  switchTab('conflict')
}

function onChangeSelection(rows) {
  selection.value = rows
}

/**
 * 审核弹窗里的改动对比。
 *
 * 提交单上同时带着 base_value（提交时看到的原值）与 submitted_value（新值），
 * 类别类提交的值是 {id, keys}，展开成两行更好核对。
 */
function reviewDiff(row) {
  if (!row) return []

  if (row.type === 'category' || row.type === 'category_create') {
    const before = row.base_value ?? {}
    const after = row.submitted_value ?? {}
    return [
      {
        field: 'id',
        before: before.id ?? '（新建）',
        after: after.id ?? '（无）',
        changed: renderValue(before.id) !== renderValue(after.id),
      },
      {
        field: 'keys',
        before: before.keys ?? [],
        after: after.keys ?? [],
        changed: renderValue(before.keys) !== renderValue(after.keys),
      },
    ]
  }

  // 点赞提交的是增量：原值是磁盘上的总数，新值显示成 +3
  if (row.type === 'likes') {
    return [
      {
        field: 'likes',
        before: row.base_value,
        after: renderLikeDelta(row.submitted_value),
        changed: true,
      },
    ]
  }

  const field = row.type === 'comments' ? 'comments' : 'ocr_text'
  return [
    {
      field,
      before: row.base_value,
      after: row.submitted_value,
      changed: renderValue(row.base_value) !== renderValue(row.submitted_value),
    },
  ]
}

function openReview(row, approve) {
  reviewDialog.open = true
  reviewDialog.row = row
  reviewDialog.approve = approve
  reviewDialog.comment = ''
}

/** 打开冲突裁定弹窗。行里自带 conflict_detail（三方对比信息）。 */
function openConflict(row) {
  activeConflict.value = {
    submission_id: row.id,
    type: row.type,
    type_label: row.type_label,
    img_key: row.img_key,
    target: row.target,
    author_name: row.author_name,
    note: row.note,
    conflict_at: row.conflict_at,
    conflict_detail: row.conflict_detail,
    reason: row.conflict_detail?.reason,
    base_value: row.conflict_detail?.base_value,
    current_value: row.conflict_detail?.current_value,
    submitted_value: row.submitted_value,
  }
  conflictOpen.value = true
}

async function onConflictResolved() {
  await loadAll()
  emit('refresh-summary')
}

async function confirmReview() {
  reviewDialog.submitting = true
  try {
    await api.review(reviewDialog.row.id, {
      approve: reviewDialog.approve,
      comment: reviewDialog.comment.trim(),
    })
    ElMessage.success(reviewDialog.approve ? '已通过，等待下发' : '已驳回')
    reviewDialog.open = false
    await loadAll()
    emit('refresh-summary')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    reviewDialog.submitting = false
  }
}

/**
 * 撤回审核：把「已通过待下发」的提交退回「待审核」。
 *
 * 适用场景：审错了、想再等等、想和别的改动一起发。已经下发（写入数据文件）的退不了。
 */
async function revokeReview(row) {
  try {
    await ElMessageBox.confirm(
      `撤回后 #${row.id}（${row.type_label} @ ${row.img_key}）会退回「待审核」，需要重新审核。确定吗？`,
      '撤回审核',
      { type: 'warning', confirmButtonText: '撤回审核' },
    )
  } catch {
    return
  }

  try {
    await api.unreview(row.id)
    ElMessage.success('已撤回审核，退回待审核')
    await loadAll()
    emit('refresh-summary')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function batchReview(approve) {
  if (!batchIds.value.length) {
    ElMessage.warning('请先勾选待审核的提交')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定批量${approve ? '通过' : '驳回'} ${batchIds.value.length} 条提交吗？`,
      '批量审核',
      { type: 'warning' },
    )
  } catch {
    return
  }

  try {
    const result = await api.reviewBatch({ ids: batchIds.value, approve, comment: '' })
    ElMessage.success(`成功 ${result.succeeded.length} 条，失败 ${result.failed.length} 条`)
    await loadAll()
    emit('refresh-summary')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function openPreview() {
  previewing.value = true
  try {
    preview.value = await api.applyPreview()
    // 逐类别改动默认全部展开：下发前就是要逐条核对，折叠起来还得一一点开
    previewOpenGroups.value = (preview.value.image_changes ?? []).map((group) => group.img_key)
    previewOpen.value = true
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    previewing.value = false
  }
}

async function doApply() {
  const count = preview.value?.submissions ?? approvedCount.value
  try {
    await ElMessageBox.confirm(
      `将把 ${count} 条已审核的改动写入 OBot-ACM，确定继续吗？`,
      '一键下发',
      { type: 'warning', confirmButtonText: '确认写入' },
    )
  } catch {
    return
  }

  applying.value = true
  try {
    // 不传 dry_run，走真正的写盘分支
    const result = await api.apply()
    const held = result.conflicts?.length ?? 0
    if (held) {
      ElMessage.warning(
        `已写入图片字段 ${result.applied_images} 处、类别 ${result.applied_categories} 个；` +
          `另有 ${held} 条因原值被改动而暂缓下发，请到「冲突待裁定」处理`,
      )
    } else {
      ElMessage.success(
        `已写入图片字段 ${result.applied_images} 处、类别 ${result.applied_categories} 个`,
      )
    }
    previewOpen.value = false
    await loadAll()
    // 有被挂起的冲突就直接把审核员送到冲突页签
    if (held) switchTab('conflict')
    emit('refresh-summary')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    applying.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="ep-page">
    <div class="ep-page-head">
      <div>
        <h1 class="ep-title">审核台</h1>
        <p class="ep-subtitle">审核通过后可一键下发以应用更改</p>
      </div>
      <div class="ep-actions">
        <el-button :loading="loading" @click="loadAll" :icon="Refresh" size="large">
          刷新
        </el-button>
        <!--
          下发统一走「预览 -> 确认」两步：这里只负责打开预览抽屉，
          真正的写盘动作在抽屉底部确认。不再提供直接下发的入口。
        -->
        <el-button
          type="primary"
          :disabled="!approvedCount"
          :loading="previewing"
          @click="openPreview"
          :icon="Upload"
          size="large"
        >
          一键下发{{ approvedCount ? ` (${approvedCount})` : '' }}
        </el-button>
      </div>
    </div>

    <div class="ep-stats ep-section">
      <div class="ep-stat">
        <div class="ep-stat-label">待审核</div>
        <div class="ep-stat-value" :class="{ 'is-warn': pendingCount > 0 }">{{ pendingCount }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">已通过待下发</div>
        <div class="ep-stat-value" :class="{ 'is-ok': approvedCount > 0 }">
          {{ approvedCount }}
        </div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">冲突待裁定</div>
        <div class="ep-stat-value" :class="{ 'is-danger': conflictCount > 0 }">
          {{ conflictCount }}
        </div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">累计已下发</div>
        <div class="ep-stat-value">{{ appliedCount }}</div>
        <div class="ep-stat-hint">{{ overview?.lib_available === false ? '数据目录不可用' : '' }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">已驳回</div>
        <div class="ep-stat-value">{{ rejectedCount }}</div>
      </div>
    </div>

    <el-alert
      v-if="conflictCount"
      type="error"
      :closable="false"
      show-icon
      class="ep-section"
      :title="`有 ${conflictCount} 条提交的原值已被改动，下发前需要逐条裁定`"
    >
      <el-button size="small" type="danger" class="alert-btn" @click="jumpToConflicts">
        去处理
      </el-button>
    </el-alert>

    <div class="ep-card ep-card--flush">
      <el-tabs v-model="activeTab" class="queue-tabs" @tab-change="switchTab">
        <el-tab-pane v-for="tab in TABS" :key="tab.name" :name="tab.name" :label="tabLabel(tab)" />
      </el-tabs>

      <div class="queue-body">
        <!-- 同一行控件统一 size，保证高度齐平 -->
        <div class="toolbar ep-mb">
          <el-input
            v-model="query.img_key"
            size="large"
            placeholder="按类别标识过滤"
            clearable
            style="width: 200px"
            @keyup.enter="((query.page = 1), load())"
            @clear="((query.page = 1), load())"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button size="large" @click="((query.page = 1), load())">查询</el-button>

          <template v-if="batchIds.length">
            <span class="ep-small ep-muted">已选 {{ batchIds.length }} 条</span>
            <el-button size="large" type="success" @click="batchReview(true)">批量通过</el-button>
            <el-button size="large" type="danger" plain @click="batchReview(false)">
              批量驳回
            </el-button>
          </template>

          <span class="ep-small ep-faint total-hint">共 {{ total }} 条</span>
        </div>

        <SubmissionTable
          :items="items"
          :loading="loading"
          :batch-enabled="batchEnabled"
          selectable
          show-author
          show-review
          @selection-change="onChangeSelection"
          @review="openReview"
          @unreview="revokeReview"
          @resolve="openConflict"
        />

        <el-pagination
          v-if="total > query.page_size"
          v-model:current-page="query.page"
          :page-size="query.page_size"
          :total="total"
          layout="prev, pager, next, total"
          class="pager"
          @current-change="load"
        />
      </div>
    </div>

    <!-- 审核确认 -->
    <el-dialog
      v-model="reviewDialog.open"
      :title="reviewDialog.approve ? '通过提交' : '驳回提交'"
      width="480px"
    >
      <template v-if="reviewDialog.row">
        <el-descriptions :column="1" size="small" border class="ep-mb">
          <el-descriptions-item label="提交">
            #{{ reviewDialog.row.id }} · {{ reviewDialog.row.type_label }}
          </el-descriptions-item>
          <el-descriptions-item label="目标">
            <span class="ep-mono ep-small ep-break">
              {{ reviewDialog.row.img_key }}
              <template v-if="reviewDialog.row.target">/ {{ reviewDialog.row.target }}</template>
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="提交者">
            {{ reviewDialog.row.author_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="reviewDialog.row.note" label="提交备注">
            {{ reviewDialog.row.note }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 改动前后对比：只给新值没法判断这次改动对不对 -->
        <div class="diff-block ep-mb">
          <div v-for="field in reviewDiff(reviewDialog.row)" :key="field.field" class="diff-row">
            <div class="diff-head">
              <span class="diff-field">改动 · {{ fieldLabel(field.field) }}</span>
            </div>
            <div class="diff-values">
              <div class="diff-side">
                <span class="ep-small ep-faint">原值</span>
                <span class="diff-old">{{ renderValue(field.before) }}</span>
              </div>
              <el-icon class="diff-arrow"><Right /></el-icon>
              <div class="diff-side">
                <span class="ep-small ep-faint">新值</span>
                <span class="diff-new">{{ renderValue(field.after) }}</span>
              </div>
            </div>
          </div>
        </div>

        <el-input
          v-model="reviewDialog.comment"
          type="textarea"
          :rows="2"
          placeholder="审核备注（可选，会展示给提交者）"
        />
      </template>
      <template #footer>
        <el-button @click="reviewDialog.open = false">取消</el-button>
        <el-button
          :type="reviewDialog.approve ? 'success' : 'danger'"
          :loading="reviewDialog.submitting"
          @click="confirmReview"
        >
          {{ reviewDialog.approve ? '确认通过' : '确认驳回' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 应用预览（只读 dry-run） -->
    <el-drawer v-model="previewOpen" size="760px" title="应用预览">
      <template v-if="preview">
        <el-alert
          v-if="previewConflicts.length"
          type="warning"
          :closable="false"
          show-icon
          class="ep-mb"
          :title="`${previewConflicts.length} 条提交存在冲突，本轮不会下发`"
        >
          <div v-for="(conflict, index) in previewConflicts" :key="index" class="ep-small ep-break">
            #{{ conflict.submission_id ?? '—' }} {{ conflict.img_key }}
            {{ conflict.target ? `/ ${conflict.target}` : '' }} —— {{ conflict.reason }}
          </div>
          <el-button size="small" type="warning" class="alert-btn" @click="((previewOpen = false), jumpToConflicts())">
            去处理冲突
          </el-button>
        </el-alert>

        <div class="ep-stats ep-mb ep-mb-drawer">
          <div class="ep-stat">
            <div class="ep-stat-label">将写入提交</div>
            <div class="ep-stat-value">{{ preview.submissions }}</div>
          </div>
          <div class="ep-stat">
            <div class="ep-stat-label">涉及类别</div>
            <div class="ep-stat-value">{{ preview.image_changes.length }}</div>
          </div>
          <div class="ep-stat">
            <div class="ep-stat-label">新类别</div>
            <div class="ep-stat-value">{{ preview.new_keys?.length ?? 0 }}</div>
            <div class="ep-stat-hint ep-break">
              {{ preview.new_keys?.length ? preview.new_keys.join('、') : '无' }}
            </div>
          </div>
        </div>

        <div class="ep-section-label">逐类别字段改动</div>
        <el-collapse v-if="preview.image_changes.length" v-model="previewOpenGroups">
          <el-collapse-item
            v-for="group in preview.image_changes"
            :key="group.img_key"
            :name="group.img_key"
            :title="`${group.img_key}（${group.count} 处）`"
          >
            <div v-for="(item, index) in group.items" :key="index" class="preview-line">
              <span class="ep-mono ep-small ep-muted ep-break">{{ item.name }}</span>
              <span class="ep-small">{{ fieldLabel(item.field) }} →</span>
              <span class="preview-new">
                {{ item.field === 'likes' ? renderLikeDelta(item.value) : renderValue(item.value) }}
              </span>
            </div>
          </el-collapse-item>
        </el-collapse>
        <el-empty v-else description="没有图片字段改动" :image-size="60" />

        <div v-if="preview.category_entries.length" class="ep-mt">
          <div class="ep-section-label">类别显示名与别名</div>
          <div v-for="entry in preview.category_entries" :key="entry.img_key" class="preview-line">
            <span class="ep-mono ep-small">{{ entry.img_key }}</span>
            <span class="preview-new">
              显示名 {{ renderValue(entry.entry.id) }} / 别名 {{ renderValue(entry.entry.key) }}
            </span>
          </div>
        </div>
      </template>

      <template #footer>
        <span class="ep-small ep-faint preview-foot-hint">
          上述更改将会在确认下发后写入 OBot-ACM 的数据文件
        </span>
        <el-button @click="previewOpen = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!preview?.submissions"
          :loading="applying"
          @click="doApply"
        >
          确认下发
        </el-button>
      </template>
    </el-drawer>

    <!-- 冲突裁定（复用共享弹窗） -->
    <ConflictResolveDialog
      v-model="conflictOpen"
      :conflict="activeConflict"
      @resolved="onConflictResolved"
    />

  </div>
</template>

<style scoped>
.queue-tabs {
  padding: 6px 20px 0;
}

.queue-body {
  padding: 4px 20px 18px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.total-hint {
  margin-left: auto;
}

.alert-btn {
  margin-top: 8px;
}

/* 抽屉底部：左侧说明 + 右侧按钮 */
.preview-foot-hint {
  float: left;
  line-height: 32px;
}

.ep-mb-drawer {
  margin-top: 24px;
  margin-bottom: 24px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.preview-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  padding: 3px 0;
}

.preview-new {
  font-size: 13px;
  font-weight: 600;
  color: var(--ep-ok);
}

/* 审核弹窗里的改动对比 */
.diff-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.diff-row {
  border: 1px solid var(--ep-border);
  border-radius: var(--ep-radius-sm);
  padding: 12px 14px;
  background: var(--ep-surface-sunken);
}

.diff-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.diff-field {
  font-size: 13px;
  font-weight: 700;
}

.diff-values {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.diff-side {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.diff-old,
.diff-new {
  font-size: 12.5px;
  line-height: 1.6;
  word-break: break-word;
}

.diff-old {
  color: var(--ep-ink-muted);
  text-decoration: line-through;
}

.diff-new {
  color: var(--ep-ink);
  font-weight: 600;
}

.diff-arrow {
  flex: none;
  margin-top: 18px;
  font-size: 12px;
  color: var(--ep-ink-faint);
}
</style>
