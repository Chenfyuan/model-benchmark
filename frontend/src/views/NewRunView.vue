<script setup lang="ts">
import { CheckOutlined, ExclamationCircleFilled, ThunderboltOutlined } from '@ant-design/icons-vue'
import { Modal, message } from 'ant-design-vue'
import { h } from 'vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Dataset, type Estimate, type ModelEndpoint } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { CAPABILITY_HINT, CAPABILITY_LABEL, KIND_LABEL } from '../format'

const router = useRouter()
const models = ref<ModelEndpoint[]>([])
const datasets = ref<Dataset[]>([])
const loaded = ref(false)
const modelIds = ref<number[]>([])
const datasetIds = ref<number[]>([])
const judgeId = ref<number | undefined>()
const mode = ref<'trial' | 'custom' | 'full'>('trial')
const customLimit = ref(50)
const batchSize = ref(2)
const maxTokens = ref(1024)
const temperature = ref(0)
const submitting = ref(false)
const estimates = ref<{ model: ModelEndpoint; dataset: Dataset; est: Estimate }[]>([])

const limit = computed<number | null>(() => (mode.value === 'trial' ? 20 : mode.value === 'custom' ? customLimit.value : null))
const judgeOptions = computed(() => models.value.filter((m) => m.protocol === 'openai').map((m) => ({ value: m.id, label: m.name })))
const groups = computed(() => {
  const order = ['doc_chart', 'general_qa', 'tool_call', '']
  const g = new Map<string, Dataset[]>()
  for (const k of order) g.set(k, [])
  for (const d of datasets.value) g.get(d.capability ?? '')!.push(d)
  return [...g.entries()].filter(([, l]) => l.length)
})
const pairs = computed(() => modelIds.value.length * datasetIds.value.length)
const picked = computed(() => datasets.value.filter((d) => datasetIds.value.includes(d.id)))
const mustJudge = computed(() => picked.value.filter((d) => d.needs_judge).map((d) => d.name))
const needsJudge = computed(() => picked.value.some((d) => d.kind === 'vqa') && !judgeId.value)
const unchecked = computed(() => models.value.filter((m) => modelIds.value.includes(m.id) && !m.last_check?.ok))
const fullOnBuiltin = computed(() => mode.value === 'full' && picked.value.some((d) => d.source === 'builtin'))
const totalTokens = computed(() => estimates.value.reduce((a, e) => a + (e.est.total_tokens ?? 0), 0))
const unknownCount = computed(() => estimates.value.some((e) => e.est.num_samples == null))

onMounted(async () => {
  ;[models.value, datasets.value] = await Promise.all([api.models(), api.datasets()])
  loaded.value = true
})

const flip = (list: number[], id: number) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
const toggleModel = (id: number) => { modelIds.value = flip(modelIds.value, id) }
const toggleDataset = (id: number) => { datasetIds.value = flip(datasetIds.value, id) }

watch([modelIds, datasetIds, limit], async () => {
  const sel = modelIds.value.flatMap((mid) => datasetIds.value.map((did) => [mid, did] as const)).slice(0, 12)
  estimates.value = await Promise.all(sel.map(async ([mid, did]) => ({
    model: models.value.find((m) => m.id === mid)!, dataset: datasets.value.find((d) => d.id === did)!,
    est: await api.estimate({ model_id: mid, dataset_id: did, limit: limit.value }),
  })))
})

const money = (c: number) => c.toFixed(c < 0.1 ? 4 : 2)
const askToConfirm = (details: string[]) => new Promise<boolean>((resolve) => {
  Modal.confirm({
    title: '预计会超出费用上限',
    content: h('div', [h('ul', { style: 'padding-left: 18px; margin: 8px 0' }, details.map((d) => h('li', d))), h('div', { style: 'color: #888' }, '仍然提交的话，运行中如果实际用量超限，任务还是会被自动停止。')]),
    okText: '仍然提交', cancelText: '取消', onOk: () => resolve(true), onCancel: () => resolve(false),
  })
})
async function submit() {
  submitting.value = true
  try {
    const body = {
      model_ids: modelIds.value, dataset_ids: datasetIds.value, judge_model_id: judgeId.value ?? null, limit: limit.value,
      batch_size: batchSize.value, max_tokens: maxTokens.value, temperature: temperature.value,
    }
    const key = crypto.randomUUID()
    let runs
    try {
      runs = await api.createRuns(body, key, true)
    } catch (e: any) {
      const d = e.response?.data
      if (d?.code !== 'budget_exceeded') { message.error(d?.message ?? '创建失败'); return }
      if (!(await askToConfirm(d.details ?? []))) return
      runs = await api.createRuns({ ...body, confirm_over_budget: true }, key)
    }
    message.success(`已创建 ${runs.length} 个评测任务`)
    // several models on one dataset: the natural next step is to compare them
    if (datasetIds.value.length === 1 && modelIds.value.length > 1) router.push({ path: '/compare', query: { runs: runs.map((r) => r.id).join(',') } })
    else router.push('/runs')
  } finally { submitting.value = false }
}
const modelState = (m: ModelEndpoint) => (!m.last_check ? ['未测试', 'default'] : m.last_check.ok ? ['可用', 'success'] : ['有问题', 'error'])
const datasetTag = (d: Dataset) => (d.needs_judge ? ['需裁判模型', 'warning'] : d.source === 'custom' ? [`自有 · ${d.num_samples} 条`, 'purple'] : d.verified ? ['已跑通', 'success'] : ['未验证', 'default'])
</script>

<template>
  <div class="page">
    <PageHeader title="发起评测" sub="选好模型和评测集，先试跑几题确认没问题，再跑全量。" />

    <div class="layout">
      <div class="main">
        <!-- 1. models -->
        <div class="card card-pad block">
          <h3 class="section-title"><span class="step">1</span>被测模型</h3>
          <p class="section-sub">可以多选，一次对比多个模型。</p>
          <a-empty v-if="loaded && !models.length" description="还没有接入任何模型">
            <a-button type="primary" @click="router.push('/models')">去接入模型</a-button>
          </a-empty>
          <div v-else class="grid grid-3">
            <div v-for="m in models" :key="m.id" class="pick" :class="{ on: modelIds.includes(m.id) }" @click="toggleModel(m.id)">
              <span class="check"><CheckOutlined v-if="modelIds.includes(m.id)" /></span>
              <div style="font-weight: 600; padding-right: 28px">{{ m.name }}</div>
              <div class="muted mono" style="margin: 2px 0 8px">{{ m.model_name }}</div>
              <a-tag :color="m.protocol === 'openai' ? 'green' : 'orange'">{{ m.protocol === 'openai' ? 'OpenAI' : 'Anthropic' }}</a-tag>
              <a-badge :status="modelState(m)[1] as any" :text="modelState(m)[0]" />
            </div>
          </div>
          <a-alert v-if="unchecked.length" type="warning" show-icon style="margin-top: 14px"
            :message="`${unchecked.map((m) => m.name).join('、')} 还没有通过连通测试`"
            description="如果模型实际没有看到图片，分数会照常产生但没有意义。建议先去“模型管理”测试。" />
        </div>

        <!-- 2. datasets -->
        <div class="card card-pad block">
          <h3 class="section-title"><span class="step">2</span>评测集</h3>
          <p class="section-sub">按能力分组；“已跑通”表示这个基准已经在本平台上实际跑过。</p>
          <div v-for="[cap, list] in groups" :key="cap" style="margin-bottom: 18px">
            <div class="row" style="margin-bottom: 8px">
              <b>{{ CAPABILITY_LABEL[cap] ?? '未分类' }}</b><span class="faint" style="font-size: 13px">{{ CAPABILITY_HINT[cap] ?? '' }}</span>
            </div>
            <div class="grid grid-3">
              <div v-for="d in list" :key="d.id" class="pick" :class="{ on: datasetIds.includes(d.id) }" @click="toggleDataset(d.id)">
                <span class="check"><CheckOutlined v-if="datasetIds.includes(d.id)" /></span>
                <div style="font-weight: 600; padding-right: 28px">{{ d.name }}<span v-if="d.source === 'custom'" class="faint"> v{{ d.version }}</span></div>
                <div class="muted" style="font-size: 13px; margin: 2px 0 8px; min-height: 20px">{{ d.description || KIND_LABEL[d.kind] }}</div>
                <a-tag :color="datasetTag(d)[1]">{{ datasetTag(d)[0] }}</a-tag>
                <a-tag v-if="d.source === 'custom'">{{ KIND_LABEL[d.kind] }}</a-tag>
              </div>
            </div>
          </div>
        </div>

        <!-- 3. settings -->
        <div class="card card-pad block">
          <h3 class="section-title"><span class="step">3</span>评测设置</h3>
          <p class="section-sub">所有被测模型使用同一套设置，保证结果可比。</p>
          <div class="field">
            <div class="label">题数（按每个子集计算）</div>
            <a-segmented v-model:value="mode" :options="[{ value: 'trial', label: '试跑 · 20 题' }, { value: 'custom', label: '自定义' }, { value: 'full', label: '全量' }]" />
            <a-input-number v-if="mode === 'custom'" v-model:value="customLimit" :min="1" style="margin-left: 12px" />
            <a-alert v-if="fullOnBuiltin" type="warning" show-icon style="margin-top: 10px" message="公开基准的全量可能有几千到上万题，耗时长、费用高；首次运行还要下载数据集。" />
          </div>
          <div class="field">
            <div class="label">裁判模型（可选，只能选 OpenAI 格式）</div>
            <a-select v-model:value="judgeId" :options="judgeOptions" allow-clear placeholder="不使用裁判模型" style="width: 100%; max-width: 420px" />
            <a-alert v-if="mustJudge.length && !judgeId" type="error" show-icon style="margin-top: 10px" :message="`${mustJudge.join('、')} 的得分完全由裁判模型给出，必须选一个裁判模型。`" />
            <a-alert v-else-if="needsJudge" type="info" show-icon style="margin-top: 10px" message="所选评测集里有视觉问答（开放问答）。不配裁判模型时只能算 BLEU / ROUGE，没有准确率。" />
          </div>
          <a-collapse ghost>
            <a-collapse-panel key="adv" header="高级设置">
              <div class="row" style="gap: 24px; flex-wrap: wrap">
                <div><div class="label">并发数</div><a-input-number v-model:value="batchSize" :min="1" :max="64" /></div>
                <div><div class="label">最大输出 token</div><a-input-number v-model:value="maxTokens" :min="1" :step="256" /></div>
                <div><div class="label">温度</div><a-input-number v-model:value="temperature" :min="0" :max="2" :step="0.1" /></div>
              </div>
            </a-collapse-panel>
          </a-collapse>
        </div>
      </div>

      <!-- summary -->
      <aside class="summary">
        <div class="card card-pad">
          <h3 class="section-title">本次评测</h3>
          <div class="big">{{ pairs }}<span class="muted" style="font-size: 14px; font-weight: 400"> 个任务</span></div>
          <div class="muted" style="font-size: 13px">{{ modelIds.length }} 个模型 × {{ datasetIds.length }} 个评测集</div>
          <a-divider style="margin: 14px 0" />
          <template v-if="estimates.length">
            <div v-for="e in estimates" :key="`${e.model.id}-${e.dataset.id}`" class="est">
              <div style="min-width: 0"><div class="ellipsis">{{ e.model.name }}</div><div class="faint ellipsis" style="font-size: 12px">{{ e.dataset.name }}</div></div>
              <div style="text-align: right; white-space: nowrap">
                <div>{{ e.est.num_samples ?? '?' }} 题</div>
                <div class="faint" style="font-size: 12px">{{ e.est.cost != null ? `约 ${money(e.est.cost)}` : e.est.total_tokens ? `${(e.est.total_tokens / 1000).toFixed(0)}k token` : '—' }}</div>
              </div>
            </div>
            <div v-if="totalTokens" class="muted" style="font-size: 13px; margin-top: 8px">合计约 {{ (totalTokens / 1000).toFixed(0) }}k token<span v-if="unknownCount">（不含题数未知的基准）</span></div>
            <div v-for="n in [...new Set(estimates.flatMap((e) => e.est.notes))]" :key="n" class="faint" style="font-size: 12px; margin-top: 6px"><ExclamationCircleFilled /> {{ n }}</div>
          </template>
          <div v-else class="faint" style="font-size: 13px">选择模型和评测集后，这里显示用量预估。</div>
          <a-button type="primary" size="large" block :disabled="!pairs || (mustJudge.length > 0 && !judgeId)" :loading="submitting" style="margin-top: 18px" @click="submit">
            <template #icon><ThunderboltOutlined /></template>{{ pairs ? `开始评测（${pairs}）` : '请先选择' }}
          </a-button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.block { margin-bottom: 16px; }
.step { display: inline-flex; width: 22px; height: 22px; border-radius: 50%; background: var(--c-primary-soft); color: var(--c-primary); align-items: center; justify-content: center; font-size: 13px; margin-right: 10px; }
.field { margin-bottom: 18px; }
.summary { position: sticky; top: 16px; }
.big { font-size: 34px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.2; }
.est { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; font-size: 13.5px; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } .summary { position: static; } }
</style>
