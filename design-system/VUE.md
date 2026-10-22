# 在本项目（Vue 3 + Ant Design Vue 4 + ECharts）中落地 Heng 衡

`README.md` 讲设计原则；这份讲**怎么映射到本项目现有代码**。`bundle.js` 是 React 写的参考实现，只用来看动效和结构怎么做，**不要引入**，组件一律用 Vue 3 + TS 重写。

## 0. 先认清：哪些是演示内容

`demo.html` / `screenshots/` 里的 Dashboard 用了虚构数据，还有本平台**没有**的功能：对战竞技场、GPU 配额、实时样本日志、搜索框。只借鉴视觉语言和动效，**不要因为设计稿里有就新增功能**。本平台的页面以 `frontend/src/views/` 现有 8 个页面为准。

## 1. 接入 token

1. 把 `design-system/tokens.css` 在 `main.ts` 中于 `style.css` 之前引入（或复制到 `src/styles/tokens.css`）。它用 `[data-theme="dark"|"light"]` 切换，和 `theme.ts` 里写 `document.documentElement.dataset.theme` 的方式一致，无需改动切换逻辑。
2. 字体：在 `index.html` 引 Google Fonts（Space Grotesk / IBM Plex Sans / Noto Sans SC / JetBrains Mono，见 `bundle.css` 第一行）。内网部署打不开时用系统字体兜底即可，字体栈已写好。
3. `style.css` 里旧的 `--c-*` 变量**改成指向新 token**（先保留别名，页面逐个迁完再删）：

| 旧变量 | 新 token | 备注 |
| --- | --- | --- |
| `--c-bg` | `--bg` | |
| `--c-card` | `--surface` | |
| `--c-border` | `--line` | 控件边框用 `--line-strong` |
| `--c-text` | `--ink` | |
| `--c-text-2` | `--ink-muted` | |
| `--c-text-3` | `--ink-muted` | 旧的 text-3 对比度不够承载文字，统一到 ink-muted |
| `--c-primary` | `--signal` | |
| `--c-primary-soft` | `--signal-soft` | |
| `--c-good` / `--c-good-soft` | `--teal` / `color-mix(in srgb, var(--teal) 12%, transparent)` | 判对、通过、已完成 |
| `--c-bad` / `--c-bad-soft` | `--danger` / `color-mix(in srgb, var(--danger) 10%, transparent)` | 判错、失败 |
| `--c-warn` | `--amber` | |
| `--c-code` | `--surface-2` | 代码块字体用 `var(--font-mono)` |
| `--shadow` | `--shadow-card` | |

## 2. Ant Design Vue 主题（theme.ts）

`antdTheme` 的 token 改为 Heng 的值（ConfigProvider 不能读 CSS 变量，必须写字面值，两套主题分开写）：

```ts
const H = {
  dark:  { bg: '#0d0f0b', surface: '#15180f', surface2: '#1e2218', line: '#2a2f22', lineStrong: '#454c39', ink: '#eef1e6', muted: '#9da391', signal: '#c8f169', onSignal: '#11140b', teal: '#5fd6c6', amber: '#f4bb45', danger: '#ff6b6b' },
  light: { bg: '#f5f4ee', surface: '#ffffff', surface2: '#eeede5', line: '#dedcd1', lineStrong: '#a9a797', ink: '#15170f', muted: '#5c604f', signal: '#4c7600', onSignal: '#ffffff', teal: '#0c6f67', amber: '#94590a', danger: '#c21d1d' },
}
// token:
//   colorPrimary / colorInfo: signal   colorSuccess: teal   colorWarning: amber   colorError: danger
//   colorBgLayout: bg   colorBgContainer: surface   colorBorder: lineStrong   colorBorderSecondary: line
//   colorText: ink   colorTextSecondary: muted
//   colorTextLightSolid: onSignal   ← 必须设！深色模式下 signal 是亮青柠，Ant 默认白字在主按钮上看不清
//   borderRadius: 10   borderRadiusLG: 16   borderRadiusSM: 6
//   fontFamily: "'IBM Plex Sans', 'Noto Sans SC', 'PingFang SC', system-ui, sans-serif"
//   motionEaseOut: 'cubic-bezier(.2,.8,.2,1)'
```

侧栏：现在写死了 `#12141c` 和 `theme="dark"`。改成 `background: var(--surface)` + 右边框 `var(--line)`，菜单选中态用 `--signal-soft` 底 + 左侧 2px `--signal` 内阴影（见 `bundle.css` 的 `.hg-nav-ind`），两种主题都跟随切换。

## 3. ECharts 配色

`CompareChart.vue` / `SubsetChart.vue` 的 `PALETTE` 换成按主题取值的序列，**顺序固定**：

- dark：`['#c8f169', '#ff8a66', '#5fd6c6', '#f4bb45']`
- light：`['#4c7600', '#b8400f', '#0c6f67', '#94590a']`

超过 4 个模型时，后续序列用 `--ink-muted` 灰色，或让用户选择高亮哪几个，不要再加新色相。坐标轴文字 `--ink-muted`，网格线 `--line`，条形图圆角 `radius-sm`（6）。动画：`animationDuration: 900, animationEasing: 'cubicOut'`。

## 4. 组件对照（参考实现 → 本项目）

| Heng 参考组件 | 本项目对应 | 做法 |
| --- | --- | --- |
| MetricCard | `components/MetricCard.vue` | 加数字滚动（value 现在是格式化字符串，需要多传一个原始数值 prop）；可选 sparkline |
| Badge | `components/StatusBadge.vue` | 状态 → tone：运行中 signal + pulse，排队 amber，完成 teal，失败 danger |
| Leaderboard | `CompareView.vue` 的排名 / 综合得分表 | 切换评测集或方案时行弹性重排（绝对定位 + `translateY` 过渡，见 `bundle.js` Leaderboard 与 `.hg-lb-row`） |
| Radar | `CompareView.vue` 多评测集对比 | 可用 ECharts radar 实现，配色同上 |
| RunProgress | `RunsView.vue` / `RunDetailView.vue` 的进度 | 进度条宽度过渡 + 运行中流光；数据来自真实接口轮询，不要 simulate |
| Tabs | Ant `a-segmented` 或自写 | 滑动指示器用 spring 曲线 |
| Button | Ant `a-button` | 不重写，靠主题 token；按压缩放 / 悬停 glow 用全局 CSS 补 |
| ScoreRing / CountUp / Sparkline | 新建通用组件 | 写成 `components/ds/` 下的小组件，`useTween` 改写为 composable |

动效实现要点：数字缓动写成 `composables/useTween.ts`（requestAnimationFrame + easeOutCubic，值变化时从当前值继续）；入场动画用 `.hg-enter` + `--d` 错峰；全部尊重 `prefers-reduced-motion`（`bundle.css` 末尾有全局兜底）。

## 5. 验收

- 每改一个页面：`npm run build`（含 vue-tsc）通过；两种主题下截图，对照 `screenshots/` 的风格。
- 全局搜索 `src/` 下硬编码的 `#xxxxxx` 色值和旧的 `--c-*` 变量，迁完后删别名。
- e2e：Ant 按钮文字选择器沿用正则（如 `保\s*存`）。
