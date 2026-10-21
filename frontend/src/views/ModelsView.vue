<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { api, type CheckResult as CheckResultT, type ModelEndpoint } from '../api'
import CheckResult from '../components/CheckResult.vue'

const models = ref<ModelEndpoint[]>([])
const loading = ref(false)
const dialog = ref(false)
const editing = ref<ModelEndpoint | null>(null)
const saving = ref(false)
const checking = ref<number | null>(null)
const checkDialog = ref<{ name: string; result: CheckResultT } | null>(null)

const blank = () => ({ name: '', protocol: 'openai', base_url: '', model_name: '', api_key: '', price_input_per_mtok: null as number | null, price_output_per_mtok: null as number | null })
const form = reactive(blank())

async function load() {
  loading.value = true
  try { models.value = await api.models() } finally { loading.value = false }
}
onMounted(load)

function openCreate() {
  editing.value = null
  Object.assign(form, blank())
  dialog.value = true
}
function openEdit(m: ModelEndpoint) {
  editing.value = m
  Object.assign(form, { name: m.name, protocol: m.protocol, base_url: m.base_url, model_name: m.model_name, api_key: '', price_input_per_mtok: m.price_input_per_mtok, price_output_per_mtok: m.price_output_per_mtok })
  dialog.value = true
}
async function save() {
  if (!form.name || !form.base_url || !form.model_name || (!editing.value && !form.api_key)) {
    ElMessage.warning('名称、地址、模型名和 key 都要填')
    return
  }
  saving.value = true
  try {
    const body: Record<string, unknown> = { ...form }
    if (editing.value && !form.api_key) delete body.api_key // blank = keep the stored key
    const saved = editing.value ? await api.updateModel(editing.value.id, body) : await api.createModel(body)
    dialog.value = false
    await load()
    if (!editing.value) await runCheck(saved) // a new model is tested right away
  } finally { saving.value = false }
}
async function runCheck(m: ModelEndpoint) {
  checking.value = m.id
  try {
    checkDialog.value = { name: m.name, result: await api.checkModel(m.id) }
    await load()
  } finally { checking.value = null }
}
async function remove(m: ModelEndpoint) {
  await ElMessageBox.confirm(`确定删除模型“${m.name}”？`, '删除模型', { type: 'warning' })
  await api.deleteModel(m.id)
  ElMessage.success('已删除')
  await load()
}
const price = (m: ModelEndpoint) => m.price_input_per_mtok == null ? '未填写' : `${m.price_input_per_mtok} / ${m.price_output_per_mtok ?? '-'}`
</script>

<template>
  <div class="page-head">
    <h2>模型管理</h2>
    <el-button type="primary" @click="openCreate">接入模型</el-button>
  </div>
  <p class="muted">这里登记别人提供的模型 HTTP 接口。key 加密保存，页面和接口都不会再显示它。接入后会立刻做连通测试。</p>

  <el-table :data="models" v-loading="loading" stripe empty-text="还没有接入任何模型">
    <el-table-column prop="name" label="名称" min-width="140" />
    <el-table-column label="协议" width="110">
      <template #default="{ row }"><el-tag size="small" :type="row.protocol === 'openai' ? 'success' : 'warning'">{{ row.protocol === 'openai' ? 'OpenAI' : 'Anthropic' }}</el-tag></template>
    </el-table-column>
    <el-table-column prop="model_name" label="模型名" min-width="150" />
    <el-table-column prop="base_url" label="接口地址" min-width="240" show-overflow-tooltip />
    <el-table-column prop="api_key_hint" label="Key" width="100"><template #default="{ row }"><span class="mono">{{ row.api_key_hint }}</span></template></el-table-column>
    <el-table-column label="单价（输入/输出，每百万 token）" width="200"><template #default="{ row }">{{ price(row) }}</template></el-table-column>
    <el-table-column label="连通测试" width="170">
      <template #default="{ row }">
        <template v-if="row.last_check">
          <el-tag :type="row.last_check.ok ? 'success' : 'danger'" size="small">{{ row.last_check.ok ? '可用' : '有问题' }}</el-tag>
          <el-tag v-if="row.last_check.warnings.length" type="warning" size="small" style="margin-left: 4px">{{ row.last_check.warnings.length }} 条提醒</el-tag>
        </template>
        <span v-else class="muted">未测试</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="230" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" :loading="checking === row.id" @click="runCheck(row)">连通测试</el-button>
        <el-button v-if="row.last_check" link @click="checkDialog = { name: row.name, result: row.last_check }">结果</el-button>
        <el-button link @click="openEdit(row)">编辑</el-button>
        <el-button link type="danger" @click="remove(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>

  <el-dialog v-model="dialog" :title="editing ? '编辑模型' : '接入模型'" width="560px">
    <el-form label-width="110px">
      <el-form-item label="名称"><el-input v-model="form.name" placeholder="例如：Haiku（Anthropic 格式）" /></el-form-item>
      <el-form-item label="协议">
        <el-radio-group v-model="form.protocol">
          <el-radio-button value="openai">OpenAI 兼容</el-radio-button>
          <el-radio-button value="anthropic">Anthropic 兼容</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="接口地址"><el-input v-model="form.base_url" placeholder="https://api.example.com" /><div class="muted">填服务商给的地址，不用带 /v1。</div></el-form-item>
      <el-form-item label="模型名"><el-input v-model="form.model_name" placeholder="接口里的 model 参数" /></el-form-item>
      <el-form-item label="API Key"><el-input v-model="form.api_key" type="password" show-password :placeholder="editing ? '不修改就留空' : '加密保存'" autocomplete="off" /></el-form-item>
      <el-form-item label="输入单价"><el-input-number v-model="form.price_input_per_mtok" :min="0" :controls="false" placeholder="可选" /><span class="muted" style="margin-left: 8px">每百万 token，用于费用预估</span></el-form-item>
      <el-form-item label="输出单价"><el-input-number v-model="form.price_output_per_mtok" :min="0" :controls="false" placeholder="可选" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">{{ editing ? '保存' : '接入并测试' }}</el-button>
    </template>
  </el-dialog>

  <el-dialog :model-value="!!checkDialog" :title="`连通测试：${checkDialog?.name}`" width="640px" @close="checkDialog = null">
    <CheckResult v-if="checkDialog" :result="checkDialog.result" />
  </el-dialog>
</template>
