<script setup lang="ts">
import { FileTextOutlined, SwapOutlined } from '@ant-design/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, mediaUrl, type CompareCell, type CompareResult, type CompareRow, type Composite, type Metric, type Run, type Scheme } from '../api'
import CompareChart from '../components/CompareChart.vue'
import PageHeader from '../components/PageHeader.vue'
import { STATUS_BADGE, STATUS_LABEL, fmtCost, fmtMetric, fmtTokens, isActive } from '../format'

const route = useRoute()
const router = useRouter()
const ids = computed(() => String(route.query.runs ?? '').split(',').map(Number).filter((n) => n > 0))
const data = ref<CompareResult | null>(null)
const options = ref<Run[]>([])
const schemes = ref<Scheme[]>([])
const composite = ref<Composite | null>(null)
const schemeId = computed({
  get: () => (route.query.scheme ? Number(route.query.scheme) : undefined),
  set: (v: number | undefined) => router.replace({ path: '/compare', query: { ...route.query, scheme: v ? String(v) : undefined } }),
})
const error = ref('')
const focus = ref<number | null>(null) // dataset id whose details are shown
const view = ref<'diff' | 'all_wrong' | 'all'>('diff')
const subset = ref<string | undefined>()
const rows = ref<CompareRow[]>([])
const rowTotal = ref(0)
const page = ref(1)
let timer: ReturnType<typeof setInterval> | undefined

async function loadOptions() {
  options.value = (await api.runs({ status: 'completed', page_size: 100 }, true)).items
}
async function load() {
  if (ids.value.length < 2) { data.value = null; error.value = ''; return }
  try {
    data.value = await api.compare(ids.value, true)
    error.value = ''
    await loadComposite()
    if (!data.value.runs.some((r) => r.dataset_id === focus.value)) focus.value = data.value.runs[0].dataset_id
  } catch (e: any) { error.value = e.response?.data?.message ?? '加载失败'; data.value = null }
}
async function loadComposite() {
  composite.value = null
  if (!schemeId.value || ids.value.length < 2) return
  try { composite.value = await api.composite(ids.value, schemeId.value, true) } catch { composite.value = null }
}
onMounted(async () => {
  schemes.value = await api.schemes()
  await Promise.all([loadOptions(), load()])
  timer = setInterval(() => data.value?.runs.some(isActive) && load(), 3000)
})
onBeforeUnmount(() => clearInterval(timer))
watch(ids, load)
watch(schemeId, loadComposite)
const ranked = computed(() => composite.value?.models.filter((m) => m.score !== null) ?? [])
const incomplete = computed(() => composite.value?.models.filter((m) => m.score === null) ?? [])

const picker = computed({
  get: () => ids.value,
  set: (v: number[]) => router.replace({ path: '/compare', query: v.length ? { runs: v.join(','), scheme: route.query.scheme } : {} }),
})
const pickerOptions = computed(() => {
  const seen = new Map<number, Run>()
  for (const r of [...(data.value?.runs ?? []), ...options.value]) seen.set(r.id, r)
  return [...seen.values()].sort((a, b) => b.id - a.id).map((r) => ({ value: r.id, label: `#${r.id}  ${r.model_name} × ${r.dataset_name}${r.limit ? `（每子集 ${r.limit} 题）` : ''}` }))
})

// ---- one dataset at a time
const datasets = computed(() => {
  const m = new Map<number, string>()
  for (const r of data.value?.runs ?? []) m.set(r.dataset_id, `${r.dataset_name} v${r.dataset_version}`)
  return [...m.entries()].map(([value, label]) => ({ value, label }))
})
const group = computed(() => (data.value?.runs ?? []).filter((r) => r.dataset_id === focus.value))
const done = (r: Run) => r.status === 'completed'
const mx = (r: Run) => data.value?.metrics[String(r.id)] ?? []
const find = (r: Run, key: string, sub = 'OVERALL'): Metric | undefined => mx(r).find((m) => m.key === key && m.subset === sub)

type Cell = { text: string; best: boolean }
type Line = { key: string; label: string; section?: string; cells: Record<number, Cell> }

/** The winner of a row: highest or lowest depending on the metric's direction (ties all count). */
function mark(values: Record<number, number | null>, direction: string): Set<number> {
  const entries = Object.entries(values).filter(([, v]) => v != null) as [string, number][]
  if (entries.length < 2 || direction === 'none') return new Set()
  const best = direction === 'lower_is_better' ? Math.min(...entries.map((e) => e[1])) : Math.max(...entries.map((e) => e[1]))
  return new Set(entries.filter((e) => e[1] === best).map((e) => Number(e[0])))
}
function line(key: string, label: string, runs: Run[], pick: (r: Run) => { v: number | null; text: string } | null, direction: string): Line {
  const picked = Object.fromEntries(runs.map((r) => [r.id, done(r) || key.startsWith('use') ? pick(r) : null]))
  const winners = mark(Object.fromEntries(runs.map((r) => [r.id, picked[r.id]?.v ?? null])), direction)
  return { key, label, cells: Object.fromEntries(runs.map((r) => [r.id, { text: picked[r.id]?.text ?? '—', best: winners.has(r.id) }])) }
}
const lines = computed<Line[]>(() => {
  const runs = group.value
  if (!runs.length) return []
  const out: Line[] = []
  const qualityKeys = [...new Map(runs.flatMap((r) => mx(r).filter((m) => m.kind === 'quality' && m.subset === 'OVERALL').map((m) => [m.key, m]))).values()]
  for (const q of qualityKeys) out.push({ ...line(q.key, q.label + (q.primary ? ' · 主指标' : ''), runs, (r) => { const m = find(r, q.key); return m ? { v: m.value, text: fmtMetric(m) } : null }, q.direction), section: '得分' })
  if (runs.some((r) => r.adjusted)) {
    const prim = qualityKeys.find((q) => q.primary)
    out.push(line('adjusted', '复核后得分（宽松匹配 + 人工）', runs, (r) => (r.adjusted ? { v: r.adjusted.adjusted, text: r.adjusted.display } : r.headline ? { v: r.headline.value, text: r.headline.display + '（未改判）' } : null), prim?.direction ?? 'higher_is_better'))
  }
  const perf: [string, string][] = [['latency_mean', '平均延迟'], ['latency_p90', '延迟 P90'], ['input_tokens_mean', '平均输入 token'], ['output_tokens_mean', '平均输出 token'], ['output_tps', '输出吞吐']]
  perf.forEach(([k, l], i) => {
    const dir = k === 'output_tps' ? 'higher_is_better' : k.startsWith('latency') ? 'lower_is_better' : 'none'
    const row = line(k, l, runs, (r) => { const m = find(r, k); return m ? { v: m.value, text: fmtMetric(m) } : null }, dir)
    out.push(i === 0 ? { ...row, section: '速度与用量' } : row)
  })
  out.push({ ...line('use_tokens', '累计用量（含重试）', runs, (r) => (r.input_tokens == null ? null : { v: r.input_tokens + (r.output_tokens ?? 0), text: fmtTokens(r.input_tokens + (r.output_tokens ?? 0)) }), 'lower_is_better'), section: undefined })
  out.push(line('use_cost', '费用', runs, (r) => (r.cost == null ? null : { v: r.cost, text: fmtCost(r.cost) }), 'lower_is_better'))
  return out
})
const columns = computed(() => [
  { title: '', key: 'label', width: 190, fixed: 'left' as const },
  ...group.value.map((r) => ({ title: r.model_name, key: `r${r.id}`, runId: r.id })),
])

const chart = computed(() => {
  const runs = group.value.filter(done)
  const prim = runs.map((r) => mx(r).find((m) => m.primary && m.subset === 'OVERALL')).find(Boolean)
  if (runs.length < 2 || !prim) return null
  const subs = [...new Set(runs.flatMap((r) => mx(r).filter((m) => m.key === prim.key && m.subset !== 'OVERALL').map((m) => m.subset)))]
  const cats = subs.length > 1 ? [...subs, 'OVERALL'] : ['OVERALL']
  return {
    title: prim.label,
    max: prim.display_unit === '%' ? 100 : undefined,
    categories: cats.map((c) => (c === 'OVERALL' ? '合计' : c)),
    series: runs.map((r) => ({
      name: r.model_name,
      values: cats.map((c) => { const m = find(r, prim.key, c); return m?.value == null ? null : m.value * m.display_multiplier }),
      displays: cats.map((c) => { const m = find(r, prim.key, c); return m ? fmtMetric(m) : '' }),
    })),
  }
})

// ---- matrix over datasets (only when the selection spans several)
const matrix = computed(() => {
  const runs = data.value?.runs ?? []
  const models = [...new Map(runs.map((r) => [r.model_id, r.model_name])).entries()]
  const dsets = [...new Map(runs.map((r) => [r.dataset_id, `${r.dataset_name} v${r.dataset_version}`])).entries()]
  return {
    models,
    rows: dsets.map(([did, label]) => {
      const cells: Record<number, { text: string; best: boolean }> = {}
      const vals: Record<number, number | null> = {}
      for (const [mid] of models) {
        const r = runs.filter((x) => x.dataset_id === did && x.model_id === mid && done(x)).sort((a, b) => b.id - a.id)[0]
        vals[mid] = r?.headline?.value ?? null
        cells[mid] = { text: r?.headline ? `${r.headline.display}` : '—', best: false }
      }
      const win = mark(vals, 'higher_is_better')
      for (const [mid] of models) cells[mid].best = win.has(mid)
      return { key: did, label, cells }
    }),
  }
})

// ---- per-question view
const canCompareSamples = computed(() => group.value.filter(done).length >= 2)
const sampleIds = computed(() => group.value.filter(done).map((r) => r.id))
const subsetOptions = computed(() => [...new Set(group.value.flatMap((r) => mx(r).filter((m) => m.kind === 'quality' && m.subset !== 'OVERALL').map((m) => m.subset)))])
async function loadSamples() {
  if (!canCompareSamples.value) { rows.value = []; rowTotal.value = 0; return }
  const r = await api.compareSamples(sampleIds.value, { view: view.value, subset: subset.value, page: page.value, page_size: 8 })
  rows.value = r.items
  rowTotal.value = r.total
}
watch([sampleIds, view, subset, focus], () => { page.value = 1; loadSamples() }, { deep: true })
watch(page, loadSamples)

const verdict = (c: CompareCell | null): ['good' | 'bad' | 'warn' | '', string] => (!c ? ['', '无结果'] : c.error ? ['warn', '出错'] : c.is_correct === true ? ['good', '答对'] : c.is_correct === false ? ['bad', '答错'] : ['', '未判定'])
const name = (id: string | number) => group.value.find((r) => r.id === Number(id))?.model_name ?? `#${id}`
const pretty = (o: unknown) => JSON.stringify(o)
const imgs = (row: CompareRow) => row.media.map((m, k) => ({ m, k })).filter((x) => x.m.type === 'image' && x.m.kind !== 'missing')
const headline = (r: Run) => (done(r) && r.headline ? r.headline.display : STATUS_LABEL[r.status])
</script>

<template>
  <div class="page">
    <PageHeader title="模型对比" sub="把同一批题上的多个模型放在一起看：得分、速度、费用，以及它们到底在哪些题上不一样。">
      <a-button v-if="ids.length >= 2 && data && data.runs.every((r) => r.status === 'completed')" tag="a" :href="`/api/v1/compare/report?run_ids=${ids.join(',')}&download=true${schemeId ? '&scheme_id=' + schemeId : ''}`"><template #icon><FileTextOutlined /></template>导出报告</a-button>
    </PageHeader>

    <div class="card card-pad" style="margin-bottom: 16px">
      <div class="label">选择要对比的评测任务（2–8 个，建议同一个评测集、同样的设置）</div>
      <a-select v-model:value="picker" mode="multiple" :options="pickerOptions" placeholder="选择已完成的评测任务" style="width: 100%" :max-tag-count="8" show-search option-filter-prop="label" />
    </div>

    <a-empty v-if="ids.length < 2 && !error" class="card card-pad" style="padding: 56px 0">
      <template #description><div>选两个以上的任务开始对比</div><div class="faint" style="font-size: 13px; margin-top: 4px">也可以在“评测任务”里勾选几行，点“对比所选”。</div></template>
      <a-button type="primary" @click="router.push('/runs/new')">发起一次多模型评测</a-button>
    </a-empty>
    <a-alert v-if="error" type="error" show-icon :message="error" style="margin-bottom: 16px" />

    <template v-if="data">
      <a-alert v-if="data.warnings.length" type="warning" show-icon message="这些差异会影响对比的可信度" style="margin-bottom: 16px">
        <template #description><ul style="margin: 4px 0 0; padding-left: 18px"><li v-for="w in data.warnings" :key="w">{{ w }}</li></ul></template>
      </a-alert>

      <div class="grid" style="grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); margin-bottom: 16px">
        <div v-for="r in data.runs" :key="r.id" class="card card-pad runchip clickable" @click="router.push(`/runs/${r.id}`)">
          <div class="row-between"><b style="font-size: 15px">{{ r.model_name }}</b><a-badge :status="STATUS_BADGE[r.status]" /></div>
          <div class="faint" style="font-size: 12.5px">{{ r.dataset_name }} v{{ r.dataset_version }} · #{{ r.id }}</div>
          <div class="big">{{ headline(r) }}</div>
        </div>
      </div>

      <!-- composite score -->
      <div class="card card-pad" style="margin-bottom: 16px">
        <div class="row-between" style="flex-wrap: wrap; gap: 10px">
          <h3 class="section-title" style="margin: 0">综合得分</h3>
          <div class="row">
            <a-select v-model:value="schemeId" allow-clear :options="schemes.map((s) => ({ value: s.id, label: s.name }))" placeholder="选择评分方案" style="width: 220px" />
            <a-button @click="router.push('/schemes')">管理方案</a-button>
          </div>
        </div>
        <p v-if="!schemeId" class="faint" style="margin: 10px 0 0; font-size: 13.5px">
          {{ schemes.length ? '选一个评分方案，把多个评测集的得分按权重合成一个综合得分。' : '还没有评分方案。到“评分方案”里按你们看重的程度设置各评测集的权重。' }}
        </p>
        <template v-else-if="composite">
          <a-alert v-if="composite.models.some((m) => m.trial)" type="warning" show-icon style="margin-top: 12px" message="包含限制了题数的试跑结果，样本少、分数波动大，综合得分只能做粗略参考。" />
          <div v-for="(m, i) in ranked" :key="m.model_id" class="crow">
            <span class="rk">{{ i + 1 }}</span>
            <b class="mn">{{ m.model_name }}</b>
            <div class="track"><div class="fill" :style="{ width: m.score! + '%' }" /></div>
            <span class="sc">{{ m.score!.toFixed(1) }}</span>
            <a-popover trigger="click" placement="left">
              <template #content>
                <div v-for="p in m.parts" :key="p.dataset_name" style="font-size: 13px; line-height: 1.8">
                  {{ p.dataset_name }}：<b>{{ p.value.toFixed(1) }}</b> × {{ p.weight_pct.toFixed(1) }}% = {{ (p.value * p.weight_pct / 100).toFixed(1) }}
                  <span class="faint">（任务 #{{ p.run_id }}{{ p.reviewed ? '，复核后' : '' }}）</span>
                </div>
              </template>
              <a class="why">怎么算的</a>
            </a-popover>
          </div>
          <div v-for="m in incomplete" :key="m.model_id" class="crow dim">
            <span class="rk">—</span><b class="mn">{{ m.model_name }}</b>
            <span class="faint" style="flex: 1">
              无法计算：<template v-if="m.missing.length">还没有这些评测集的结果：{{ m.missing.join('、') }}</template><template v-if="m.problems.length">{{ m.problems.join('；') }}</template>
            </span>
          </div>
          <p class="faint" style="margin: 12px 0 0; font-size: 12.5px">方案“{{ composite.scheme.name }}”：{{ composite.scheme.items.map((i) => `${i.dataset_name} ${i.weight_pct.toFixed(0)}%`).join(' · ') }}。综合得分是加权平均，不同评测集的难度不同，分数接近时请回头看具体的错题。</p>
        </template>
      </div>

      <!-- several datasets: matrix -->
      <div v-if="datasets.length > 1" class="card card-pad" style="margin-bottom: 16px">
        <h3 class="section-title">各评测集上的主指标</h3>
        <p class="section-sub">每个格子是该模型在该评测集上最新一次已完成任务的主指标，绿色是这一行最高。不同评测集的指标含义可能不同，别跨行比大小。</p>
        <a-table :data-source="matrix.rows" :pagination="false" size="small" row-key="key" :columns="[{ title: '评测集', key: 'label' }, ...matrix.models.map(([mid, n]) => ({ title: n, key: `m${mid}`, mid }))]">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'label'"><b>{{ record.label }}</b></template>
            <template v-else><span :class="{ win: record.cells[(column as any).mid].best }">{{ record.cells[(column as any).mid].text }}</span></template>
          </template>
        </a-table>
      </div>

      <div v-if="datasets.length > 1" class="row" style="margin-bottom: 12px"><span class="muted">查看明细：</span><a-segmented v-model:value="focus" :options="datasets" /></div>

      <!-- detail for one dataset -->
      <div v-if="group.length" class="card card-pad" style="margin-bottom: 16px">
        <h3 class="section-title">逐项对比 <span class="faint" style="font-weight: 400; font-size: 13px">· 绿色表示这一行最好</span></h3>
        <a-table :columns="columns" :data-source="lines" :pagination="false" size="middle" row-key="key" :scroll="{ x: 'max-content' }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'label'">
              <div v-if="record.section" class="sect">{{ record.section }}</div><span class="muted">{{ record.label }}</span>
            </template>
            <template v-else><span class="cellv" :class="{ win: record.cells[(column as any).runId].best }">{{ record.cells[(column as any).runId].text }}</span></template>
          </template>
        </a-table>
      </div>

      <div v-if="chart" class="card card-pad" style="margin-bottom: 16px">
        <h3 class="section-title">{{ chart.title }}（按子集）</h3>
        <CompareChart :categories="chart.categories" :series="chart.series" :max="chart.max" />
      </div>

      <!-- per-question -->
      <div v-if="group.length" class="card card-pad">
        <div class="row-between" style="flex-wrap: wrap; gap: 12px; margin-bottom: 4px">
          <div><h3 class="section-title"><SwapOutlined /> 逐题对比</h3><p class="section-sub" style="margin: 0">同一道题，各个模型答得对不对、各自怎么答的。</p></div>
          <div class="row">
            <a-segmented v-model:value="view" :options="[{ value: 'diff', label: '有分歧' }, { value: 'all_wrong', label: '全都答错' }, { value: 'all', label: '全部' }]" />
            <a-select v-if="subsetOptions.length > 1" v-model:value="subset" allow-clear placeholder="全部子集" style="width: 150px" :options="subsetOptions.map((s) => ({ value: s, label: s }))" />
          </div>
        </div>
        <a-alert v-if="!canCompareSamples" type="info" show-icon style="margin-top: 12px" message="这个评测集上至少要有两个已完成的任务，才能逐题对比。" />
        <a-empty v-else-if="!rows.length" style="padding: 36px 0" :description="view === 'diff' ? '没有分歧：所有模型在每道题上的对错都一样' : '没有符合条件的题'" />

        <div v-for="row in rows" :key="`${row.subset}-${row.idx}`" class="qrow">
          <div class="qhead">
            <span class="muted">{{ subsetOptions.length > 1 ? row.subset + ' · ' : '' }}#{{ row.idx }}</span>
            <span v-if="row.target != null" class="faint">标准答案 <b class="mono" style="color: var(--teal)">{{ row.target }}</b></span>
          </div>
          <div class="qbody">
            <div v-if="imgs(row).length" style="flex: none; width: 170px">
              <a-image-preview-group>
                <template v-for="x in imgs(row)" :key="x.k"><a-image :src="mediaUrl(row.media_run_id, { id: row.media_sample_id, media: row.media }, x.k)" :width="170" style="border-radius: var(--radius-sm); margin-bottom: 6px; display: block" /></template>
              </a-image-preview-group>
            </div>
            <div style="flex: 1; min-width: 0">
              <div class="pre qtext">{{ row.question }}</div>
              <div class="answers">
                <div v-for="(cell, rid) in row.results" :key="rid" class="ans" :class="verdict(cell)[0]">
                  <div class="row-between"><b style="font-size: 13px">{{ name(rid) }}</b><span class="vtag" :class="verdict(cell)[0]">{{ verdict(cell)[1] }}</span></div>
                  <template v-if="cell">
                    <div v-if="cell.tool_calls" class="mono pre" style="margin-top: 4px">{{ cell.tool_calls.map((t) => `${t.name}(${pretty(t.arguments)})`).join('\n') }}</div>
                    <div v-else class="pre atext">{{ cell.extracted && cell.extracted !== cell.prediction ? cell.extracted : cell.prediction || '（空）' }}</div>
                    <div v-if="cell.reviewed" class="faint" style="font-size: 12px; margin-top: 2px">人工复核{{ cell.engine_correct !== cell.is_correct ? '（改判）' : '' }}</div>
                    <a-tooltip v-else-if="cell.auto_reason && cell.engine_correct !== cell.is_correct" :title="cell.auto_reason"><div class="faint" style="font-size: 12px; margin-top: 2px; cursor: help">{{ cell.is_correct ? '宽松匹配通过（引擎判错）' : '参数检查未通过（引擎判对）' }}</div></a-tooltip>
                    <a-tooltip v-if="cell.extracted && cell.extracted !== cell.prediction && !cell.tool_calls" :title="cell.prediction"><div class="faint" style="font-size: 12px; margin-top: 2px; cursor: help">抽取自完整回答（悬停查看）</div></a-tooltip>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
        <a-pagination v-if="rowTotal > 8" v-model:current="page" :page-size="8" :total="rowTotal" :show-size-changer="false" style="margin-top: 16px; text-align: right" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.runchip { padding: 14px 16px; transition: transform 0.15s; }
.runchip:hover { transform: translateY(-2px); }
.big { font-family: var(--font-display); font-size: 26px; font-weight: 650; letter-spacing: -0.02em; margin-top: 6px; font-variant-numeric: tabular-nums; }
.sect { font-size: 12px; color: var(--ink-muted); text-transform: none; margin-bottom: 2px; }
.cellv { font-variant-numeric: tabular-nums; padding: 2px 8px; border-radius: 6px; }
.win { background: var(--signal-soft); color: var(--signal); font-weight: 650; padding: 2px 8px; border-radius: 6px; }
.qrow { border: 1px solid var(--line); border-radius: var(--radius-md); margin-top: 14px; overflow: hidden; }
.qhead { display: flex; justify-content: space-between; padding: 9px 16px; background: var(--surface-2); font-size: 13px; }
.qbody { display: flex; gap: 16px; padding: 14px 16px; }
.qtext { font-size: 13.5px; max-height: 110px; overflow: auto; margin-bottom: 10px; line-height: 1.6; }
.answers { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
.ans { border: 1px solid var(--line); border-left-width: 4px; border-radius: var(--radius-md); padding: 8px 12px; background: var(--surface); }
.ans.good { border-left-color: var(--teal); background: var(--teal-soft); }
.ans.bad { border-left-color: var(--danger); background: var(--danger-soft); }
.ans.warn { border-left-color: var(--amber); }
.atext { font-size: 13px; margin-top: 4px; max-height: 120px; overflow: auto; line-height: 1.55; }
.vtag { font-size: 12px; padding: 0 8px; border-radius: var(--radius-pill); background: var(--surface-2); color: var(--ink-muted); }
.vtag.good { background: var(--teal-soft); color: var(--teal); }
.vtag.bad { background: var(--danger-soft); color: var(--danger); }
.vtag.warn { background: var(--amber-soft); color: var(--amber); }
.crow { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.crow.dim { opacity: .75; }
.rk { width: 22px; height: 22px; border-radius: 50%; background: var(--signal); color: var(--on-signal); font-size: 12px; font-family: var(--font-display); display: grid; place-items: center; flex: none; }
.crow.dim .rk { background: var(--line); color: var(--ink-muted); }
.mn { width: 170px; flex: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { flex: 1; height: 12px; border-radius: var(--radius-pill); background: var(--surface-2); overflow: hidden; }
.fill { height: 100%; border-radius: var(--radius-pill); background: var(--signal); }
.sc { font-family: var(--font-display); width: 56px; text-align: right; font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.why { font-size: 13px; cursor: pointer; flex: none; }
@media (max-width: 900px) { .qbody { flex-direction: column; } }
</style>
