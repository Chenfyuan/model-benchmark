import type { Metric, Run } from './api'

export const CAPABILITY_LABEL: Record<string, string> = { doc_chart: '文档图表', general_qa: '通用问答', tool_call: '工具调用' }
export const CAPABILITY_HINT: Record<string, string> = {
  doc_chart: '读图表、文档页面、OCR',
  general_qa: '通用看图问答与推理',
  tool_call: '该不该调用工具、参数格式对不对',
}

export const KIND_LABEL: Record<string, string> = { benchmark: '公开基准', vqa: '视觉问答', vmcq: '选择题', fc: '工具调用' }

export const STATUS_LABEL: Record<Run['status'], string> = {
  queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消',
}
/** Heng tone of the status pill: signal = in progress, amber = waiting, teal = done, danger = failed only */
export const STATUS_TONE: Record<Run['status'], 'signal' | 'amber' | 'teal' | 'danger' | 'muted'> = {
  queued: 'amber', running: 'signal', completed: 'teal', failed: 'danger', cancelled: 'muted',
}
/** Ant Design `a-badge` status values */
export const STATUS_BADGE: Record<Run['status'], 'default' | 'processing' | 'success' | 'error' | 'warning'> = {
  queued: 'default', running: 'processing', completed: 'success', failed: 'error', cancelled: 'warning',
}
export const STAGE_LABEL: Record<string, string> = {
  queued: '排队中', preparing: '准备中', downloading: '下载基准数据', evaluating: '评测中', collecting: '汇总结果', done: '',
}

export function fmtMetric(m: Pick<Metric, 'value' | 'display_multiplier' | 'precision' | 'display_unit'>): string {
  if (m.value == null) return '-'
  return (m.value * (m.display_multiplier || 1)).toFixed(m.precision) + (m.display_unit || '')
}

export function fmtTime(s: string | null): string {
  if (!s) return '-'
  // the backend stores naive UTC timestamps
  return new Date(s.endsWith('Z') ? s : s + 'Z').toLocaleString('zh-CN', { hour12: false })
}

/** "刚刚 / 5 分钟前 / 2 小时前 / 3 天前" for list views */
export function fmtAgo(s: string | null): string {
  if (!s) return '-'
  const sec = Math.max(0, Math.round((Date.now() - new Date(s + 'Z').getTime()) / 1000))
  if (sec < 45) return '刚刚'
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟前`
  if (sec < 86400) return `${Math.round(sec / 3600)} 小时前`
  return `${Math.round(sec / 86400)} 天前`
}

export function fmtDuration(a: string | null, b: string | null): string {
  if (!a) return '-'
  const start = new Date(a + 'Z').getTime()
  const end = b ? new Date(b + 'Z').getTime() : Date.now()
  const sec = Math.max(0, Math.round((end - start) / 1000))
  return sec < 60 ? `${sec} 秒` : `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

export const isActive = (r: Run) => r.status === 'queued' || r.status === 'running'

export function fmtTokens(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k'
  return String(n)
}

/** Money without a currency symbol (the platform does not know the currency of the prices a user typed). */
export function fmtCost(c: number | null | undefined): string {
  if (c == null) return '—'
  return c < 0.01 ? c.toFixed(4) : c < 100 ? c.toFixed(2) : c.toFixed(0)
}

export const STOP_REASON_LABEL: Record<string, string> = { budget_run: '超出单次上限', budget_month: '超出月度上限' }
