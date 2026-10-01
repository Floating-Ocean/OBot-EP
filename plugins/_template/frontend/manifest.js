/**
 * @@NAME@@ 的对外介绍。字段与后端 `plugins/@@SLUG@@/plugin.py` 里的 `PluginManifest`
 * 一一对应；`nav` / `adminNav` 只在前端使用。slug 两边必须一致。
 */
export default {
  slug: '@@SLUG@@',
  name: '@@NAME@@',
  tag: '@@TAG@@',
  icon: 'Grid',
  summary: 'TODO(@@SLUG@@): 一句话说明这个工具能改什么。',
  home: '/@@SLUG@@',
  order: 100,
  accent: {
    tint: 'rgba(56, 189, 214, 0.10)',
    tint_strong: 'rgba(56, 189, 214, 0.26)',
    ink: '#0f6f85',
    track: 'rgba(56, 189, 214, 0.2)',
    glow: 'rgba(56, 189, 214, 0.3)',
  },
  /** 进入本工具后，导航栏左边这几个入口 */
  nav: [{ path: '/@@SLUG@@', label: '条目', icon: 'Grid' }],
  /** 管理员在本工具内额外看到的入口 */
  adminNav: [{ path: '/@@SLUG@@/review', label: '审核台', icon: 'Stamp', badge: true }],
}
