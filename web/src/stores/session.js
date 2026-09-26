import { computed, reactive } from 'vue'
import { api } from '@/api'

/** 全局会话状态（够用就好，不引入 Pinia）。 */
const state = reactive({
  user: null,
  allowRegister: true,
  ready: false,
})

let inflight = null

async function loadMe(force = false) {
  if (state.ready && !force) return state.user
  if (inflight) return inflight

  inflight = (async () => {
    try {
      const data = await api.meta()
      state.user = data.user
      state.allowRegister = data.allow_register
    } catch {
      state.user = null
      try {
        const cfg = await api.authConfig()
        state.allowRegister = cfg.allow_register
      } catch {
        /* 后端不可用时保持默认 */
      }
    } finally {
      state.ready = true
      inflight = null
    }
    return state.user
  })()

  return inflight
}

export const session = {
  state,
  isLoggedIn: computed(() => Boolean(state.user)),
  isAdmin: computed(() => Boolean(state.user?.is_admin)),
  label: computed(() => state.user?.label ?? ''),

  loadMe,

  async login(payload) {
    const data = await api.login(payload)
    state.user = data.user
    state.ready = true
    return data.user
  },

  async register(payload) {
    const data = await api.register(payload)
    state.user = data.user
    state.ready = true
    return data.user
  },

  async logout() {
    try {
      await api.logout()
    } finally {
      state.user = null
    }
  },

  refresh() {
    return loadMe(true)
  },
}
