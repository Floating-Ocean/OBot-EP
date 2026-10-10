<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { session } from '@/stores/session'
import { theme } from '@/stores/theme'
import { currentPlugin, pluginBySlug } from '@/plugins/registry'
import OBotLogo from '@/components/OBotLogo.vue'

const props = defineProps({
  /**
   * 每个工具的导航角标数（slug → 件数），由 `App.vue` 汇总：
   * 框架数得到的提交单 + 插件自报的待办。**必须是分工具的**，见那里的注释。
   */
  badges: { type: Object, default: () => ({}) },
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

/**
 * 右上角只报两个版本：上游 OBot-ACM、本站 OBot-EP。
 * 插件各自维护的模块版本（PickOne 的模块版本号等）不往这里塞 —— 那是工具自己的事，
 * 需要露出的工具应该在自己的页面里显示。
 */
const versions = ref({})

const obotVersion = computed(() => versions.value.obot ?? '')

/** 后端给的是裸版本号（0.2.0），页面上统一带 v；读不到就退回打包时写死的那个 */
const epVersion = computed(() => {
  const value = String(versions.value.obot_ep ?? APP_VERSION)
  return value.startsWith('v') ? value : `v${value}`
})

onMounted(async () => {
  try {
    // /meta/versions 是公开接口，正好只给版本号（不带 commit），这里够用
    versions.value = await api.versions()
  } catch {
    /* 读不到就只显示本工具写死的版本号 */
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
 * 导航项上的角标数：只认**当前这个工具**的数。
 * 这一行本来就只显示一个工具的页面，所以整行共用一个 key（工具 slug）。
 */
const badgeCount = computed(() => props.badges[contextPlugin.value?.manifest.slug ?? ''] ?? 0)

/**
 * 账号菜单的条目。账号管理 / 操作日志是**框架**的全局页面，不属于任何工具，
 * 所以不进工具导航行 —— 整行只有一种含义：「当前工具里的页面」。
 * 全局动作收在右上角账号菜单里，那里本来就是「跟当前工具无关」的地方。
 */
const accountMenu = computed(() => {
  const items = [
    {
      command: 'theme',
      label: '颜色模式',
      // 跟随系统时用中性图标，自己选过就显示对应的那半
      icon:
        theme.preference.value === 'system'
          ? 'Monitor'
          : theme.isDark.value
            ? 'Moon'
            : 'Sunny',
    },
    { command: 'password', label: '修改密码', icon: 'Key', divided: true },
  ]
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

/* ---- 第二级导航 ---- */

/**
 * 导航项可以带 `children`：同一个区块里的几个工作面（「审核台」下面的
 * 「提交审核 / 待审图片」就是）。`children` 由插件在 manifest 里声明。
 *
 * 这样顶级导航仍然只有一个入口，但每个工作面各占一格、点一下就到 ——
 * 不需要先进一个落地页再点第二次，也不会出现两个并列的「xx审核」被读成
 * 同一个控件的两个标签页。
 */
function isPathActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

/**
 * 当前所在的区块：命中的顶级项，或命中了某个子项的那个顶级项。
 *
 * 必须取**匹配最深**的那一项：`/pickone`（所有表情）是所有子路径的前缀，
 * 先命中的话任何页面都会被判成「在 所有表情 区块里」，二级导航永远不出现。
 * 第一级的选中态（activePath）用的是同一套最长匹配。
 */
const activeSection = computed(() => {
  const matched = toolNavItems.value
    .filter(
      (item) =>
        isPathActive(item.path) || (item.children ?? []).some((child) => isPathActive(child.path)),
    )
    .sort((a, b) => b.path.length - a.path.length)
  return matched[0] ?? null
})

const subNavItems = computed(() => activeSection.value?.children ?? [])

/** 子页签的选中态同样取最长前缀，避免 /review 把 /review/images 也点亮 */
const activeSubPath = computed(() => {
  const matched = subNavItems.value
    .filter((child) => isPathActive(child.path))
    .sort((a, b) => b.path.length - a.path.length)
  return matched[0]?.path ?? ''
})

/* ---- 账号菜单 ---- */

const passwordOpen = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '', confirm: '', busy: false })

/*
 * 颜色模式：先问「是否跟随系统」，不跟随时再挑浅色/深色。
 * 改一下立刻生效（不等「保存」），所以对话框本身就是预览。
 */
const themeOpen = ref(false)

const followSystem = computed({
  get: () => theme.preference.value === 'system',
  set: (on) => theme.set(on ? 'system' : theme.isDark.value ? 'dark' : 'light'),
})

const themeMode = computed({
  // 关掉「跟随系统」时从当前实际生效的那一档接着走，不会突然跳回浅色
  get: () =>
    theme.preference.value === 'system'
      ? theme.isDark.value
        ? 'dark'
        : 'light'
      : theme.preference.value,
  set: (value) => theme.set(value),
})

async function handleAccountCommand(command) {
  // 框架管理页从菜单里进：它们不属于任何工具，所以不占工具导航行
  if (command.startsWith('go:')) {
    router.push(command.slice(3))
    return
  }

  if (command === 'theme') {
    themeOpen.value = true
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
        <el-tooltip placement="bottom-end" effect="light" :show-after="120" :offset="10">
          <template #content>
            <div class="version-tip">
              <div class="version-tip-row">
                <span class="version-tip-key">OBot-ACM</span>
                <span class="version-tip-val">{{ obotVersion || '未读到' }}</span>
              </div>
              <div class="version-tip-row">
                <span class="version-tip-key">OBot-EP</span>
                <span class="version-tip-val">{{ epVersion }}</span>
              </div>
              <span class="version-tip-note">上游 Bot 与本站维护工具的版本</span>
            </div>
          </template>
          <span class="version">
            <span class="version-dot" />
            <template v-if="obotVersion">
              <span class="version-obot">OBot {{ obotVersion }}</span>
            </template>
          </span>
        </el-tooltip>
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
            <em v-if="item.badge && badgeCount" class="nav-badge">{{ badgeCount }}</em>
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

      <!--
        第二级导航：当前区块的几个工作面。刻意做得比第一级轻（文字 + 下划线），
        否则两排一模一样的药丸会像两排并列的主导航，又把「一层入口」讲回成两个工具。
      -->
      <nav v-if="subNavItems.length" class="shell-subnav">
        <div class="shell-inner subnav-row">
          <router-link
            v-for="child in subNavItems"
            :key="child.path"
            :to="child.path"
            class="subnav-link"
            :class="{ 'is-active': child.path === activeSubPath }"
          >
            {{ child.label }}
          </router-link>
        </div>
      </nav>
    </header>

    <main class="shell-main">
      <router-view v-slot="{ Component }">
        <component :is="Component" @refresh-summary="$emit('refresh-summary')" />
      </router-view>
    </main>

    <el-drawer v-model="themeOpen" title="颜色模式" size="min(440px, 92vw)">
      <div class="theme-row">
        <div>
          <p class="theme-row-title">跟随系统</p>
        </div>
        <el-switch v-model="followSystem" size="large" />
      </div>

      <div class="theme-row theme-row--picked" :class="{ 'is-disabled': followSystem }">
        <div>
          <p class="theme-row-title">颜色模式</p>
          <p class="theme-row-hint">
            {{ followSystem ? '跟随系统时由系统决定' : '自己指定，覆盖系统设置' }}
          </p>
        </div>
        <el-radio-group v-model="themeMode" :disabled="followSystem">
          <el-radio-button value="light">浅色</el-radio-button>
          <el-radio-button value="dark">深色</el-radio-button>
        </el-radio-group>
      </div>

      <template #footer>
        <el-button type="primary" @click="themeOpen = false">完成</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="passwordOpen" title="修改密码" size="min(440px, 92vw)">
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
    </el-drawer>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  /*
   * 进入动效（页面内容上浮 / 二级导航行下滑）共用的曲线。
   *
   * 不用 ease-out：它是「起步中等、尾巴很长」——0.4s 里前 0.16s 只走完 ~78%，
   * 剩下 0.24s 都在挪最后那两像素，看着就是拖拉。
   * 这条（easeOutQuint）前 0.12s 走完 ~83%、约 0.18s 就基本到位，
   * 于是 0.4s 只剩一点点收尾，不再拖；位移本身也没被砍掉。
   * 想更利落可以换 cubic-bezier(0.16, 1, 0.3, 1)（近似 easeOutExpo，更极端）。
   */
  --ep-enter-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.shell-bar {
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: saturate(170%) blur(18px);
  border-bottom: 1px solid var(--ep-border);
  position: sticky;
  top: 0;
  z-index: 10;
}

/* 顶栏与导航条是「半透明白玻璃」，深色下要换成深色玻璃（同一个变量换不了透明度底） */
html.dark .shell-bar {
  background: rgba(20, 25, 33, 0.82);
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

.version-sep {
  color: var(--ep-border-strong);
}

.version-ep {
  font-weight: 600;
  color: var(--ep-ink-faint);
}

/* tip：两行键值 + 一行说明，比原生 title 那种挤成一行、还带插件版本的长串好读 */
.version-tip {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 186px;
  padding: 2px;
  font-size: 12.5px;
  line-height: 1.5;
}

.version-tip-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 20px;
}

.version-tip-key {
  color: var(--ep-ink-faint);
}

.version-tip-val {
  font-family: var(--ep-font-mono);
  font-weight: 700;
}

.version-tip-note {
  margin-top: 2px;
  padding-top: 6px;
  border-top: 1px solid var(--ep-border);
  color: var(--ep-ink-faint);
  font-size: 11.5px;
}

/* 头像里可能是一个 emoji（宽度远大于单个字母），缩一号字保证放得下 */
:deep(.el-avatar) {
  font-size: 15px;
  line-height: 28px;
}

/* 账号头像改用通用人形图标：昵称可能是 emoji 或符号，取首字既不稳定也不好看 */
.account-avatar {
  background: linear-gradient(145deg, rgba(168, 213, 194, 0.32), rgba(95, 141, 126, 0.26));
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

html.dark .shell-nav {
  background: rgba(20, 25, 33, 0.5);
}

/* 第二级导航：比第一级矮、比第一级淡，靠下划线而不是药丸表示选中 */
.shell-subnav {
  border-top: 1px solid var(--ep-border);
  background: rgba(255, 255, 255, 0.3);
  /* 进这个区块时整行淡入下滑一点，别硬生生「跳」出来 */
  animation: ep-subnav-in 0.4s var(--ep-enter-ease);
}

html.dark .shell-subnav {
  background: rgba(20, 25, 33, 0.34);
}

@keyframes ep-subnav-in {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
}

.shell-inner.subnav-row {
  height: clamp(44px, 4vw, 52px);
  gap: clamp(16px, 1.8vw, 30px);
  /*
   * 和第一级药丸里的文字左对齐：药丸自己有一圈内边距，纯文字的页签得补上同样的量，
   * 否则两行的第一个字会错开一格，看着就是没对齐。
   */
  padding-left: calc(clamp(18px, 3.2vw, 52px) + clamp(12px, 1.4vw, 18px));
}

.subnav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 100%;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ep-ink-muted);
  white-space: nowrap;
  transition: color 0.4s ease;
}

.subnav-link:hover {
  color: var(--ep-ink);
}

.subnav-link.is-active {
  color: var(--ep-brand-b);
}

/*
 * 下划线压在行的下边框上，读起来像「页签」而不是「按钮」。
 * 用 scaleX 从左侧长出来，切换时是「划过去」而不是硬切。
 * 颜色用 --ep-brand-b 而不是那条深色渐变：深色模式下渐变不换色，
 * 2px 的深青压在深底上根本看不见。
 */
.subnav-link::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--ep-brand-b);
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform 0.4s ease;
}

.subnav-link.is-active::after {
  transform: scaleX(1);
}

/*
 * 路由切换：新页面淡入并轻微上浮。
 *
 * 只做「进」不做「出」：旧元素直接移除，既不会出现两页同时在位、
 * 把容器高度顶跳一下，也不要求每个页面组件都是单根元素（过渡要求单根）。
 */
.shell-main > :deep(*) {
  animation: ep-page-in 0.5s var(--ep-enter-ease);
}

@keyframes ep-page-in {
  from {
    opacity: 0;
    transform: translateY(13px);
  }
}

/* 上面这几处动效对「减少动态效果」的用户一律关掉 */
@media (prefers-reduced-motion: reduce) {
  .shell-subnav,
  .shell-main > :deep(*) {
    animation: none;
  }

  .subnav-link,
  .subnav-link::after {
    transition: none;
  }
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
  /*
   * 只过渡能过渡的属性。选中态那层底是渐变（background-image），它本来就动画不了，
   * 所以文字颜色不能再单独淡入 —— 否则背景「啪」地换掉、字却慢慢变色，很怪。
   * 悬停底色是 background-color，能过渡，保留。
   */
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}

.nav-link:hover {
  background-color: rgba(20, 22, 31, 0.05);
  color: var(--ep-ink);
}

html.dark .nav-link:hover {
  background-color: rgba(255, 255, 255, 0.07);
}

.nav-link.is-active {
  background-image: var(--ep-brand-gradient-deep);
  color: #fff;
  box-shadow: 0 6px 16px rgba(78, 127, 112, 0.28);
}

.nav-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ---- 颜色模式对话框 ---- */

.theme-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.theme-row + .theme-row {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--ep-border);
}

.theme-row-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ep-ink);
}

.theme-row-hint {
  margin: 2px 0 0;
  font-size: 12.5px;
  color: var(--ep-ink-faint);
}

.theme-row--picked {
  margin-bottom: 16px;
}

/* 跟随系统时「颜色模式」是灰的，让它再淡一点，别看着像可点的 */
.theme-row--picked.is-disabled {
  opacity: 0.6;
  margin-bottom: 16px;
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

/* 选中态是深青药丸：红数字压在绿底上太打架，改成白底青字 */
.nav-link.is-active .nav-badge {
  background: #fff;
  color: var(--ep-brand-b);
}

/* 深色下 --ep-danger 是提亮过的「文字红」，拿来当实心底又亮又压不住白字；
   实心改回按钮那支深红（白字 4.9:1），也不那么抢眼。
   选中态那条 (0,3,0) 优先级更高，白底青字不受影响 */
html.dark .nav-badge {
  background: var(--el-color-danger);
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
