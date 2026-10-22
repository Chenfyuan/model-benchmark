<script setup lang="ts">
import { BarChartOutlined, DeleteOutlined, PlusOutlined, RedoOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Run } from '../api'
import PageHeader from '../components/PageHeader.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { STOP_REASON_LABEL, fmtAgo, fmtCost, fmtDuration, fmtTokens, isActive } from '../format'

const router = useRouter()
const runs = ref<Run[]>([])
const total = ref(0)
const page = ref(1)
const filter = ref<'all' | 'running' | 'completed' | 'failed'>('all')
const loading = ref(true)
const selected = ref<number[]>([])
const counts = ref({ all: 0, running: 0, completed: 0, failed: 0 })
let timer: ReturnType<typeof setInterval> | undefined

async function loadCounts() {
  const [all, running, completed, failed] = await Promise.all(
    [undefined, 'running', 'completed', 'failed'].map((status) => api.runs({ page_size: 1, status }, true).then((r) => r.total)),
  )
  counts.value = { all, running, completed, failed }
}
async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await api.runs({ page: page.value, page_size: 12, status: filter.value === 'all' ? undefined : filter.value }, silent)
    runs.value = r.items
    total.value = r.total
    await loadCounts()
  } finally { loading.value = false }
}
const anyActive = computed(() => runs.value.some(isActive))
onMounted(() => { load(); timer = setInterval(() => anyActive.value && load(true), 3000) })
onBeforeUnmount(() => clearInterval(timer))
watch(page, () => load())
watch(filter, () => { page.value = 1; load() })

async function act(fn: () => Promise<unknown>, msg: string) {
  await fn()
  message.success(msg)
  await load(true)
}
const cancel = (r: Run) => act(() => api.cancelRun(r.id), '已请求取消')
const retry = (r: Run) => act(() => api.retryRun(r.id), '已重新排队')
const rerun = (r: Run) => act(() => api.rerun(r.id), '已按相同配置创建新任务')
const remove = (r: Run) => act(() => api.deleteRun(r.id), '已删除')

const filters = computed(() => [
  { value: 'all', label: `全部 ${counts.value.all}` },
  { value: 'running', label: `运行中 ${counts.value.running}` },
  { value: 'completed', label: `已完成 ${counts.value.completed}` },
  { value: 'failed', label: `失败 ${counts.value.failed}` },
])
const columns = [
  { title: '任务', key: 'task' },
  { title: '状态', key: 'status', width: 220 },
  { title: '主指标', key: 'headline', width: 160 },
  { title: '用量', key: 'usage', width: 130 },
  { title: '时间', key: 'time', width: 150 },
  { title: '', key: 'actions', width: 150, align: 'right' as const },
]
const customRow = (r: Run) => ({
  onClick: (e: MouseEvent) => { if (!(e.target as HTMLElement).closest('.ant-table-selection-column')) router.push(`/runs/${r.id}`) },
  style: 'cursor: pointer',
})
const canCompare = computed(() => selected.value.length >= 2 && selected.value.length <= 8)
const compare = () => router.push({ path: '/compare', query: { runs: selected.value.join(',') } })
</script>

<template>
  <div class="page">
    <PageHeader title="评测任务" sub="所有评测任务的进度和结果。点击一行查看详情。">
      <a-button type="primary" size="large" @click="$router.push('/runs/new')"><template #icon><PlusOutlined /></template>发起评测</a-button>
    </PageHeader>

    <div class="grid grid-4" style="margin-bottom: 16px">
      <div class="card card-pad stat"><div class="muted">全部任务</div><div class="n">{{ counts.all }}</div></div>
      <div class="card card-pad stat"><div class="muted">运行中</div><div class="n" style="color: var(--c-primary)">{{ counts.running }}</div></div>
      <div class="card card-pad stat"><div class="muted">已完成</div><div class="n" style="color: var(--c-good)">{{ counts.completed }}</div></div>
      <div class="card card-pad stat"><div class="muted">失败</div><div class="n" :style="{ color: counts.failed ? 'var(--c-bad)' : undefined }">{{ counts.failed }}</div></div>
    </div>

    <div class="card" style="overflow: hidden">
      <div class="row-between" style="padding: 14px 20px">
        <a-segmented v-model:value="filter" :options="filters" />
        <div class="row">
          <a-tooltip :title="selected.length < 2 ? '在左边勾选 2–8 个任务' : selected.length > 8 ? '一次最多对比 8 个' : ''">
            <a-button :type="canCompare ? 'primary' : 'default'" :disabled="!canCompare" @click="compare"><template #icon><BarChartOutlined /></template>对比所选{{ selected.length ? ` (${selected.length})` : '' }}</a-button>
          </a-tooltip>
          <a-button type="text" @click="load()"><template #icon><ReloadOutlined /></template>刷新</a-button>
        </div>
      </div>
      <a-table :columns="columns" :data-source="runs" :loading="loading" row-key="id" :custom-row="customRow"
        :row-selection="{ selectedRowKeys: selected, onChange: (k: (string | number)[]) => (selected = k as number[]) }"
        :pagination="total > 12 ? { current: page, pageSize: 12, total, showSizeChanger: false, onChange: (p: number) => (page = p) } : false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'task'">
            <div style="font-weight: 600">{{ record.model_name }}</div>
            <div class="muted" style="font-size: 13px">{{ record.dataset_name }} <span class="faint">v{{ record.dataset_version }}</span><span v-if="record.judge_model_name" class="faint"> · 裁判 {{ record.judge_model_name }}</span></div>
          </template>
          <template v-else-if="column.key === 'status'">
            <StatusBadge :run="record as Run" show-progress />
            <a-tag v-if="record.stop_reason" color="orange" style="margin-top: 4px">{{ STOP_REASON_LABEL[record.stop_reason] }}</a-tag>
          </template>
          <template v-else-if="column.key === 'usage'">
            <template v-if="record.input_tokens != null">
              <div>{{ fmtTokens((record.input_tokens ?? 0) + (record.output_tokens ?? 0)) }} token</div>
              <div class="faint" style="font-size: 12px">{{ record.cost != null ? `费用 ${fmtCost(record.cost)}` : '未填单价' }}<span v-if="record.attempts > 1"> · 重试 {{ record.attempts - 1 }} 次</span></div>
            </template>
            <span v-else class="faint">—</span>
          </template>
          <template v-else-if="column.key === 'headline'">
            <template v-if="record.headline">
              <span class="hl">{{ record.headline.display }}</span> <span class="faint" style="font-size: 12px; margin-left: 6px">{{ record.headline.label }}</span>
              <a-tooltip v-if="record.adjusted" :title="`宽松匹配 ${record.adjusted.n_lenient} 题、人工改判 ${record.adjusted.n_manual} 题后的得分；引擎原始得分是 ${record.headline.display}`"><a-tag color="processing" style="margin: 0 0 0 6px">复核后 {{ record.adjusted.display }}</a-tag></a-tooltip>
            </template>
            <span v-else class="faint">—</span>
          </template>
          <template v-else-if="column.key === 'time'">
            <div>{{ fmtAgo(record.created_at) }}</div>
            <div class="faint" style="font-size: 12px">耗时 {{ fmtDuration(record.started_at, record.finished_at) }}</div>
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="row" style="justify-content: flex-end" @click.stop>
              <a-tooltip v-if="isActive(record as Run)" title="取消"><a-button type="text" size="small" @click="cancel(record as Run)"><template #icon><StopOutlined /></template></a-button></a-tooltip>
              <a-tooltip v-if="record.status === 'failed' || record.status === 'cancelled'" title="重试"><a-button type="text" size="small" @click="retry(record as Run)"><template #icon><RedoOutlined /></template></a-button></a-tooltip>
              <a-tooltip v-if="!isActive(record as Run)" title="用相同配置重跑"><a-button type="text" size="small" @click="rerun(record as Run)"><template #icon><ReloadOutlined /></template></a-button></a-tooltip>
              <a-popconfirm v-if="record.status !== 'running'" title="删除这个任务和它的全部结果？" ok-text="删除" cancel-text="取消" :ok-button-props="{ danger: true }" @confirm="remove(record as Run)">
                <a-button type="text" size="small" danger><template #icon><DeleteOutlined /></template></a-button>
              </a-popconfirm>
            </div>
          </template>
        </template>
        <template #emptyText>
          <a-empty description="还没有评测任务">
            <a-button type="primary" @click="$router.push('/runs/new')">发起第一次评测</a-button>
          </a-empty>
        </template>
      </a-table>
    </div>
  </div>
</template>

<style scoped>
.stat { padding: 16px 20px; }
.n { font-size: 30px; font-weight: 650; letter-spacing: -0.02em; margin-top: 2px; font-variant-numeric: tabular-nums; }
.hl { font-size: 18px; font-weight: 650; font-variant-numeric: tabular-nums; }
</style>
