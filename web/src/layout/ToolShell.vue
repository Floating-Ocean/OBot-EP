<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { session } from '@/stores/session'
import OBotLogo from '@/components/OBotLogo.vue'

const props = defineProps({
  /** 审核台待处理数量，用于导航角标 */
  pendingCount: { type: Number, default: 0 },
})

const route = useRoute()
const router = useRouter()

const APP_VERSION = '0.1.0'

/** logo 尺寸跟随视口（要响应 resize，不能直接读 window.innerWidth） */
const narrow = ref(false)
const logoSize = computed(() => (narrow.value ? 30 : 38))

function syncViewport() {
  narrow.value = window.innerWidth < 900
}

onMounted(() => {
  syncViewport()
  window.addEventListener('resize', syncViewport, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('resize', syncViewport)
})

/** OBot-ACM 自己的版本号，从后端读（后端直接读它的源码常量）。 */
const versions = ref({ obot: null, pickone: null })

const versionLabel = computed(() => versions.value.obot ?? `v${APP_VERSION}`)

const versionTitle = computed(() => {
  const parts = [`本工具 OBot-EP v${APP_VERSION}`]
  if (versions.value.obot) parts.push(`OBot-ACM ${versions.value.obot}`)
  if (versions.value.commit) parts.push(`commit ${versions.value.commit}`)
  if (versions.value.pickone) parts.push(`PickOne 模块 ${versions.value.pickone}`)
  return parts.join(' · ')
})

onMounted(async () => {
  try {
    versions.value = await api.versions()
  } catch {
    /* 读不到就只显示本工具版本 */
  }
})

const TOOL_NAMES = {
  '': 'OBot\'s Endpoint',
  '/pickone': 'PickOne 表情包',
}

const TOOL_NAV = {
  '': [{ path: '/', label: '工具', icon: 'Menu' }],
  '/pickone': [
    { path: '/pickone', label: '所有表情', icon: 'Grid' },
    { path: '/pickone/submissions', label: '我的提交', icon: 'Tickets' },
  ],
}

const ADMIN_NAV = [
  { path: '/pickone/review', label: '审核台', icon: 'Stamp', badge: true },
  { path: '/pickone/users', label: '账号管理', icon: 'User' },
  { path: '/pickone/logs', label: '操作日志', icon: 'Document' },
]

const toolPrefix = computed(
  () =>
    Object.keys(TOOL_NAMES)
      .filter((prefix) => prefix && route.path.startsWith(prefix))
      .sort((a, b) => b.length - a.length)[0] ?? '',
)

const toolName = computed(() => TOOL_NAMES[toolPrefix.value])

const navItems = computed(() => {
  const items = [...(TOOL_NAV[toolPrefix.value] ?? [])]
  if (toolPrefix.value && session.isAdmin.value) items.push(...ADMIN_NAV)
  return items
})

/** 最长前缀匹配，避免 /pickone 把 /pickone/submissions 也点亮 */
const activePath = computed(() => {
  const matches = navItems.value
    .filter((item) => route.path === item.path || route.path.startsWith(`${item.path}/`))
    .sort((a, b) => b.path.length - a.path.length)
  return matches[0]?.path ?? route.path
})

/* ---- 账号菜单 ---- */

const passwordOpen = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '', confirm: '', busy: false })

async function handleAccountCommand(command) {
  if (command === 'password') {
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm = ''
    passwordOpen.value = true
    return
  }

  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', { type: 'warning' })
    } catch {
      return
    }
    await session.logout()
    ElMessage.success('已退出登录')
    router.push({ name: 'login' })
  }
}

async function submitPassword() {
  if (passwordForm.new_password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }

  passwordForm.busy = true
  try {
    await api.changePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    ElMessage.success('密码已修改')
    passwordOpen.value = false
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    passwordForm.busy = false
  }
}
</script>

<template>
  <div class="shell">
    <header class="shell-bar">
      <div class="shell-inner bar-row">
        <router-link to="/" class="brand">
          <span class="brand-mark"><OBotLogo :size="logoSize" /></span>
          <span class="brand-text">
            <b>{{ toolName }}</b>
            <em>OBot-ACM Web 维护工具</em>
          </span>
        </router-link>

        <!-- 右上角只留版本号，账号相关动作收进下面的导航行 -->
        <span class="version" :title="versionTitle">
          <span class="version-dot" />
          <span class="version-obot">OBot {{ versionLabel }}</span>
        </span>
      </div>

      <nav v-if="navItems.length" class="shell-nav">
        <div class="shell-inner nav-row">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="nav-link"
            :class="{ 'is-active': activePath === item.path }"
            :title="item.label"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span class="nav-label">{{ item.label }}</span>
            <em v-if="item.badge && pendingCount" class="nav-badge">{{ pendingCount }}</em>
          </router-link>

          <div class="nav-right">
            <router-link v-if="toolPrefix" to="/" class="nav-link nav-back" title="全部工具">
              <el-icon><Menu /></el-icon>
              <span class="nav-label">全部工具</span>
            </router-link>

            <el-dropdown trigger="click" @command="handleAccountCommand">
              <span class="account">
                <el-avatar :size="30" class="account-avatar">
                  <el-icon><UserFilled /></el-icon>
                </el-avatar>
                <span class="account-name">{{ session.label.value }}</span>
                <el-icon class="account-caret"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="password">
                    <el-icon><Key /></el-icon> 修改密码
                  </el-dropdown-item>
                  <el-dropdown-item command="logout" divided>
                    <el-icon><SwitchButton /></el-icon> 退出登录
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </nav>
    </header>

    <main class="shell-main">
      <router-view v-slot="{ Component }">
        <component :is="Component" @refresh-summary="$emit('refresh-summary')" />
      </router-view>
    </main>

    <el-dialog v-model="passwordOpen" title="修改密码" width="440px">
      <el-form label-position="top">
        <el-form-item label="原密码">
          <el-input v-model="passwordForm.old_password" type="password" show-password
                    size="large" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="passwordForm.new_password"
            type="password"
            show-password
            placeholder="至少 8 位"
            size="large"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="passwordForm.confirm" type="password" show-password
                    size="large" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordOpen = false">取消</el-button>
        <el-button type="primary" :loading="passwordForm.busy" @click="submitPassword">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.shell-bar {
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: saturate(170%) blur(18px);
  border-bottom: 1px solid var(--ep-border);
  position: sticky;
  top: 0;
  z-index: 10;
}

.shell-inner {
  max-width: var(--ep-max-width);
  margin: 0 auto;
  /* 内边距随视口收放，1K 屏不会显得顶栏又高又空 */
  padding: 0 clamp(18px, 3.2vw, 52px);
  display: flex;
  align-items: center;
  gap: clamp(12px, 1.6vw, 20px);
}

.bar-row {
  height: clamp(64px, 6vw, 84px);
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: clamp(10px, 1.2vw, 14px);
  min-width: 0;
}

/* logo 无底：去掉方块、描边与投影，只留渐变图形本身 */
.brand-mark {
  display: grid;
  place-items: center;
  flex: none;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.36;
  min-width: 0;
}

.brand-text b {
  font-size: clamp(14px, 1.25vw, 16px);
  font-weight: 700;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.brand-text em {
  font-style: normal;
  font-size: 12px;
  color: var(--ep-ink-faint);
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.version {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ep-ink-faint);
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--ep-border);
  background: var(--ep-surface);
  white-space: nowrap;
  flex: none;
}

.version-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-image: var(--ep-brand-gradient);
}

.version-obot {
  font-weight: 700;
  color: var(--ep-ink-muted);
}

/* 头像里可能是一个 emoji（宽度远大于单个字母），缩一号字保证放得下 */
:deep(.el-avatar) {
  font-size: 15px;
  line-height: 28px;
}

/* 账号头像改用通用人形图标：昵称可能是 emoji 或符号，取首字既不稳定也不好看 */
.account-avatar {
  background: linear-gradient(145deg, rgba(255, 95, 126, 0.16), rgba(123, 92, 255, 0.2));
  color: var(--ep-brand-b);
}

.account-avatar :deep(.el-icon) {
  font-size: 17px;
  margin: 0;
}

.shell-nav {
  border-top: 1px solid var(--ep-border);
  background: rgba(255, 255, 255, 0.45);
}

.nav-row {
  height: clamp(56px, 5vw, 68px);
  gap: 6px;
}

.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  height: 40px;
  padding: 0 clamp(12px, 1.4vw, 18px);
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ep-ink-muted);
  white-space: nowrap;
  transition: background 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.nav-link:hover {
  background: rgba(20, 22, 31, 0.05);
  color: var(--ep-ink);
}

.nav-link.is-active {
  background-image: var(--ep-brand-gradient);
  color: #fff;
  box-shadow: 0 6px 16px rgba(122, 92, 255, 0.28);
}

.nav-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-back {
  border: 1px solid var(--ep-border);
  background: var(--ep-surface);
}

.nav-badge {
  font-style: normal;
  font-size: 11.5px;
  font-weight: 700;
  background: var(--ep-danger);
  color: #fff;
  border-radius: 999px;
  padding: 0 8px;
  line-height: 18px;
}

.nav-link.is-active .nav-badge {
  background: #fff;
  color: var(--ep-danger);
}

.account {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  height: 40px;
  padding: 0 14px 0 5px;
  border-radius: 12px;
  border: 1px solid var(--ep-border);
  background: var(--ep-surface);
  cursor: pointer;
  outline: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.account:hover {
  border-color: var(--ep-border-strong);
  box-shadow: var(--ep-shadow-sm);
}

.account-name {
  font-size: 13.5px;
  font-weight: 600;
}

.account-caret {
  font-size: 12px;
  color: var(--ep-ink-faint);
}

.shell-main {
  flex: 1;
}

/*
 * 窄屏：顶栏收成一行，副标题与版本号让位，
 * 导航行改为横向滚动（比换行成两行整齐，也不会把内容顶下去）。
 */
@media (max-width: 1080px) {
  .brand-text em {
    display: none;
  }

}

/*
 * 窄屏：导航收成「只留图标」的方形按钮。
 * 之前是让整行横向滚动，但 390px 下会直接溢出到视口外，很难看也不好点。
 */
@media (max-width: 860px) {
  .version {
    display: none;
  }

  .nav-link .nav-label {
    display: none;
  }

  .nav-link {
    width: 42px;
    padding: 0;
    justify-content: center;
    position: relative;
  }

  .nav-badge {
    position: absolute;
    top: 1px;
    right: 1px;
    padding: 0 5px;
    font-size: 10.5px;
    line-height: 15px;
  }

  .account-name {
    display: none;
  }

  .account {
    width: 42px;
    padding: 0;
    justify-content: center;
    gap: 0;
  }

  .account-caret {
    display: none;
  }
}

@media (max-width: 560px) {
  .bar-row {
    height: 56px;
  }

  .nav-row {
    height: 54px;
    gap: 4px;
  }

  .nav-right {
    gap: 6px;
  }

  .nav-link,
  .account {
    width: 38px;
    height: 36px;
  }
}
</style>
