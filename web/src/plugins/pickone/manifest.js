/**
 * PickOne 的对外介绍。字段与后端 `plugins/pickone/plugin.py` 里的
 * `PluginManifest` 一一对应；`nav` / `adminNav` 只在前端使用。
 */
export default {
  slug: 'pickone',
  name: 'PickOne 表情包',
  tag: '表情包数据',
  icon: 'Grid',
  summary: '维护「来只」表情包的图片描述、类别别名与点赞评论。',
  home: '/pickone',
  order: 10,
  accent: {
    tint: 'rgba(158, 87, 114, 0.07)',
    tint_strong: 'rgba(158, 87, 114, 0.14)',
    ink: '#764156',
    track: 'rgba(158, 87, 114, 0.16)',
    glow: 'rgba(158, 87, 114, 0.24)',
  },
  /** 进入本工具后，导航栏左边这几个入口 */
  nav: [
    { path: '/pickone', label: '所有表情', icon: 'Grid' },
    { path: '/pickone/submissions', label: '我的提交', icon: 'Tickets' },
  ],
  /** 管理员在本工具内额外看到的入口 */
  adminNav: [{ path: '/pickone/review', label: '审核台', icon: 'Stamp', badge: true }],
}
