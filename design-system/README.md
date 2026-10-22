# Heng 衡

> 衡，量也。—— 给大模型一杆公平、清晰、看得见过程的秤。

Heng 是一个大模型评测平台的设计系统：排行榜、能力雷达、评测任务、对战竞技场。它是**夜间优先**的数据界面——深色石墨底上只有一种荧光青柠色负责「最重要的那件事」，其余全部交给中性色与动效。

完整页面见组件 **Dashboard**（右上角可切换日 / 夜主题）。

## 设计原则

1. **数据是主角。** 卡片只用 `line` 描边和 `shadow-card` 分层，不做花哨背景；色彩只给数据和状态。
2. **一页只有一个 signal。** `signal`（荧光青柠）只用于：主按钮、第一名、进行中、图表第一序列。看到它就知道该看哪里。
3. **动效解释变化。** 每个动画都在回答一个问题：数字从哪来（CountUp）、排名怎么变（Leaderboard 弹性重排）、任务进行到哪（流光进度条）、谁赢了（判定条展开）。不做纯装饰的动效——背景光晕除外，且它慢到几乎察觉不到。
4. **颜色之外还有形状。** 涨跌用 ▲▼，状态用文字胶囊，对战 A/B 用字母标签，色弱用户也能读懂。

## 颜色

| 角色 | Token | 用法 |
| --- | --- | --- |
| 画布 | `bg` | 页面底色，叠加 `space-5`（20px）步长的点阵 |
| 卡片 | `surface` / `surface-2` | 卡片 / 轨道、输入框、悬停行 |
| 线 | `line` / `line-strong` | 装饰描边 / 控件边框（≥3:1） |
| 文字 | `ink` / `ink-muted` | 主文字 / 次要文字（两主题均 ≥4.5:1） |
| 品牌 | `signal` + `on-signal` + `signal-soft` | 荧光青柠；夜间 `#c8f169`，日间加深为 `#4c7600` 以保证对比度 |
| 序列 | `coral` · `teal` · `amber` | 图表第 2–4 序列，亦表示对比方 / 完成 / 排队 |
| 状态 | `danger` | 只表示失败 |

图表多序列顺序固定：**signal → coral → teal → amber**，四者明度不同，不只靠色相区分。

## 字体

- **Space Grotesk**（display）：页面标题与所有数字，等宽数字 `tabular-nums`，滚动时不抖动。
- **IBM Plex Sans + Noto Sans SC**（sans）：正文、表格、按钮。
- **JetBrains Mono**（mono）：日志、样本 ID、延迟、token 数、涨跌幅。

字体均来自 Google Fonts，由 `components/bundle.css` 顶部 `@import` 载入。

## 间距与圆角

4 / 8 / 12 / 16 / 20 / 28px（`space-1` … `space-7`）。卡片内边距 `space-5`，卡片间隙 `space-4`，页面边距 `space-7`。
圆角：徽章与进度条 `radius-sm`，按钮与输入框 `radius-md`，卡片 `radius-lg`，胶囊与头像 `radius-pill`。

## 动效

动效时长与曲线在 `bundle.css` 的 `:root` 中定义：

| 变量 | 值 | 用于 |
| --- | --- | --- |
| `--hg-ease` | `cubic-bezier(.2,.8,.2,1)` | 入场、进度、数字滚动 |
| `--hg-spring` | `cubic-bezier(.34,1.56,.64,1)` | 排名重排、标签指示器、徽章弹出、判定条 |
| `--hg-fast` / `--hg-med` / `--hg-slow` | 160 / 320 / 700ms | 按压 / 悬停 / 入场 |

- **入场**：卡片上移 14px 淡入，按 80–90ms 错峰（`.hg-enter` + `--d`）。
- **数据到达**：数字滚动、趋势线描绘、环形填充、条形伸展，都在 0.9–1.6s 内完成。
- **持续状态**：只有「真的在进行中」的东西可以循环动——运行中徽章的脉冲、进度条流光、流式光标。
- **减少动效**：系统开启 `prefers-reduced-motion` 时，所有组件直接呈现终态。

## 语气

界面文字简短、动词开头、不加句号：「新建评测」「全部任务」「重播」。数字带单位：「12,032 样本」「1.8s」「¥3,482」。模型名保留原始大小写。

## 组件

Button · Badge · Tabs · CountUp · Sparkline · MetricCard · ScoreRing · Leaderboard · Radar · RunProgress · ArenaCompare · Dashboard（整页示例）。
全局对象 `window.Heng`，依赖 React 18。示例数据中的模型与机构均为虚构。
