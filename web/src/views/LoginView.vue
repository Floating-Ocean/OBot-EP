<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import { session } from '@/stores/session'
import OBotLogo from '@/components/OBotLogo.vue'

const route = useRoute()
const router = useRouter()

const mode = ref('login')
const submitting = ref(false)
const authConfig = ref({ allow_register: true, needs_bootstrap: false })
const form = reactive({ username: '', password: '', display_name: '' })

async function loadConfig() {
  try {
    authConfig.value = await api.authConfig()
  } catch {
    /* 保留默认值 */
  }
}

async function submit() {
  if (!form.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (form.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }

  submitting.value = true
  try {
    if (mode.value === 'login') {
      await session.login({ username: form.username.trim(), password: form.password })
    } else {
      await session.register({
        username: form.username.trim(),
        password: form.password,
        display_name: form.display_name.trim(),
      })
    }

    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    // 普通用户被重定向到管理员页时兜底回首页
    if (!session.isAdmin.value && redirect.startsWith('/pickone/review')) {
      router.replace('/')
    } else {
      router.replace(redirect)
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  form.password = ''
}

onMounted(loadConfig)
</script>

<template>
  <div class="login">
    <div class="login-glow login-glow--a" />
    <div class="login-glow login-glow--b" />

    <div class="login-card">
      <div class="login-brand">
        <OBotLogo :size="46" />
        <div class="brand-copy">
          <h1>OBot's Endpoint</h1>
          <p>OBot-ACM 的公开数据维护入口</p>
        </div>
      </div>

      <el-alert
        v-if="authConfig.needs_bootstrap"
        type="warning"
        :closable="false"
        show-icon
        title="还没有账号"
        description="初始管理员的用户名和密码已打印在后端启动日志里；也可以用 python -m server.manage passwd 重置。"
        class="ep-mb"
      />

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" size="large" placeholder="用户名" />
        </el-form-item>

        <el-form-item v-if="mode === 'register'" label="昵称（可选）">
          <el-input v-model="form.display_name" size="large" placeholder="别人看到的名字" />
        </el-form-item>

        <el-form-item :label="mode === 'login' ? '密码' : '密码（至少 8 位）'">
          <el-input
            v-model="form.password"
            size="large"
            type="password"
            show-password
            placeholder="密码"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-button
          type="primary"
          size="large"
          class="login-submit"
          :loading="submitting"
          @click="submit"
        >
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </el-button>
      </el-form>

      <div class="login-foot">
        <template v-if="mode === 'login'">
          <span class="ep-small ep-muted">还没有账号？</span>
          <el-link v-if="authConfig.allow_register" type="primary" @click="switchMode">
            注册
          </el-link>
          <span v-else class="ep-small ep-muted">请联系管理员开通</span>
        </template>
        <template v-else>
          <span class="ep-small ep-muted">已有账号？</span>
          <el-link type="primary" @click="switchMode">去登录</el-link>
        </template>
      </div>
    </div>

    <p class="login-note">嗨，登录以查看更多内容哦</p>
  </div>
</template>

<style scoped>
.login {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 26px;
  padding: 56px 24px;
  overflow: hidden;
}

/* 两团柔光，让登录页不至于是纯灰底 */
.login-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  pointer-events: none;
}

.login-glow--a {
  width: 620px;
  height: 620px;
  top: -220px;
  left: -140px;
  background: rgba(123, 92, 255, 0.3);
}

.login-glow--b {
  width: 540px;
  height: 540px;
  bottom: -200px;
  right: -120px;
  background: rgba(255, 95, 126, 0.26);
}

.login-card {
  position: relative;
  width: 100%;
  max-width: 420px;
  background: var(--ep-surface);
  border: 1px solid var(--ep-border);
  border-radius: 24px;
  padding: 42px 42px 34px;
  box-shadow: 0 24px 60px rgba(23, 26, 38, 0.14), 0 4px 14px rgba(23, 26, 38, 0.06);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-bottom: 32px;
}

.brand-copy h1 {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-copy p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ep-ink-faint);
}

.login-submit {
  width: 100%;
  margin-top: 8px;
}

.login-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 22px;
}

.login-note {
  position: relative;
  margin: 0;
  font-size: 12.5px;
  color: var(--ep-ink-faint);
}
</style>
