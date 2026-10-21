<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Dataset, type Estimate, type ModelEndpoint } from '../api'
import { CAPABILITY_LABEL } from '../format'

const router = useRouter()
const models = ref<ModelEndpoint[]>([])
const datasets = ref<Dataset[]>([])
const modelIds = ref<number[]>([])
const datasetIds = ref<number[]>([])
const judgeId = ref<number | null>(null)
const mode = ref<'trial' | 'custom' | 'full'>('trial')
const customLimit = ref(50)
const batchSize = ref(2)
const maxTokens = ref(1024)
const temperature = ref(0)
const submitting = ref(false)
const estimates = ref<{ model: ModelEndpoint; dataset: Dataset; est: Estimate }[]>([])

const limit = computed<number | null>(() => (mode.value === 'trial' ? 20 : mode.value === 'custom' ? customLimit.value : null))
const judgeCandidates = computed(() => models.value.filter((m) => m.protocol === 'openai'))
const groups = computed(() => {
  const g: Record<string, Dataset[]> = {}
  for (const d of datasets.value) (g[d.capability ? CAPABILITY_LABEL[d.capability] : '未分类'] ??= []).push(d)
  return g
})
const pairs = computed(() => modelIds.value.length * datasetIds.value.length)
const picked = computed(() => datasets.value.filter((d) => datasetIds.value.includes(d.id)))
const needsJudge = computed(() => picked.value.some((d) => d.kind === 'vqa') && !judgeId.value)
const unchecked = computed(() => models.value.filter((m) => modelIds.value.includes(m.id) && !m.last_check?.ok))
const fullOnBuiltin = computed(() => mode.value === 'full' && picked.value.some((d) => d.source === 'builtin'))

onMounted(async () => {
  ;[models.value, datasets.value] = await Promise.all([api.models(), api.datasets()])
})

watch([modelIds, datasetIds, limit], async () => {
  const sel = modelIds.value.flatMap((mid) => datasetIds.value.map((did) => [mid, did] as const)).slice(0, 12)
  const out = await Promise.all(sel.map(async ([mid, did]) => ({
    model: models.value.find((m) => m.id === mid)!, dataset: datasets.value.find((d) => d.id === did)!,
    est: await api.estimate({ model_id: mid, dataset_id: did, limit: limit.value }),
  })))
  estimates.value = out
})

const money = (c: number | null) => (c == null ? '-' : `${c.toFixed(c < 0.1 ? 4 : 2)}`)

async function submit() {
  submitting.value = true
  try {
    const runs = await api.createRuns({
      model_ids: modelIds.value, dataset_ids: datasetIds.value, judge_model_id: judgeId.value, limit: limit.value,
      batch_size: batchSize.value, max_tokens: maxTokens.value, temperature: temperature.value,
    }, crypto.randomUUID())
    ElMessage.success(`已创建 ${runs.length} 个评测任务`)
    router.push('/runs')
  } finally { submitting.value = false }
}
</script>

<template>
  <div class="page-head"><h2>发起评测</h2></div>
  <el-form label-width="110px" style="max-width: 860px">
    <el-form-item label="被测模型">
      <el-select v-model="modelIds" multiple placeholder="可多选，一次对比多个模型" style="width: 100%">
        <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id">
          <span>{{ m.name }}</span>
          <el-tag v-if="!m.last_check" size="small" type="info" style="margin-left: 8px">未测试</el-tag>
          <el-tag v-else-if="!m.last_check.ok" size="small" type="danger" style="margin-left: 8px">连通测试有问题</el-tag>
        </el-option>
      </el-select>
      <el-alert v-if="unchecked.length" type="warning" :closable="false" show-icon style="margin-top: 8px"
        :title="`${unchecked.map((m) => m.name).join('、')} 还没有通过连通测试。如果模型实际没有看到图片，分数会照常产生但没有意义，建议先去“模型管理”测试。`" />
    </el-form-item>

    <el-form-item label="评测集">
      <el-select v-model="datasetIds" multiple placeholder="可多选" style="width: 100%">
        <el-option-group v-for="(list, g) in groups" :key="g" :label="g">
          <el-option v-for="d in list" :key="d.id" :label="d.source === 'custom' ? `${d.name} v${d.version}` : d.name" :value="d.id">
            <span>{{ d.source === 'custom' ? `${d.name} v${d.version}` : d.name }}</span>
            <el-tag v-if="d.source === 'custom'" size="small" style="margin-left: 8px">自有 · {{ d.num_samples }} 条</el-tag>
            <el-tag v-else-if="d.verified" size="small" type="success" style="margin-left: 8px">已跑通</el-tag>
            <el-tag v-else size="small" type="info" style="margin-left: 8px">未验证</el-tag>
          </el-option>
        </el-option-group>
      </el-select>
    </el-form-item>

    <el-form-item label="裁判模型">
      <el-select v-model="judgeId" clearable placeholder="可选；开放问答类评测集建议选" style="width: 100%">
        <el-option v-for="m in judgeCandidates" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <div class="muted">只能选 OpenAI 格式的模型。裁判不要求多模态，评测数据会发送给它的服务商。</div>
      <el-alert v-if="needsJudge" type="info" :closable="false" show-icon style="margin-top: 8px"
        title="所选评测集里有视觉问答（开放问答）类型。不配裁判模型时，只能算 BLEU/ROUGE，没有准确率。" />
    </el-form-item>

    <el-form-item label="题数">
      <el-radio-group v-model="mode">
        <el-radio-button value="trial">试跑（每个子集 20 题）</el-radio-button>
        <el-radio-button value="custom">自定义</el-radio-button>
        <el-radio-button value="full">全量</el-radio-button>
      </el-radio-group>
      <el-input-number v-if="mode === 'custom'" v-model="customLimit" :min="1" style="margin-left: 12px" />
      <div class="muted">建议先试跑，确认配置和接口没问题，再跑全量。限制按“每个子集”计算。</div>
      <el-alert v-if="fullOnBuiltin" type="warning" :closable="false" show-icon style="margin-top: 8px"
        title="公开基准的全量可能有几千到上万题，耗时长、费用高；首次运行还要下载数据集。" />
    </el-form-item>

    <el-collapse style="margin-bottom: 16px">
      <el-collapse-item title="高级设置（所有被测模型使用同一套，保证可比）">
        <el-form-item label="并发数"><el-input-number v-model="batchSize" :min="1" :max="64" /><span class="muted" style="margin-left: 8px">对方接口有限流时调小</span></el-form-item>
        <el-form-item label="最大输出"><el-input-number v-model="maxTokens" :min="1" :step="256" /></el-form-item>
        <el-form-item label="温度"><el-input-number v-model="temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
      </el-collapse-item>
    </el-collapse>

    <el-card v-if="estimates.length" shadow="never" style="margin-bottom: 16px">
      <template #header><b>费用和用量预估</b><span class="muted" style="margin-left: 8px">仅供参考，实际以运行中统计的 token 为准</span></template>
      <el-table :data="estimates" size="small">
        <el-table-column label="模型" prop="model.name" />
        <el-table-column label="评测集"><template #default="{ row }">{{ row.dataset.name }}</template></el-table-column>
        <el-table-column label="题数" width="90"><template #default="{ row }">{{ row.est.num_samples ?? '运行时才知道' }}</template></el-table-column>
        <el-table-column label="预计 token" width="120"><template #default="{ row }">{{ row.est.total_tokens?.toLocaleString() ?? '-' }}</template></el-table-column>
        <el-table-column label="预计费用" width="110"><template #default="{ row }">{{ money(row.est.cost) }}</template></el-table-column>
      </el-table>
      <div v-for="n in [...new Set(estimates.flatMap((e) => e.est.notes))]" :key="n" class="muted" style="margin-top: 4px">· {{ n }}</div>
    </el-card>

    <el-button type="primary" size="large" :disabled="!pairs" :loading="submitting" @click="submit">
      {{ pairs ? `创建 ${pairs} 个评测任务` : '请先选择模型和评测集' }}
    </el-button>
  </el-form>
</template>
