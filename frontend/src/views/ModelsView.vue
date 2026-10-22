<script setup lang="ts">
import { CheckCircleFilled, CloseCircleFilled, DeleteOutlined, EditOutlined, ExclamationCircleFilled, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { onMounted, reactive, ref } from 'vue'
import { api, type CheckResult as CheckResultT, type ModelEndpoint } from '../api'
import EmptyState from '../components/ds/EmptyState.vue'
import CheckResult from '../components/CheckResult.vue'
import PageHeader from '../components/PageHeader.vue'

const models = ref<ModelEndpoint[]>([])
const loading = ref(true)
const drawer = ref(false)
const editing = ref<ModelEndpoint | null>(null)
const saving = ref(false)
const checking = ref<number | null>(null)
const checkView = ref<{ name: string; result: CheckResultT } | null>(null)

const blank = () => ({ name: '', protocol: 'openai' as 'openai' | 'anthropic', base_url: '', model_name: '', api_key: '', price_input_per_mtok: null as number | null, price_output_per_mtok: null as number | null, max_parallel_runs: null as number | null })
const form = reactive(blank())

async function load() {
  try { models.value = await api.models() } finally { loading.value = false }
}
onMounted(load)

function openCreate() { editing.value = null; Object.assign(form, blank()); drawer.value = true }
function openEdit(m: ModelEndpoint) {
  editing.value = m
  Object.assign(form, { name: m.name, protocol: m.protocol, base_url: m.base_url, model_name: m.model_name, api_key: '', price_input_per_mtok: m.price_input_per_mtok, price_output_per_mtok: m.price_output_per_mtok, max_parallel_runs: m.max_parallel_runs })
  drawer.value = true
}
async function save() {
  if (!form.name || !form.base_url || !form.model_name || (!editing.value && !form.api_key)) { message.warning('名称、地址、模型名和 key 都要填'); return }
  saving.value = true
  try {
    const body: Record<string, unknown> = { ...form }
    if (editing.value && !form.api_key) delete body.api_key // blank = keep the stored key
    const wasNew = !editing.value
    const saved = editing.value ? await api.updateModel(editing.value.id, body) : await api.createModel(body)
    drawer.value = false
    await load()
    if (wasNew) await runCheck(saved) // a new model is tested right away
  } finally { saving.value = false }
}
async function runCheck(m: ModelEndpoint) {
  checking.value = m.id
  try {
    checkView.value = { name: m.name, result: await api.checkModel(m.id) }
    await load()
  } finally { checking.value = null }
}
async function remove(m: ModelEndpoint) {
  await api.deleteModel(m.id)
  message.success('已删除')
  await load()
}
const price = (m: ModelEndpoint) => (m.price_input_per_mtok == null ? '未填写单价' : `$${m.price_input_per_mtok} / $${m.price_output_per_mtok ?? '-'} 每百万 token`)
</script>

<template>
  <div class="page">
    <PageHeader title="模型管理" sub="登记别人提供的模型 HTTP 接口。key 加密保存，之后不会再显示。">
      <a-button type="primary" size="large" @click="openCreate"><template #icon><PlusOutlined /></template>接入模型</a-button>
    </PageHeader>

    <a-spin :spinning="loading">
      <EmptyState v-if="!loading && !models.length" card title="还没有接入任何模型" hint="登记一个模型的 HTTP 接口，就可以拿它跑评测。">
        <a-button type="primary" @click="openCreate">接入第一个模型</a-button>
      </EmptyState>
      <div v-else class="grid grid-3">
        <div v-for="m in models" :key="m.id" class="card card-pad model">
          <div class="row-between">
            <div style="font-weight: 650; font-size: 16px">{{ m.name }}</div>
            <a-tag :class="m.protocol === 'openai' ? 'tag-teal' : 'tag-coral'" style="margin: 0">{{ m.protocol === 'openai' ? 'OpenAI' : 'Anthropic' }}</a-tag>
          </div>
          <div class="mono muted" style="margin: 6px 0 2px">{{ m.model_name }}</div>
          <div class="faint ellipsis" :title="m.base_url" style="font-size: 12.5px">{{ m.base_url }}</div>
          <div class="row faint" style="margin: 10px 0 14px; font-size: 12.5px; gap: 14px">
            <span><SafetyCertificateOutlined /> <span class="mono">{{ m.api_key_hint }}</span></span><span>{{ price(m) }}</span>
          </div>

          <div class="status" :class="m.last_check ? (m.last_check.ok ? 'good' : 'bad') : ''" @click="m.last_check && (checkView = { name: m.name, result: m.last_check })">
            <template v-if="m.last_check">
              <CheckCircleFilled v-if="m.last_check.ok" /><CloseCircleFilled v-else />
              <span style="flex: 1">{{ m.last_check.ok ? '连通测试通过' : '连通测试有问题' }}</span>
              <span v-if="m.last_check.warnings.length" class="warn"><ExclamationCircleFilled /> {{ m.last_check.warnings.length }}</span>
            </template>
            <span v-else class="faint">还没有测试过</span>
          </div>

          <div class="row" style="margin-top: 14px">
            <a-button :loading="checking === m.id" type="primary" ghost @click="runCheck(m)">{{ m.last_check ? '重新测试' : '连通测试' }}</a-button>
            <a-button @click="openEdit(m)"><template #icon><EditOutlined /></template>编辑</a-button>
            <a-popconfirm title="确定删除这个模型？" ok-text="删除" cancel-text="取消" :ok-button-props="{ danger: true }" @confirm="remove(m)">
              <a-button danger type="text"><template #icon><DeleteOutlined /></template></a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
    </a-spin>

    <a-drawer v-model:open="drawer" :title="editing ? '编辑模型' : '接入模型'" :width="460" destroy-on-close>
      <a-form layout="vertical" :model="form">
        <a-form-item label="名称" name="name"><a-input v-model:value="form.name" placeholder="例如：Haiku（Anthropic 格式）" /></a-form-item>
        <a-form-item label="协议" name="protocol">
          <a-segmented v-model:value="form.protocol" block :options="[{ value: 'openai', label: 'OpenAI 兼容' }, { value: 'anthropic', label: 'Anthropic 兼容' }]" />
        </a-form-item>
        <a-form-item label="接口地址" name="base_url" extra="填服务商给的地址，不用带 /v1。"><a-input v-model:value="form.base_url" placeholder="https://api.example.com" /></a-form-item>
        <a-form-item label="模型名" name="model_name" extra="接口里 model 参数的值。"><a-input v-model:value="form.model_name" /></a-form-item>
        <a-form-item label="API Key" name="api_key" :extra="editing ? '不修改就留空。' : '加密保存，之后只显示后四位。'"><a-input-password v-model:value="form.api_key" autocomplete="off" /></a-form-item>
        <a-form-item label="单价（可选）" extra="每百万 token，只用来做费用预估。">
          <div class="row"><a-input-number v-model:value="form.price_input_per_mtok" :min="0" placeholder="输入" style="flex: 1" /><a-input-number v-model:value="form.price_output_per_mtok" :min="0" placeholder="输出" style="flex: 1" /></div>
        </a-form-item>
        <a-form-item label="同时评测的任务数" extra="这个模型最多同时跑几个评测任务，默认 1。每个任务自己还会并发发送请求（发起评测时的“并发”），调大前先确认服务商的限流。">
          <a-input-number v-model:value="form.max_parallel_runs" :min="1" :max="20" placeholder="1" style="width: 120px" />
        </a-form-item>
      </a-form>
      <template #footer>
        <div class="row" style="justify-content: flex-end"><a-button @click="drawer = false">取消</a-button><a-button type="primary" :loading="saving" @click="save">{{ editing ? '保存' : '接入并测试' }}</a-button></div>
      </template>
    </a-drawer>

    <a-modal :open="!!checkView" :title="`连通测试 · ${checkView?.name}`" :footer="null" :width="560" @cancel="checkView = null">
      <CheckResult v-if="checkView" :result="checkView.result" />
    </a-modal>
  </div>
</template>

<style scoped>
.model { transition: box-shadow 0.15s, transform 0.15s; }
.model:hover { transform: translateY(-2px); box-shadow: var(--shadow-card); }
.status { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: var(--radius-md); background: var(--surface-2); font-size: 13.5px; cursor: pointer; }
.status.good { background: var(--teal-soft); color: var(--teal); }
.status.bad { background: var(--danger-soft); color: var(--danger); }
.warn { color: var(--amber); }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
