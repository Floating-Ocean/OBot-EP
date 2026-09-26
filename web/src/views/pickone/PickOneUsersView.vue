<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { session } from '@/stores/session'
import { formatTime } from '@/utils/format'

const emit = defineEmits(['refresh-summary'])

const loading = ref(false)
const users = ref([])
const totalAdmins = ref(0)

const createOpen = ref(false)
const creating = ref(false)
const createForm = reactive({ username: '', password: '', display_name: '', role: 'user' })

const resetTarget = ref(null)
const resetPassword = ref('')
const resetting = ref(false)

const roleFilter = ref('all')

function roleLabel(row) {
  return row.is_admin ? '管理员' : '用户'
}

async function load() {
  loading.value = true
  try {
    const data = await api.users()
    users.value = data.users
    totalAdmins.value = data.total_admins
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, { username: '', password: '', display_name: '', role: 'user' })
  createOpen.value = true
}

async function submitCreate() {
  if (createForm.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  creating.value = true
  try {
    await api.createUser({ ...createForm, username: createForm.username.trim() })
    ElMessage.success('账号已创建')
    createOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    creating.value = false
  }
}

async function toggleActive(row) {
  try {
    await api.updateUser(row.id, { is_active: !row.is_active })
    ElMessage.success(row.is_active ? '已停用' : '已启用')
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function toggleRole(row) {
  const next = row.is_admin ? '普通用户' : '管理员'
  try {
    await ElMessageBox.confirm(`把「${row.label}」改为${next}？`, '修改角色', { type: 'warning' })
  } catch {
    return
  }

  try {
    await api.updateUser(row.id, { role: row.is_admin ? 'user' : 'admin' })
    ElMessage.success('角色已修改')
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function openReset(row) {
  resetTarget.value = row
  resetPassword.value = ''
}

async function confirmReset() {
  if (resetPassword.value.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  resetting.value = true
  try {
    await api.updateUser(resetTarget.value.id, { password: resetPassword.value })
    ElMessage.success('密码已重置')
    resetTarget.value = null
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    resetting.value = false
  }
}

async function removeUser(row) {
  try {
    await ElMessageBox.confirm(`删除账号「${row.label}」后不可恢复，确定吗？`, '删除账号', {
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await api.deleteUser(row.id)
    ElMessage.success('已删除')
    await load()
    emit('refresh-summary')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(load)
</script>

<template>
  <div class="ep-page">
    <div class="ep-page-head">
      <div>
        <h1 class="ep-title">账号管理</h1>
        <p class="ep-subtitle">普通用户可以提交修改，但仍需审核；管理员负责审核与下发</p>
      </div>
      <div class="ep-actions">
        <el-button :icon="'Refresh'" @click="load" size="large">刷新</el-button>
        <el-button type="primary" @click="openCreate"
          :icon="Plus" size="large">
          新建账号
        </el-button>
      </div>
    </div>

    <div class="ep-stats ep-section">
      <div class="ep-stat">
        <div class="ep-stat-label">账号总数</div>
        <div class="ep-stat-value">{{ users.length }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">可用管理员</div>
        <div class="ep-stat-value">{{ totalAdmins }}</div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">已停用</div>
        <div class="ep-stat-value" :class="{ 'is-warn': users.some((item) => !item.is_active) }">
          {{ users.filter((item) => !item.is_active).length }}
        </div>
      </div>
      <div class="ep-stat">
        <div class="ep-stat-label">待处理提交</div>
        <div class="ep-stat-value">
          {{ users.reduce((sum, item) => sum + item.open_submissions, 0) }}
        </div>
      </div>
    </div>

    <div class="ep-card ep-card--flush">
      <el-table :data="users" v-loading="loading" size="default" row-key="id">
        <el-table-column label="ID" prop="id" width="90" />

        <el-table-column label="用户名" min-width="180">
          <template #default="{ row }">
            <span class="ep-mono">{{ row.username }}</span>
            <span v-if="row.id === session.state.user?.id" class="ep-chip self">我</span>
          </template>
        </el-table-column>

        <el-table-column label="昵称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'ep-faint': !row.display_name }">{{ row.display_name || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="角色" width="130">
          <template #default="{ row }">
            <span class="ep-chip" :class="row.is_admin ? 'ep-chip--accent' : ''">
              {{ roleLabel(row) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <span class="ep-chip" :class="row.is_active ? 'ep-chip--ok' : 'ep-chip--warn'">
              {{ row.is_active ? '正常' : '已停用' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="待处理" width="120" align="center">
          <template #default="{ row }">
            <span v-if="row.open_submissions" class="ep-chip ep-chip--warn">
              {{ row.open_submissions }}
            </span>
            <span v-else class="ep-faint ep-small">0</span>
          </template>
        </el-table-column>

        <el-table-column label="最近登录" width="180">
          <template #default="{ row }">
            <span class="ep-small ep-faint">{{ formatTime(row.last_login_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            <span class="ep-small ep-faint">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="370" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" type="primary" plain @click="toggleRole(row)">
                {{ row.is_admin ? '降级为用户' : '设为管理员' }}
              </el-button>
              <el-button size="small" plain @click="openReset(row)">重置密码</el-button>
              <el-button size="small" plain @click="toggleActive(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :disabled="row.id === session.state.user?.id"
                @click="removeUser(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createOpen" title="新建账号" width="440px">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" placeholder="字母、数字、下划线、短横线、点"
                    size="large" />
        </el-form-item>
        <el-form-item label="昵称（可选）">
          <el-input v-model="createForm.display_name"
                    size="large" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 8 位"
                    size="large" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="createForm.role"
                          size="large">
            <el-radio-button value="user">普通用户</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="Boolean(resetTarget)"
      title="重置密码"
      width="400px"
      @update:model-value="(value) => !value && (resetTarget = null)"
    >
      <p class="ep-small ep-muted">
        为「{{ resetTarget?.label }}」设置新密码（至少 8 位）。
      </p>
      <el-input v-model="resetPassword" type="password" show-password placeholder="新密码"
                size="large" />
      <template #footer>
        <el-button @click="resetTarget = null">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="confirmReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.self {
  margin-left: 6px;
}

/*
 * 行内操作按钮。
 *
 * 之前全是 text 样式（无边框、无底、无悬停反馈），看着就是几个蓝字，
 * 鼠标划过去没有任何反应。改成有边框的 plain 按钮 + 悬停过渡。
 */
.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
}

.row-actions .el-button + .el-button {
  margin-left: 0;
}

.row-actions :deep(.el-button) {
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.12s ease;
}

.row-actions :deep(.el-button:hover) {
  box-shadow: 0 3px 10px rgba(23, 26, 38, 0.12);
}

.row-actions :deep(.el-button:active) {
  transform: translateY(0);
  box-shadow: none;
}
</style>
