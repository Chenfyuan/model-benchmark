import axios from 'axios'
import { message } from 'ant-design-vue'

export interface CheckItem { ok: boolean; detail: string; latency_ms?: number; input_tokens?: number }
export interface CheckResult {
  ok: boolean
  checks: { text: CheckItem; image: CheckItem; tools: CheckItem }
  warnings: string[]
  baseline_input_tokens: number | null
}
export interface ModelEndpoint {
  id: number; name: string; protocol: 'openai' | 'anthropic'; base_url: string; model_name: string
  api_key_hint: string; price_input_per_mtok: number | null; price_output_per_mtok: number | null
  last_check: CheckResult | null; created_at: string
}
export interface Dataset {
  id: number; name: string; version: number; source: 'builtin' | 'custom'; kind: string
  benchmark_id: string | null; capability: string | null; description: string; verified: boolean
  num_samples: number | null; created_at: string
}
export interface Run {
  id: number; model_id: number; model_name: string; dataset_id: number; dataset_name: string; dataset_version: number
  judge_model_id: number | null; judge_model_name: string | null; parent_run_id: number | null
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; stage: string; progress: number
  error: string | null; limit: number | null; config: Record<string, number>; engine: string
  engine_version: string | null; created_at: string; started_at: string | null; finished_at: string | null
  attempts: number; reused_samples: number | null
  input_tokens: number | null; output_tokens: number | null; cost: number | null
  stop_reason: 'budget_run' | 'budget_month' | null
  headline: { label: string; value: number | null; display: string } | null
  /** headline recomputed after lenient matching / manual review; null when nothing changed or it cannot be recomputed */
  adjusted: { adjusted: number; display: string; n_lenient: number; n_manual: number } | null
}
export interface Metric {
  kind: string; key: string; label: string; subset: string; value: number | null; num: number | null
  display_multiplier: number; display_unit: string; precision: number; direction: string; primary: boolean
}
export interface Sample {
  id: number; idx: number; subset: string; question: string; media: { type: string; kind: string; ref: string }[]
  target: string | null; prediction: string | null; extracted: string | null
  tool_calls: { name: string; arguments: unknown }[] | null; scores: Record<string, unknown>
  score: number | null; is_correct: boolean | null; judge_output: string | null
  auto_correct: boolean | null; auto_reason: string | null; review_correct: boolean | null; review_note: string | null; final_correct: boolean | null
  latency: number | null; input_tokens: number | null; output_tokens: number | null; error: string | null
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface Estimate {
  num_samples: number | null; avg_input_tokens: number; avg_output_tokens: number; token_source: string
  total_tokens: number | null; cost: number | null; notes: string[]
}

export interface BudgetLimits {
  per_run_max_tokens: number | null; per_run_max_cost: number | null
  monthly_max_tokens: number | null; monthly_max_cost: number | null
}
export interface BudgetView {
  limits: BudgetLimits
  usage: { month: string; tokens: number; cost: number; runs: number }
  unpriced_models: string[]
}
export interface CompareResult { runs: Run[]; metrics: Record<string, Metric[]>; warnings: string[] }
export interface CompareCell {
  sample_id: number; is_correct: boolean | null; score: number | null; prediction: string | null; extracted: string | null
  tool_calls: { name: string; arguments: unknown }[] | null; latency: number | null; error: string | null
  engine_correct?: boolean | null; auto_reason?: string | null; reviewed?: boolean
}
export interface CompareRow {
  subset: string; idx: number; question: string; target: string | null
  media: { type: string; kind: string; ref: string }[]; media_run_id: number; media_sample_id: number
  results: Record<string, CompareCell | null>
}

export const http = axios.create({ baseURL: '/api/v1', timeout: 120000 })

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const d = err.response?.data
    if (!err.config?.silent) {
      const detail = Array.isArray(d?.details) && d.details.length ? '\n' + d.details.slice(0, 5).join('\n') : ''
      message.error({ content: (d?.message ?? (typeof d?.detail === 'string' ? d.detail : '请求失败：' + err.message)) + detail, duration: 6 })
    }
    return Promise.reject(err)
  },
)

declare module 'axios' { interface AxiosRequestConfig { silent?: boolean } }

export const api = {
  models: () => http.get<ModelEndpoint[]>('/models').then((r) => r.data),
  createModel: (b: object) => http.post<ModelEndpoint>('/models', b).then((r) => r.data),
  updateModel: (id: number, b: object) => http.put<ModelEndpoint>(`/models/${id}`, b).then((r) => r.data),
  deleteModel: (id: number) => http.delete(`/models/${id}`),
  checkModel: (id: number) => http.post<CheckResult>(`/models/${id}/check`).then((r) => r.data),
  datasets: (params?: object) => http.get<Dataset[]>('/datasets', { params }).then((r) => r.data),
  capabilities: () => http.get<Record<string, string>>('/datasets/capabilities').then((r) => r.data),
  uploadDataset: (form: FormData) => http.post<Dataset>('/datasets', form).then((r) => r.data),
  previewDataset: (id: number) => http.get<unknown[]>(`/datasets/${id}/preview`).then((r) => r.data),
  deleteDataset: (id: number) => http.delete(`/datasets/${id}`),
  estimate: (b: object) => http.post<Estimate>('/runs/estimate', b).then((r) => r.data),
  createRuns: (b: object, key: string, silent = false) =>
    http.post<Run[]>('/runs', b, { headers: { 'Idempotency-Key': key }, silent }).then((r) => r.data),
  budget: () => http.get<BudgetView>('/settings/budget').then((r) => r.data),
  saveBudget: (b: BudgetLimits) => http.put<BudgetView>('/settings/budget', b).then((r) => r.data),
  compare: (ids: number[], silent = false) => http.get<CompareResult>('/compare', { params: { run_ids: ids.join(',') }, silent }).then((r) => r.data),
  compareSamples: (ids: number[], params: object) =>
    http.get<Page<CompareRow>>('/compare/samples', { params: { run_ids: ids.join(','), ...params } }).then((r) => r.data),
  runs: (params: object, silent = false) => http.get<Page<Run>>('/runs', { params, silent }).then((r) => r.data),
  run: (id: number, silent = false) => http.get<Run>(`/runs/${id}`, { silent }).then((r) => r.data),
  cancelRun: (id: number) => http.post<Run>(`/runs/${id}/cancel`).then((r) => r.data),
  retryRun: (id: number) => http.post<Run>(`/runs/${id}/retry`).then((r) => r.data),
  rerun: (id: number) => http.post<Run>(`/runs/${id}/rerun`).then((r) => r.data),
  deleteRun: (id: number) => http.delete(`/runs/${id}`),
  metrics: (id: number) => http.get<Metric[]>(`/runs/${id}/metrics`).then((r) => r.data),
  samples: (id: number, params: object) => http.get<Page<Sample>>(`/runs/${id}/samples`, { params }).then((r) => r.data),
  reviewSample: (runId: number, sampleId: number, correct: boolean | null, note?: string) =>
    http.put<Sample>(`/runs/${runId}/samples/${sampleId}/review`, { correct, note }).then((r) => r.data),
  rescore: (id: number) => http.post<{ checked: number; upgraded: number; skipped_reason_judge: number }>(`/runs/${id}/rescore`).then((r) => r.data),
  log: (id: number) => http.get<string>(`/runs/${id}/log`, { transformResponse: (d) => d }).then((r) => r.data),
}

export const mediaUrl = (runId: number, s: Pick<Sample, 'id' | 'media'>, k: number) =>
  s.media[k].kind === 'url' ? s.media[k].ref : `/api/v1/runs/${runId}/samples/${s.id}/media/${k}`
