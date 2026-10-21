<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, mediaUrl, type Metric, type Run, type Sample } from '../api'
import SubsetChart from '../components/SubsetChart.vue'
import { STAGE_LABEL, STATUS_LABEL, STATUS_TYPE, fmtDuration, fmtMetric, fmtTime, isActive } from '../format'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)
const run = ref<Run | null>(null)
const metrics = ref<Metric[]>([])
const tab = ref('overview')
const samples = ref<Sample[]>([])
const sampleTotal = ref(0)
const samplePage = ref(1)
const filter = ref({ correct: '', subset: '', q: '' })
const logText = ref<string | null>(null)
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
const subsets = computed(() => [...new Set(metrics.value.filter((m) => m.subset !== 'OVERALL' && m.kind === 'quality').map((m) => m.subset))])
const subsetBars = computed(() => primary.value
  ? metrics.value.filter((m) => m.key === primary.value!.key && m.subset !== 'OVERALL' && m.value != null)
      .map((m) => ({ name: `${m.subset}（${m.num} 题）`, value: m.value! * m.display_multiplier, display: fmtMetric(m) }))
  : [])
const matrix = computed(() => {
  const keys = [...new Set(metrics.value.filter((m) => m.kind === 'quality').map((m) => m.key))]
  return subsets.value.concat(['OVERALL']).map((s) => ({
    subset: s, ...Object.fromEntries(keys.map((k) => {
      const m = metrics.value.find((x) => x.key === k && x.subset === s)
      return [k, m ? fmtMetric(m) : '-']
    })),
  }))
})
const matrixCols = computed(() => [...new Map(metrics.value.filter((m) => m.kind === 'quality').map((m) => [m.key, m.label])).entries()])

async function act(fn: () => Promise<unknown>, msg: string) { await fn(); ElMessage.success(msg); await loadRun() }
const cancel = () => act(() => api.cancelRun(id), '已请求取消')
const retry = () => act(() => api.retryRun(id), '已重新排队')
async function showLog() { logText.value = (await api.log(id)) || '（还没有日志）' }
async function rerun() { const r = await api.rerun(id); ElMessage.success('已创建新任务'); router.push(`/runs/${r.id}`).then(() => location.reload()) }
const verdict = (s: Sample) => (s.error ? ['出错', 'warning'] : s.is_correct === true ? ['答对', 'success'] : s.is_correct === false ? ['答错', 'danger'] : ['-', 'info'])
const pretty = (o: unknown) => JSON.stringify(o, null, 1)
</script>

<template>
  <template v-if="run">
    <div class="page-head">
      <h2>
        <el-link underline="never" @click="router.push('/runs')">评测任务</el-link> / #{{ run.id }}
        <el-tag :type="STATUS_TYPE[run.status]" style="margin-left: 8px">{{ STATUS_LABEL[run.status] }}</el-tag>
        <span v-if="run.status === 'running'" class="muted" style="margin-left: 8px">{{ STAGE_LABEL[run.stage] }}</span>
      </h2>
      <div>
        <el-button v-if="isActive(run)" type="warning" @click="cancel">取消</el-button>
        <el-button v-if="run.status === 'failed' || run.status === 'cancelled'" type="primary" @click="retry">重试</el-button>
        <el-button v-if="!isActive(run)" @click="rerun">用相同配置重跑</el-button>
        <el-button v-if="run.status === 'completed'" tag="a" :href="`/api/v1/runs/${id}/export`">导出 CSV</el-button>
        <el-button @click="showLog">引擎日志</el-button>
      </div>
    </div>

    <el-progress v-if="run.status === 'running' && run.stage === 'evaluating'" :percentage="Math.round(run.progress * 100)" style="margin-bottom: 12px" />
    <el-alert v-if="run.error" type="error" :closable="false" title="失败原因" style="margin-bottom: 12px"><pre class="mono" style="white-space: pre-wrap; margin: 0">{{ run.error }}</pre></el-alert>

    <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
      <el-descriptions-item label="被测模型">{{ run.model_name }}</el-descriptions-item>
      <el-descriptions-item label="评测集">{{ run.dataset_name }} v{{ run.dataset_version }}</el-descriptions-item>
      <el-descriptions-item label="裁判模型">{{ run.judge_model_name ?? '无' }}</el-descriptions-item>
      <el-descriptions-item label="题数限制">{{ run.limit ? `每个子集 ${run.limit} 题` : '全量' }}</el-descriptions-item>
      <el-descriptions-item label="引擎">{{ run.engine }} {{ run.engine_version }}</el-descriptions-item>
      <el-descriptions-item label="耗时">{{ fmtDuration(run.started_at, run.finished_at) }}</el-descriptions-item>
      <el-descriptions-item label="创建时间">{{ fmtTime(run.created_at) }}</el-descriptions-item>
      <el-descriptions-item label="参数" :span="2">并发 {{ run.config.batch_size }} · 最大输出 {{ run.config.max_tokens }} · 温度 {{ run.config.temperature }}</el-descriptions-item>
    </el-descriptions>

    <el-tabs v-if="run.status === 'completed'" v-model="tab">
      <el-tab-pane label="总览" name="overview">
        <el-row :gutter="16" style="margin-bottom: 16px">
          <el-col v-for="m in quality" :key="m.key" :xs="12" :md="6">
            <el-card shadow="never"><div class="muted">{{ m.label }}<span v-if="m.primary"> · 主指标</span></div><div class="big">{{ fmtMetric(m) }}</div><div class="muted mono">{{ m.key }} · {{ m.num }} 题</div></el-card>
          </el-col>
        </el-row>
        <el-alert v-if="run.limit" type="info" :closable="false" show-icon style="margin-bottom: 16px" title="这是限制了题数的结果，样本较少，分数波动大，不能直接和公开榜单的成绩比较。" />

        <el-row :gutter="24">
          <el-col :md="12" v-if="subsetBars.length > 1"><SubsetChart :title="`${primary?.label}（按子集）`" :items="subsetBars" :max="primary?.display_unit === '%' ? 100 : undefined" /></el-col>
          <el-col :md="12" v-if="matrixCols.length">
            <div class="muted" style="margin-bottom: 4px">各子集明细</div>
            <el-table :data="matrix" size="small" border>
              <el-table-column prop="subset" label="子集" />
              <el-table-column v-for="[k, label] in matrixCols" :key="k" :prop="k" :label="label" />
            </el-table>
          </el-col>
        </el-row>

        <h4>成本与性能</h4>
        <el-row :gutter="16">
          <el-col v-for="k in ['latency_mean', 'latency_p90', 'input_tokens_mean', 'output_tokens_mean', 'output_tps']" :key="k" :xs="12" :md="4">
            <el-card v-if="perf[k]" shadow="never"><div class="muted">{{ perf[k].label }}</div><div class="big">{{ fmtMetric(perf[k]) }}</div></el-card>
          </el-col>
        </el-row>
        <p v-if="perf.input_tokens_mean && perf.input_tokens_mean.value! > 1500" class="muted">
          平均每题输入 {{ Math.round(perf.input_tokens_mean.value!) }} token，其中通常包含网关每次请求附加的固定内容（见“模型管理”里的连通测试提醒），费用估算时要把它算进去。
        </p>
        <div v-if="diagnostics.length" class="muted">其他计数：<span v-for="m in diagnostics" :key="m.key" class="mono" style="margin-right: 12px">{{ m.key }} = {{ fmtMetric(m) }}</span></div>
      </el-tab-pane>

      <el-tab-pane :label="`样本（${sampleTotal}）`" name="samples">
        <div style="margin-bottom: 12px; display: flex; gap: 12px; flex-wrap: wrap">
          <el-radio-group v-model="filter.correct">
            <el-radio-button value="">全部</el-radio-button><el-radio-button value="false">答错</el-radio-button>
            <el-radio-button value="error">出错</el-radio-button><el-radio-button value="true">答对</el-radio-button>
          </el-radio-group>
          <el-select v-if="subsets.length > 1" v-model="filter.subset" clearable placeholder="全部子集" style="width: 160px"><el-option v-for="s in subsets" :key="s" :label="s" :value="s" /></el-select>
          <el-input v-model="filter.q" clearable placeholder="搜索问题 / 答案 / 回答" style="width: 260px" />
        </div>
        <el-empty v-if="!samples.length" description="没有符合条件的样本" />
        <el-card v-for="s in samples" :key="s.id" shadow="never" style="margin-bottom: 12px">
          <template #header>
            <el-tag :type="verdict(s)[1] as any" size="small">{{ verdict(s)[0] }}</el-tag>
            <span class="muted" style="margin-left: 8px">{{ subsets.length > 1 ? s.subset + ' ' : '' }}#{{ s.idx }}</span>
            <span class="muted" style="margin-left: 12px">{{ s.latency ? s.latency.toFixed(2) + ' s' : '' }} · 输入 {{ s.input_tokens ?? '-' }} / 输出 {{ s.output_tokens ?? '-' }} token</span>
          </template>
          <div style="display: flex; gap: 16px">
            <div v-if="s.media.length" style="flex: none">
              <template v-for="(m, k) in s.media" :key="k">
                <el-image v-if="m.type === 'image' && m.kind !== 'missing'" :src="mediaUrl(id, s, k)" :preview-src-list="[mediaUrl(id, s, k)]" fit="contain" style="width: 200px; max-height: 200px; display: block; margin-bottom: 6px" preview-teleported />
                <div v-else class="muted">[{{ m.type }}{{ m.kind === 'missing' ? ' 不可用' : '' }}]</div>
              </template>
            </div>
            <div style="flex: 1; min-width: 0">
              <div class="muted">问题</div>
              <div class="text">{{ s.question }}</div>
              <el-descriptions :column="1" size="small" border style="margin-top: 8px">
                <el-descriptions-item v-if="s.target != null" label="标准答案"><span class="mono">{{ s.target }}</span></el-descriptions-item>
                <el-descriptions-item v-if="s.extracted && s.extracted !== s.prediction" label="抽取的答案"><span class="mono">{{ s.extracted }}</span></el-descriptions-item>
                <el-descriptions-item v-if="s.prediction || !s.tool_calls" label="模型回答"><div class="text">{{ s.prediction || '（空）' }}</div></el-descriptions-item>
                <el-descriptions-item v-if="s.tool_calls" label="工具调用"><pre class="mono" style="margin: 0">{{ s.tool_calls.map((t) => `${t.name}(${pretty(t.arguments)})`).join('\n') }}</pre></el-descriptions-item>
                <el-descriptions-item v-else-if="run.dataset_name && s.scores && 'should_call_tool' in s.scores && s.scores.should_call_tool === 0" label="工具调用">模型没有调用工具</el-descriptions-item>
                <el-descriptions-item v-if="s.judge_output" label="裁判输出"><div class="text">{{ s.judge_output }}</div></el-descriptions-item>
                <el-descriptions-item label="得分"><span class="mono">{{ pretty(s.scores) }}</span></el-descriptions-item>
                <el-descriptions-item v-if="s.error" label="错误">{{ s.error }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </div>
        </el-card>
        <el-pagination v-if="sampleTotal > 10" v-model:current-page="samplePage" :page-size="10" :total="sampleTotal" layout="prev, pager, next, total" />
      </el-tab-pane>
    </el-tabs>
    <el-empty v-else-if="isActive(run)" description="评测还在进行，完成后这里会显示结果" />
  </template>

  <el-dialog :model-value="logText !== null" title="引擎日志（最后 200 行）" width="900px" @close="logText = null">
    <pre class="mono" style="white-space: pre-wrap; max-height: 60vh; overflow: auto">{{ logText }}</pre>
  </el-dialog>
</template>

<style scoped>
.big { font-size: 26px; font-weight: 600; margin: 4px 0; }
.text { white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; }
h4 { margin: 24px 0 12px; }
</style>
