import http from './http'
import { coreApi } from './core'
import { pluginApis } from '@/plugins/registry'

/**
 * 全站 API 门面。
 *
 * 由两部分组成：
 *   - 框架级接口（`./core`）：认证、元信息、账号、审核队列……
 *   - 每个插件在 `web/src/plugins/<slug>/api.js` 里声明的接口，挂在 `api.<slug>.*`
 *
 * **新写的插件代码请用 `api.<slug>.方法名()`。** 平铺的 `api.方法名()` 是给早期代码
 * 留的兼容层：只有「全站唯一」的方法名才会被平铺出来，两个插件都叫 `withdraw`
 * 时它不会出现在平铺接口上（否则就是「调了别的工具的方法」这种难查的 bug），
 * 但永远不会因此让页面起不来。
 *
 * 另外：这个模块和 `@/plugins/registry` 是一对**循环依赖**（`@/api` → registry →
 * `web/src/plugins/<slug>/index.js`），所以门面必须**延迟构造**。若在模块求值期直接
 * `Object.assign({}, pluginApis)`，pluginApis 可能还在 TDZ 里，插件命名空间就会
 * 变成 undefined —— 症状是首页卡片报 "Cannot read properties of undefined"。
 * 用 Proxy 把构造推迟到第一次取属性（那时所有模块都已求值完），这类顺序问题就不会
 * 再随「谁先 import 谁」而变。
 */
let facade = null

function resolveFacade() {
  if (facade) return facade

  const merged = { ...coreApi }
  const coreNames = new Set(Object.keys(coreApi))
  const owners = new Map([...coreNames].map((name) => [name, 'core']))
  const shadowed = new Map()
  const ambiguous = new Map()

  for (const [slug, methods] of Object.entries(pluginApis)) {
    for (const [name, fn] of Object.entries(methods)) {
      if (coreNames.has(name)) {
        // 框架接口优先：平铺的 api.<name> 永远是框架那份。
        // 插件想给同名接口加自己的行为（例如注入 plugin 过滤），走 api.<slug>.<name>。
        if (!shadowed.has(name)) shadowed.set(name, [])
        shadowed.get(name).push(slug)
        continue
      }
      if (owners.has(name)) {
        // 插件之间重名：谁都不平铺，只保留 api.<slug>.<name> 这种明确写法
        delete merged[name]
        if (!ambiguous.has(name)) ambiguous.set(name, [owners.get(name)])
        ambiguous.get(name).push(slug)
        continue
      }
      merged[name] = fn
      owners.set(name, slug)
    }
  }

  if (import.meta.env?.DEV) {
    const report = [
      ...(ambiguous.size
        ? [
            '这些方法名被多个工具使用，只保留命名空间写法（api.<slug>.<name>）：',
            ...[...ambiguous.entries()].map(([name, slugs]) => `  ${name} -> ${slugs.join(', ')}`),
          ]
        : []),
      ...(shadowed.size
        ? [
            '这些插件方法与框架接口重名，平铺时以框架为准（插件版走 api.<slug>.<name>）：',
            ...[...shadowed.entries()].map(([name, slugs]) => `  ${name} -> ${slugs.join(', ')}`),
          ]
        : []),
    ]
    if (report.length) console.info(`[obot-ep]\n${report.join('\n')}`)
  }

  facade = Object.assign(merged, pluginApis)
  return facade
}

export const api = new Proxy(
  {},
  {
    get: (_target, property) => resolveFacade()[property],
    has: (_target, property) => property in resolveFacade(),
    ownKeys: () => Reflect.ownKeys(resolveFacade()),
    getOwnPropertyDescriptor: (_target, property) =>
      Reflect.getOwnPropertyDescriptor(resolveFacade(), property) ?? {
        configurable: true,
        enumerable: true,
        value: resolveFacade()[property],
      },
  },
)

export { http }
export default api
