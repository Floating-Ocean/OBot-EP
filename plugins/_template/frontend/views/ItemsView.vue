<script setup>
/**
 * @@NAME@@ 的主页面：列出条目 + 提交修改。
 *
 * 这是骨架示例，按这个工具真正要展示的数据改写即可。三条约定：
 *   - 接口调用统一走 `api.@@SLUG@@.*`（见 ../api.js）
 *   - 页面外层用 `ep-page` / `ep-page-head` / `ep-title` / `ep-stat` 这些全站样式类
 *     （定义在 web/src/styles/main.css）
 *   - 提交只是「排队」：真正的写盘要等管理员在审核台点「一键下发」
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const items = ref([])
const total = ref(0)
const missing = ref(0)
const loading = ref(false)
const keyword = ref('')

const dialogOpen = ref(false)
const editing = ref(null)
const form = ref({ text: '', note: '' })
const saving = ref(false)

const visible = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  if (!needle) return items.value
  return items.value.filter(
    (item) => item.key.toLowerCase().includes(needle) || item.text.toLowerCase().includes(needle),
  )
})

async function load() {
  loading.value = true
  try {
    const data = await api.@@SLUG@@.listItems()
    items.value = data.items
    total.value = data.total
    missing.value = data.missing_text
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openEditor(item) {
  editing.value = item
  form.value = { text: item.text, note: '' }
  dialogOpen.value = true
}

async function submit() {
  saving.value = true
  try {
    await api.@@SLUG@@.submitText({
      key: editing.value.key,
      text: form.value.text,
      note: form.value.note,
    })
    ElMessage.success('已提交，等待管理员审核')
    dialogOpen.value = false
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ep-page">
    <div class="ep-page-head">
      <div>
        <h1 class="ep-title">@@NAME@@</h1>
        <p class="ep-subtitle">TODO(@@SLUG@@): 说明这个页面能做什么、改的内容会落到哪。</p>
      </div>
      <div class="ep-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="ep-stats ep-section">
      <div class="ep-stat">
        <div class="ep-stat-label">条目总数</div>
        <div class="ep-stat-value">{{ total }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">待补充</div>
        <div class="ep-stat-value" :class="{ 'is-warn': missing > 0 }">{{ missing }}</div>
      </div>
    </div>

    <div class="filters ep-mb">
      <el-input v-model="keyword" placeholder="搜索条目" clearable style="max-width: 280px" />
      <span class="ep-muted">共 {{ visible.length }} 条</span>
    </div>

    <el-table :data="visible" v-loading="loading" stripe @row-click="openEditor">
      <el-table-column prop="key" label="条目" width="200" />
      <el-table-column label="内容" min-width="320">
        <template #default="{ row }">
          <span v-if="row.text">{{ row.text }}</span>
          <span v-else class="ep-faint">（空）</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <span class="ep-chip" :class="row.needs_text ? 'ep-chip--warn' : 'ep-chip--ok'">
            {{ row.needs_text ? '待补充' : '已完成' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="openEditor(row)">修改</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无数据</template>
    </el-table>

    <el-dialog v-model="dialogOpen" title="提交修改" width="520px">
      <el-form label-position="top">
        <el-form-item label="条目">
          <el-input :model-value="editing?.key" disabled />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.text" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="备注（可选）">
          <el-input v-model="form.note" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交审核</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
