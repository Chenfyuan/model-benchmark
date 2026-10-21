<script setup lang="ts">
import { ArrowLeftOutlined, DownloadOutlined, FileTextOutlined, ReloadOutlined, RedoOutlined, StopOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, mediaUrl, type Metric, type Run, type Sample } from '../api'
import MetricCard from '../components/MetricCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import SubsetChart from '../components/SubsetChart.vue'
import { fmtDuration, fmtMetric, fmtTime, isActive } from '../format'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)
const run = ref<Run | null>(null)
const metrics = ref<Metric[]>([])
const tab = ref('overview')
const samples = ref<Sample[]>([])
const sampleTotal = ref(0)
const samplePage = ref(1)
const filter = ref({ correct: '', subset: undefined as string | undefined, q: '' })
const logText = ref<string | null>(null)
const logLoading = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

async function loadRun() {
  const before = run.value?.status
  run.value = await api.run(id, true)
  if (run.value.status === 'completed' && before !== 'completed') { await loadMetrics(); await loadSamples() }
}
async function loadMetrics() { metrics.value = await api.metrics(id) }
async function loadSamples() {
  const r = await api.samples(id, { page: samplePage.value, page_size: 10, correct: filter.value.correct || undefined, subset: filter.value.subset || undefined, q: filter.value.q || undefined })
  samples.value = r.items
  sampleTotal.value = r.total
}
onMounted(async () => {
  await loadRun()
  if (run.value?.status === 'completed') { await loadMetrics(); await loadSamples() }
  timer = setInterval(() => run.value && isActive(run.value) && loadRun(), 3000)
})
onBeforeUnmount(() => clearInterval(timer))
watch(filter, () => { samplePage.value = 1; loadSamples() }, { deep: true })
watch(samplePage, loadSamples)

const quality = computed(() => metrics.value.filter((m) => m.kind === 'quality' && m.subset === 'OVERALL'))
const diagnostics = computed(() => metrics.value.filter((m) => m.kind === 'diagnostic' && m.subset === 'OVERALL'))
const perf = computed(() => Object.fromEntries(metrics.value.filter((m) => m.kind === 'perf').map((m) => [m.key, m])))
const primary = computed(() => metrics.value.find((m) => m.primary && m.subset === 'OVERALL'))
const others = computed(() => quality.value.filter((m) => !m.primary))
const subsets = computed(() => [...new Set(metrics.value.filter((m) => m.subset !== 'OVERALL' && m.kind === 'quality').map((m) => m.subset))])
const subsetBars = computed(() => primary.value
  ? metrics.value.filter((m) => m.key === primary.value!.key && m.subset !== 'OVERALL' && m.value != null)
      .map((m) => ({ name: `${m.subset}（${m.num} 题）`, value: m.value! * m.display_multiplier, display: fmtMetric(m) }))
  : [])
const matrixCols = computed(() => [...new Map(metrics.value.filter((m) => m.kind === 'quality').map((m) => [m.key, m.label])).entries()])
const matrix = computed(() => subsets.value.concat(['OVERALL']).map((s) => ({
  subset: s === 'OVERALL' ? '合计' : s,
  ...Object.fromEntries(matrixCols.value.map(([k]) => {
    const m = metrics.value.find((x) => x.key === k && x.subset === s)
    return [k, m ? fmtMetric(m) : '—']
  })),
})))
const matrixColumns = computed(() => [{ title: '子集', dataIndex: 'subset', key: 'subset' }, ...matrixCols.value.map(([k, l]) => ({ title: l, dataIndex: k, key: k }))])
const wrongCount = computed(() => (primary.value && primary.value.num != null && primary.value.value != null ? Math.round(primary.value.num * (1 - primary.value.value)) : null))

async function act(fn: () => Promise<unknown>, msg: string) { await fn(); message.success(msg); await loadRun() }
const cancel = () => act(() => api.cancelRun(id), '已请求取消')
const retry = () => act(() => api.retryRun(id), '已重新排队')
async function rerun() { const r = await api.rerun(id); message.success('已创建新任务'); await router.push(`/runs/${r.id}`); location.reload() }
async function showLog() { logLoading.value = true; try { logText.value = (await api.log(id)) || '（还没有日志）' } finally { logLoading.value = false } }

const verdict = (s: Sample): ['good' | 'bad' | 'warn' | '', string] => (s.error ? ['warn', '出错'] : s.is_correct === true ? ['good', '答对'] : s.is_correct === false ? ['bad', '答错'] : ['', '未判定'])
const pretty = (o: unknown) => JSON.stringify(o, null, 1)
const imgs = (s: Sample) => s.media.map((m, k) => ({ m, k })).filter((x) => x.m.type === 'image' && x.m.kind !== 'missing')
const num = (m?: Metric) => (m ? fmtMetric(m) : '—')
</script>

<template>
  <div v-if="run" class="page">
    <a-button type="link" style="padding: 0; margin: 4px 0 8px" @click="router.push('/runs')"><template #icon><ArrowLeftOutlined /></template>评测任务</a-button>
    <div class="row-between" style="margin-bottom: 18px; align-items: flex-start">
      <div>
        <div class="row" style="gap: 12px"><h1 class="title">{{ run.model_name }} <span class="faint">×</span> {{ run.dataset_name }}</h1><StatusBadge :run="run" /></div>
        <div class="muted" style="margin-top: 4px; font-size: 13.5px">任务 #{{ run.id }} · {{ fmtTime(run.created_at) }} · 耗时 {{ fmtDuration(run.started_at, run.finished_at) }}</div>
      </div>
      <div class="row">
        <a-button v-if="isActive(run)" danger @click="cancel"><template #icon><StopOutlined /></template>取消</a-button>
        <a-button v-if="run.status === 'failed' || run.status === 'cancelled'" type="primary" @click="retry"><template #icon><RedoOutlined /></template>重试</a-button>
        <a-button v-if="!isActive(run)" @click="rerun"><template #icon><ReloadOutlined /></template>用相同配置重跑</a-button>
        <a-button v-if="run.status === 'completed'" tag="a" :href="`/api/v1/runs/${id}/export`"><template #icon><DownloadOutlined /></template>导出 CSV</a-button>
      </div>
    </div>

    <!-- state banners -->
    <a-alert v-if="run.error" type="error" show-icon message="任务失败" style="margin-bottom: 16px"><template #description><pre class="mono pre" style="margin: 0">{{ run.error }}</pre></template></a-alert>
    <div v-if="isActive(run)" class="card card-pad" style="margin-bottom: 16px; text-align: center; padding: 36px 20px">
      <a-spin />
      <div style="font-size: 16px; font-weight: 600; margin-top: 12px">{{ run.status === 'queued' ? '排队中，等待 Worker 取走' : '评测进行中' }}</div>
      <a-progress v-if="run.status === 'running' && run.stage === 'evaluating'" :percent="Math.round(run.progress * 100)" style="max-width: 420px; margin: 8px auto 0" />
      <div class="muted" style="font-size: 13px; margin-top: 4px">完成后这里会自动显示结果</div>
    </div>

    <!-- hero -->
    <div v-if="run.status === 'completed' && primary" class="hero" style="margin-bottom: 16px">
      <div class="row-between" style="align-items: flex-end; flex-wrap: wrap; gap: 20px">
        <div>
          <div class="muted">{{ primary.label }} · 主指标</div>
          <div class="hero-value">{{ fmtMetric(primary) }}</div>
          <div class="muted" style="font-size: 13px">{{ primary.key }} · {{ primary.num }} 题<span v-if="wrongCount"> · 约 {{ wrongCount }} 题答错</span></div>
        </div>
        <div class="row" style="gap: 12px; flex-wrap: wrap">
          <div v-for="k in ['latency_mean', 'input_tokens_mean', 'output_tokens_mean']" :key="k" class="hero-stat">
            <div class="muted" style="font-size: 12px">{{ perf[k]?.label }}</div><div style="font-size: 20px; font-weight: 650">{{ num(perf[k]) }}</div>
          </div>
        </div>
      </div>
    </div>

    <a-tabs v-if="run.status === 'completed'" v-model:activeKey="tab">
      <!-- overview -->
      <a-tab-pane key="overview" tab="总览">
        <a-alert v-if="run.limit" type="info" show-icon message="这是限制了题数的结果" description="样本较少，分数波动大，不能直接和公开榜单的成绩比较。" style="margin-bottom: 16px" />

        <div v-if="others.length" class="grid grid-4" style="margin-bottom: 16px">
          <MetricCard v-for="m in others" :key="m.key" :label="m.label" :value="fmtMetric(m)" :hint="`${m.key} · ${m.num} 题`" />
        </div>

        <div class="grid" :style="{ gridTemplateColumns: subsetBars.length > 1 ? '1fr 1fr' : '1fr' }" style="margin-bottom: 16px">
          <div v-if="subsetBars.length > 1" class="card card-pad">
            <h3 class="section-title">{{ primary?.label }}（按子集）</h3>
            <SubsetChart :items="subsetBars" :max="primary?.display_unit === '%' ? 100 : undefined" />
          </div>
          <div v-if="matrixCols.length" class="card card-pad">
            <h3 class="section-title">各子集明细</h3>
            <a-table :columns="matrixColumns" :data-source="matrix" :pagination="false" size="small" row-key="subset" />
          </div>
        </div>

        <h3 class="section-title" style="margin: 24px 0 10px">成本与性能</h3>
        <div class="grid" style="grid-template-columns: repeat(3, minmax(0, 1fr))">
          <MetricCard v-for="k in ['latency_mean', 'latency_p90', 'latency_max', 'input_tokens_mean', 'output_tokens_mean', 'output_tps']" :key="k" :label="perf[k]?.label ?? k" :value="num(perf[k])" />
        </div>
        <a-alert v-if="perf.input_tokens_mean && perf.input_tokens_mean.value! > 1500" type="warning" show-icon style="margin-top: 14px"
          :message="`平均每题输入 ${Math.round(perf.input_tokens_mean.value!)} token`" description="其中通常包含网关每次请求附加的固定内容（见“模型管理”里的连通测试提醒），估算费用时要把它算进去。" />
        <div v-if="diagnostics.length" class="faint" style="margin-top: 14px; font-size: 13px">其他计数：<span v-for="m in diagnostics" :key="m.key" class="mono" style="margin-right: 14px">{{ m.key }} = {{ fmtMetric(m) }}</span></div>
      </a-tab-pane>

      <!-- samples -->
      <a-tab-pane key="samples" :tab="`样本 ${sampleTotal}`">
        <div class="row" style="margin-bottom: 14px; flex-wrap: wrap; gap: 12px">
          <a-segmented v-model:value="filter.correct" :options="[{ value: '', label: '全部' }, { value: 'false', label: '答错' }, { value: 'error', label: '出错' }, { value: 'true', label: '答对' }]" />
          <a-select v-if="subsets.length > 1" v-model:value="filter.subset" allow-clear placeholder="全部子集" style="width: 160px" :options="subsets.map((s) => ({ value: s, label: s }))" />
          <a-input v-model:value="filter.q" allow-clear placeholder="搜索问题 / 答案 / 回答" style="width: 260px" />
        </div>
        <a-empty v-if="!samples.length" description="没有符合条件的样本" class="card card-pad" style="padding: 48px 0" />

        <div v-for="s in samples" :key="s.id" class="card verdict" :class="verdict(s)[0]" style="margin-bottom: 14px; overflow: hidden">
          <div class="row-between" style="padding: 12px 20px; border-bottom: 1px solid var(--c-border)">
            <div class="row"><a-tag :color="verdict(s)[0] === 'good' ? 'success' : verdict(s)[0] === 'bad' ? 'error' : verdict(s)[0] === 'warn' ? 'warning' : 'default'" style="margin: 0">{{ verdict(s)[1] }}</a-tag>
              <span class="muted">{{ subsets.length > 1 ? s.subset + ' · ' : '' }}#{{ s.idx }}</span></div>
            <div class="faint mono">{{ s.latency ? s.latency.toFixed(2) + ' s · ' : '' }}输入 {{ s.input_tokens ?? '-' }} / 输出 {{ s.output_tokens ?? '-' }} token</div>
          </div>
          <div class="sample-body">
            <div v-if="s.media.length" class="media">
              <a-image-preview-group>
                <template v-for="x in imgs(s)" :key="x.k"><a-image :src="mediaUrl(id, s, x.k)" :width="220" style="border-radius: 10px; margin-bottom: 8px; display: block" /></template>
              </a-image-preview-group>
              <div v-for="(m, k) in s.media.filter((m) => m.type !== 'image' || m.kind === 'missing')" :key="k" class="faint">[{{ m.type }}{{ m.kind === 'missing' ? ' 不可用' : '' }}]</div>
            </div>
            <div style="flex: 1; min-width: 0">
              <div class="label">问题</div>
              <div class="pre q">{{ s.question }}</div>
              <div class="cmp">
                <div v-if="s.target != null"><div class="label">标准答案</div><div class="answer-box good mono pre">{{ s.target }}</div></div>
                <div v-if="s.prediction || !s.tool_calls">
                  <div class="label">模型回答<span v-if="s.extracted && s.extracted !== s.prediction"> · 抽取：<b class="mono">{{ s.extracted }}</b></span></div>
                  <div class="answer-box pre" :class="verdict(s)[0] === 'bad' ? 'bad' : verdict(s)[0] === 'good' ? 'good' : ''">{{ s.prediction || '（空）' }}</div>
                </div>
                <div v-if="s.tool_calls"><div class="label">工具调用</div><pre class="code" :style="{ margin: 0 }">{{ s.tool_calls.map((t) => `${t.name}(${pretty(t.arguments)})`).join('\n') }}</pre></div>
                <div v-else-if="s.scores && 'should_call_tool' in s.scores"><div class="label">工具调用</div><div class="answer-box">模型没有调用工具</div></div>
              </div>
              <a-collapse v-if="s.judge_output" ghost style="margin-top: 8px"><a-collapse-panel key="j" header="裁判输出"><div class="pre" style="font-size: 13px">{{ s.judge_output }}</div></a-collapse-panel></a-collapse>
              <div class="faint mono" style="margin-top: 10px">{{ pretty(s.scores).replace(/\n/g, ' ') }}</div>
              <div v-if="s.error" style="color: var(--c-bad); margin-top: 6px">错误：{{ s.error }}</div>
            </div>
          </div>
        </div>
        <a-pagination v-if="sampleTotal > 10" v-model:current="samplePage" :page-size="10" :total="sampleTotal" :show-size-changer="false" style="margin-top: 16px; text-align: right" />
      </a-tab-pane>

      <!-- config -->
      <a-tab-pane key="config" tab="配置与日志">
        <a-descriptions bordered :column="2" size="middle">
          <a-descriptions-item label="被测模型">{{ run.model_name }}</a-descriptions-item>
          <a-descriptions-item label="评测集">{{ run.dataset_name }} v{{ run.dataset_version }}</a-descriptions-item>
          <a-descriptions-item label="裁判模型">{{ run.judge_model_name ?? '无' }}</a-descriptions-item>
          <a-descriptions-item label="题数">{{ run.limit ? `每个子集 ${run.limit} 题` : '全量' }}</a-descriptions-item>
          <a-descriptions-item label="引擎">{{ run.engine }} {{ run.engine_version }}</a-descriptions-item>
          <a-descriptions-item label="参数">并发 {{ run.config.batch_size }} · 最大输出 {{ run.config.max_tokens }} · 温度 {{ run.config.temperature }}</a-descriptions-item>
          <a-descriptions-item label="开始">{{ fmtTime(run.started_at) }}</a-descriptions-item>
          <a-descriptions-item label="结束">{{ fmtTime(run.finished_at) }}</a-descriptions-item>
        </a-descriptions>
        <div style="margin-top: 16px">
          <a-button :loading="logLoading" @click="showLog"><template #icon><FileTextOutlined /></template>查看引擎日志</a-button>
          <pre v-if="logText !== null" class="code" style="margin-top: 12px; max-height: 420px; overflow: auto">{{ logText }}</pre>
        </div>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<style scoped>
.title { margin: 0; font-size: 24px; font-weight: 650; letter-spacing: -0.01em; }
.hero-value { font-size: 64px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; margin: 4px 0; font-variant-numeric: tabular-nums; }
.hero-stat { background: rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 16px; min-width: 120px; backdrop-filter: blur(4px); }
.sample-body { display: flex; gap: 20px; padding: 16px 20px; }
.media { flex: none; width: 220px; }
.q { font-size: 14px; max-height: 140px; overflow: auto; margin-bottom: 12px; line-height: 1.6; }
.cmp { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
@media (max-width: 900px) { .sample-body { flex-direction: column; } .media { width: auto; } }
</style>
