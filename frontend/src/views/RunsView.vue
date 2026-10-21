<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type Run } from '../api'
import { STAGE_LABEL, STATUS_LABEL, STATUS_TYPE, fmtDuration, fmtTime, isActive } from '../format'

const runs = ref<Run[]>([])
const total = ref(0)
const page = ref(1)
const status = ref('')
const loading = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await api.runs({ page: page.value, page_size: 15, status: status.value || undefined }, silent)
    runs.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}
const anyActive = computed(() => runs.value.some(isActive))
onMounted(() => { load(); timer = setInterval(() => anyActive.value && load(true), 3000) })
onBeforeUnmount(() => clearInterval(timer))
watch([page, status], () => load())

async function act(fn: () => Promise<unknown>, msg: string) {
  await fn()
  ElMessage.success(msg)
  await load(true)
}
const cancel = (r: Run) => act(() => api.cancelRun(r.id), '已请求取消')
const retry = (r: Run) => act(() => api.retryRun(r.id), '已重新排队')
const rerun = (r: Run) => act(() => api.rerun(r.id), '已按相同配置创建新任务')
async function remove(r: Run) {
  await ElMessageBox.confirm(`确定删除任务 #${r.id} 及其全部结果？`, '删除任务', { type: 'warning' })
  await act(() => api.deleteRun(r.id), '已删除')
}
const stage = (r: Run) => (r.status === 'running' ? STAGE_LABEL[r.stage] || '' : '')
</script>

<template>
  <div class="page-head">
    <h2>评测任务</h2>
    <div>
      <el-select v-model="status" clearable placeholder="全部状态" style="width: 140px; margin-right: 8px" @change="page = 1">
        <el-option v-for="(l, k) in STATUS_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-button type="primary" @click="$router.push('/runs/new')">发起评测</el-button>
    </div>
  </div>

  <el-table :data="runs" v-loading="loading" stripe empty-text="还没有评测任务" @row-click="(r: Run) => $router.push(`/runs/${r.id}`)" style="cursor: pointer">
    <el-table-column prop="id" label="#" width="60" />
    <el-table-column prop="model_name" label="模型" min-width="150" />
    <el-table-column label="评测集" min-width="170"><template #default="{ row }">{{ row.dataset_name }}<span class="muted"> v{{ row.dataset_version }}</span></template></el-table-column>
    <el-table-column label="状态" width="210">
      <template #default="{ row }">
        <el-tag :type="STATUS_TYPE[row.status as Run['status']]" size="small">{{ STATUS_LABEL[row.status as Run['status']] }}</el-tag>
        <span v-if="stage(row)" class="muted" style="margin-left: 6px">{{ stage(row) }}</span>
        <el-progress v-if="row.status === 'running' && row.stage === 'evaluating'" :percentage="Math.round(row.progress * 100)" :stroke-width="6" style="margin-top: 4px" />
      </template>
    </el-table-column>
    <el-table-column label="主指标" width="170">
      <template #default="{ row }"><template v-if="row.headline"><b>{{ row.headline.display }}</b> <span class="muted">{{ row.headline.label }}</span></template><span v-else class="muted">-</span></template>
    </el-table-column>
    <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ fmtTime(row.created_at) }}</template></el-table-column>
    <el-table-column label="耗时" width="110"><template #default="{ row }">{{ fmtDuration(row.started_at, row.finished_at) }}</template></el-table-column>
    <el-table-column label="操作" width="200" fixed="right">
      <template #default="{ row }">
        <el-button v-if="isActive(row)" link type="warning" @click.stop="cancel(row)">取消</el-button>
        <el-button v-if="row.status === 'failed' || row.status === 'cancelled'" link type="primary" @click.stop="retry(row)">重试</el-button>
        <el-button v-if="!isActive(row)" link @click.stop="rerun(row)">重跑</el-button>
        <el-button v-if="row.status !== 'running'" link type="danger" @click.stop="remove(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-pagination v-if="total > 15" v-model:current-page="page" :page-size="15" :total="total" layout="prev, pager, next, total" style="margin-top: 16px" />
</template>
