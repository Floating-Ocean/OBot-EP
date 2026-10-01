<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { session } from '@/stores/session'
import { currentPlugin, pluginBySlug } from '@/plugins/registry'
import OBotLogo from '@/components/OBotLogo.vue'

const props = defineProps({
  /** 审核台待处理数量，用于导航角标 */
  pendingCount: { type: Number, default: 0 },
})

const route = useRoute()
const router = useRouter()

const APP_VERSION = '0.2.0'

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
const versions = ref({})

const versionLabel = computed(() => versions.value.obot ?? `v${APP_VERSION}`)

/** 插件回报的上游模块版本，例如 PickOne 的模块版本号。 */
const moduleVersions = computed(() =>
  Object.entries(versions.value)
    .filter(([key]) => !['obot', 'obot_base', 'commit', 'obot_ep'].includes(key))
    .filter(([, value]) => value)
    .map(([key, value]) => `${pluginBySlug(key)?.manifest.name ?? key} ${value}`),
)

const versionTitle = computed(() => {
  const parts = [`本工具 OBot-EP v${APP_VERSION}`]
  if (versions.value.obot) parts.push(`OBot-ACM ${versions.value.obot}`)
  if (versions.value.commit) parts.push(`commit ${versions.value.commit}`)
  parts.push(...moduleVersions.value)
  return parts.join(' · ')
})

onMounted(async () => {
  try {
    // /meta/info 是登录后才读得到的完整版本信息（含 commit）；
    // 公开的 /meta/versions 只给版本号，不带 commit。
    const data = await api.meta()
    versions.value = data.versions ?? {}
  } catch {
    /* 读不到就只显示本工具版本 */
  }
})

/**
 * 导航栏完全由插件注册表驱动：进到哪个工具就显示哪个工具的 nav / adminNav。
 * 加一个工具不需要改这个文件。
 */
const CORE_NAV = [{ path: '/', label: '工具', icon: 'Menu' }]

/** 账号与审计日志是框架能力，管理员在任何页面都能进 */
const CORE_ADMIN_NAV = [
  { path: '/admin/users', label: '账号管理', icon: 'User' },
  { path: '/admin/logs', label: '操作日志', icon: 'Document' },
]

const activePlugin = computed(() => currentPlugin(route.path))

/**
 * 记住上次待过的工具。框架自己的管理页（账号 / 日志）不属于任何工具，
 * 但在这类页面上把工具导航留着，用户点进去以后还能一步点回来。
 * 存在 sessionStorage 里是为了刷新后仍然记得。
 */
const LAST_TOOL_KEY = 'obot-ep.last-tool'

function readLastTool() {
  try {
    return sessionStorage.getItem(LAST_TOOL_KEY) ?? ''
  } catch {
    return '' // 读不到就退化成「没有记忆」，只影响这一个便利功能
  }
}

const lastToolSlug = ref(readLastTool())

watch(
  () => activePlugin.value?.manifest.slug ?? '',
  (slug) => {
    if (!slug) return
    lastToolSlug.value = slug
    try {
      sessionStorage.setItem(LAST_TOOL_KEY, slug)
    } catch {
      /* 存不下就只在本次会话里记着 */
    }
  },
  { immediate: true },
)

/** 框架管理页：有 meta.admin、但不属于任何插件 */
const inFrameworkAdmin = computed(() => Boolean(route.meta.admin) && !route.meta.plugin)

/**
 * 导航栏要显示哪个工具的入口：优先当前工具；框架管理页上退回上次待过的工具。
 * 其余情况（工具首页、404）没有「当前工具」，只显示框架导航。
 */
const contextPlugin = computed(
  () => activePlugin.value ?? (inFrameworkAdmin.value ? pluginBySlug(lastToolSlug.value) : null),
)

const toolName = computed(() => contextPlugin.value?.manifest.name ?? "OBot's Endpoint")

const toolPrefix = computed(() => contextPlugin.value?.manifest.home ?? '')

/**
 * 工具组：这个工具自己的页面（nav + 管理员额外看到的 adminNav）。
 * 框架入口不混进来（它们收在右上角账号菜单里）—— 否则「审核台」会被账号 / 日志
 * 隔开，看着不像同一个工具的东西，整行的含义也变成两种。
 */
const toolNavItems = computed(() => {
  const plugin = contextPlugin.value
  if (!plugin) return CORE_NAV
  const items = [...(plugin.manifest.nav ?? [])]
  if (session.isAdmin.value) items.push(...(plugin.manifest.adminNav ?? []))
  return items
})

/**
 * 账号菜单的条目。账号管理 / 操作日志是**框架**的全局页面，不属于任何工具，
 * 所以不进工具导航行 —— 整行只有一种含义：「当前工具里的页面」。
 * 全局动作收在右上角账号菜单里，那里本来就是「跟当前工具无关」的地方。
 */
const accountMenu = computed(() => {
  const items = [{ command: 'password', label: '修改密码', icon: 'Key' }]
  if (session.isAdmin.value) {
    for (const item of CORE_ADMIN_NAV) {
      items.push({ ...item, command: `go:${item.path}`, divided: true })
    }
  }
  items.push({ command: 'logout', label: '退出登录', icon: 'SwitchButton', divided: true })
  return items
})

/** 最长前缀匹配，避免 /pickone 把 /pickone/submissions 也点亮 */
const activePath = computed(() => {
  const matches = [...toolNavItems.value, ...CORE_ADMIN_NAV]
    .filter((item) => route.path === item.path || route.path.startsWith(`${item.path}/`))
    .sort((a, b) => b.path.length - a.path.length)
  return matches[0]?.path ?? route.path
})

/* ---- 账号菜单 ---- */

const passwordOpen = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '', confirm: '', busy: false })

async function handleAccountCommand(command) {
  // 框架管理页从菜单里进：它们不属于任何工具，所以不占工具导航行
  if (command.startsWith('go:')) {
    router.push(command.slice(3))
    return
  }

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

      <nav v-if="toolNavItems.length" class="shell-nav">
        <div class="shell-inner nav-row">
          <router-link
            v-for="item in toolNavItems"
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
                  <el-dropdown-item
                    v-for="item in accountMenu"
                    :key="item.command"
                    :command="item.command"
                    :divided="item.divided"
                  >
                    <el-icon><component :is="item.icon" /></el-icon>&nbsp;&nbsp;
                    <span>{{ item.label }}</span>
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

/* 账号菜单里标记当前所在的框架页 */
.menu-check {
  margin-left: 8px;
  color: var(--ep-brand-b);
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
