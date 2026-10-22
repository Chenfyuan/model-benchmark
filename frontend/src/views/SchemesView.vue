<script setup lang="ts">
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { api, type Scheme } from '../api'
import EmptyState from '../components/ds/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'

type Row = { dataset_name: string | undefined; weight: number | null }
const schemes = ref<Scheme[]>([])
const datasetNames = ref<string[]>([])
const loading = ref(true)
const drawer = ref(false)
const editing = ref<Scheme | null>(null)
const saving = ref(false)
const form = reactive<{ name: string; rows: Row[] }>({ name: '', rows: [] })

async function load() {
  loading.value = true
  try {
    ;[schemes.value, datasetNames.value] = await Promise.all([api.schemes(), api.datasets().then((d) => [...new Set(d.map((x) => x.name))])])
  } finally { loading.value = false }
}
onMounted(load)

function open(s?: Scheme) {
  editing.value = s ?? null
  form.name = s?.name ?? ''
  form.rows = s ? s.items.map((i) => ({ dataset_name: i.dataset_name, weight: i.weight })) : [{ dataset_name: undefined, weight: 1 }, { dataset_name: undefined, weight: 1 }]
  drawer.value = true
}
const total = computed(() => form.rows.reduce((a, r) => a + (r.weight && r.weight > 0 ? r.weight : 0), 0))
const share = (r: Row) => (total.value && r.weight && r.weight > 0 ? `${((r.weight / total.value) * 100).toFixed(1)}%` : '—')
const options = (current: string | undefined) => datasetNames.value.filter((n) => n === current || !form.rows.some((r) => r.dataset_name === n)).map((n) => ({ value: n, label: n }))
const addRow = () => form.rows.push({ dataset_name: undefined, weight: 1 })
const removeRow = (i: number) => form.rows.splice(i, 1)
const equalize = () => form.rows.forEach((r) => (r.weight = 1))

async function save() {
  const items = form.rows.filter((r) => r.dataset_name)
  if (!form.name.trim()) return void message.warning('给方案起个名字')
  if (!items.length) return void message.warning('至少选一个评测集')
  if (items.some((r) => !r.weight || r.weight <= 0)) return void message.warning('每个评测集的权重都要大于 0')
  saving.value = true
  try {
    await api.saveScheme({ name: form.name.trim(), items: items.map((r) => ({ dataset_name: r.dataset_name!, weight: r.weight! })) }, editing.value?.id)
    drawer.value = false
    message.success('已保存')
    await load()
  } finally { saving.value = false }
}
async function remove(s: Scheme) { await api.deleteScheme(s.id); message.success('已删除'); await load() }
</script>

<template>
  <div class="page narrow" style="--col: 856px">
    <PageHeader title="评分方案" sub="把一个模型在多个评测集上的得分，按你们看重的程度合成一个综合得分。在“模型对比”里选方案就能看到。">
      <a-button type="primary" size="large" @click="open()"><template #icon><PlusOutlined /></template>新建方案</a-button>
    </PageHeader>

    <a-alert type="info" show-icon style="margin-bottom: 16px" message="综合得分怎么算"
      description="综合得分 = 各评测集得分 × 权重占比，再相加。权重只看相对大小（2 和 1 等于 67% 和 33%）。得分用各评测集的主指标，有复核时用复核后的得分。模型缺少方案里任何一个评测集的结果，就不给综合得分。" />

    <a-spin :spinning="loading">
      <EmptyState v-if="!loading && !schemes.length" card title="还没有评分方案" hint="按你看重的程度，给各个评测集设置权重，合成一个综合得分。">
        <a-button type="primary" @click="open()">新建第一个方案</a-button>
      </EmptyState>
      <div v-for="s in schemes" :key="s.id" class="card card-pad scheme" style="margin-bottom: 14px">
        <div class="row-between">
          <h3 class="section-title" style="margin: 0">{{ s.name }}</h3>
          <div class="row">
            <a-button size="small" @click="open(s)"><template #icon><EditOutlined /></template>编辑</a-button>
            <a-popconfirm title="删除这个方案？已有的评测结果不受影响。" ok-text="删除" cancel-text="取消" @confirm="remove(s)"><a-button size="small" danger><template #icon><DeleteOutlined /></template>删除</a-button></a-popconfirm>
          </div>
        </div>
        <div style="margin-top: 12px">
          <div v-for="i in s.items" :key="i.dataset_name" class="bar">
            <span class="nm">{{ i.dataset_name }}</span>
            <div class="track"><div class="fill" :style="{ width: i.weight_pct + '%' }" /></div>
            <b class="pc">{{ i.weight_pct.toFixed(1) }}%</b>
          </div>
        </div>
      </div>
    </a-spin>

    <a-drawer v-model:open="drawer" :title="editing ? '编辑评分方案' : '新建评分方案'" :width="520" destroy-on-close>
      <a-form layout="vertical">
        <a-form-item label="方案名称"><a-input v-model:value="form.name" placeholder="例如：文档场景" /></a-form-item>
        <a-form-item label="评测集和权重" extra="权重是相对大小，右边会实时换算成占比。">
          <div v-for="(r, i) in form.rows" :key="i" class="wrow">
            <a-select v-model:value="r.dataset_name" :options="options(r.dataset_name)" placeholder="选择评测集" show-search style="flex: 1" />
            <a-input-number v-model:value="r.weight" :min="0" :max="1000" style="width: 90px" />
            <span class="share">{{ share(r) }}</span>
            <a-button type="text" danger :disabled="form.rows.length <= 1" @click="removeRow(i)"><template #icon><DeleteOutlined /></template></a-button>
          </div>
          <div class="row" style="margin-top: 6px"><a-button size="small" @click="addRow"><template #icon><PlusOutlined /></template>添加评测集</a-button><a-button size="small" @click="equalize">各项相同</a-button></div>
        </a-form-item>
      </a-form>
      <template #footer><div class="row" style="justify-content: flex-end"><a-button @click="drawer = false">取消</a-button><a-button type="primary" :loading="saving" @click="save">保存</a-button></div></template>
    </a-drawer>
  </div>
</template>

<style scoped>
.bar { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
.nm { width: 180px; flex: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { flex: 1; height: 10px; border-radius: var(--radius-pill); background: var(--surface-2); overflow: hidden; }
.fill { height: 100%; border-radius: var(--radius-pill); background: var(--signal); }
.pc { font-family: var(--font-display); width: 56px; text-align: right; font-variant-numeric: tabular-nums; }
.wrow { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.share { font-family: var(--font-display); width: 56px; text-align: right; color: var(--ink-muted); font-variant-numeric: tabular-nums; }
</style>
