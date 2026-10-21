<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { api, type Dataset } from '../api'
import { CAPABILITY_LABEL, KIND_LABEL, fmtTime } from '../format'

const datasets = ref<Dataset[]>([])
const loading = ref(false)
const tab = ref('builtin')
const dialog = ref(false)
const uploading = ref(false)
const errors = ref<string[]>([])
const file = ref<File | null>(null)
const form = ref({ name: '', kind: 'vqa', capability: '', description: '' })
const previewing = ref<{ name: string; rows: unknown[] } | null>(null)

const builtin = computed(() => datasets.value.filter((d) => d.source === 'builtin'))
const custom = computed(() => datasets.value.filter((d) => d.source === 'custom'))

const EXAMPLES: Record<string, { title: string; hint: string; example: string }> = {
  vqa: {
    title: '视觉问答（开放问答、OCR、图表问答）',
    hint: '每行一条，messages 是 OpenAI 消息格式，图片放在 image_url 里；answer 是标准答案。配上裁判模型才能算准确率，否则只算 BLEU/ROUGE。',
    example: '{"messages":[{"role":"user","content":[{"type":"text","text":"图里写了什么？"},{"type":"image_url","image_url":{"url":"img/1.png"}}]}],"answer":"ORBIT-208"}',
  },
  vmcq: {
    title: '选择题（选项可以是文字或图片）',
    hint: 'question 里用 <image 1> 引用图片，对应 image_1 列；answer 是正确选项的字母。',
    example: '{"question":"<image 1> 背景是什么颜色？","options":["黄色","蓝色","绿色"],"image_1":"img/1.png","answer":"B"}',
  },
  fc: {
    title: '工具调用',
    hint: 'tools 是 OpenAI 格式的工具定义；should_call_tool 标明这条输入该不该调用工具。只评“该不该调、工具名和参数格式对不对”，不检查参数的值。',
    example: '{"messages":[{"role":"user","content":"巴黎天气怎么样？"}],"tools":[{"type":"function","function":{"name":"get_weather","description":"查询天气","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],"should_call_tool":true}',
  },
}

async function load() {
  loading.value = true
  try { datasets.value = await api.datasets() } finally { loading.value = false }
}
onMounted(load)

function openUpload() {
  form.value = { name: '', kind: 'vqa', capability: '', description: '' }
  file.value = null
  errors.value = []
  dialog.value = true
}
function pick(e: Event) { file.value = (e.target as HTMLInputElement).files?.[0] ?? null }
async function upload() {
  if (!form.value.name || !file.value) { ElMessage.warning('请填写名称并选择文件'); return }
  const fd = new FormData()
  fd.append('name', form.value.name)
  fd.append('kind', form.value.kind)
  fd.append('description', form.value.description)
  if (form.value.capability) fd.append('capability', form.value.capability)
  fd.append('file', file.value)
  uploading.value = true
  errors.value = []
  try {
    const ds = await api.uploadDataset(fd)
    ElMessage.success(`已上传：${ds.name} v${ds.version}，${ds.num_samples} 条`)
    dialog.value = false
    await load()
  } catch (e: any) {
    errors.value = e.response?.data?.details ?? []
  } finally { uploading.value = false }
}
async function preview(d: Dataset) { previewing.value = { name: `${d.name} v${d.version}`, rows: await api.previewDataset(d.id) } }
async function remove(d: Dataset) {
  await ElMessageBox.confirm(`确定删除“${d.name} v${d.version}”？`, '删除评测集', { type: 'warning' })
  await api.deleteDataset(d.id)
  await load()
}
</script>

<template>
  <div class="page-head">
    <h2>评测集</h2>
    <el-button v-if="tab === 'custom'" type="primary" @click="openUpload">上传评测集</el-button>
  </div>

  <el-tabs v-model="tab">
    <el-tab-pane label="内置基准" name="builtin">
      <p class="muted">公开基准的数据在第一次评测时自动下载并缓存。“已跑通”表示这个基准已经在本平台上实际跑过，其余来自 EvalScope 的官方列表，还没有在这里验证。</p>
      <el-table :data="builtin" v-loading="loading" stripe>
        <el-table-column label="能力" width="110"><template #default="{ row }"><el-tag size="small">{{ CAPABILITY_LABEL[row.capability] ?? row.capability }}</el-tag></template></el-table-column>
        <el-table-column prop="name" label="基准" width="200" />
        <el-table-column prop="benchmark_id" label="ID" width="180"><template #default="{ row }"><span class="mono">{{ row.benchmark_id }}</span></template></el-table-column>
        <el-table-column prop="description" label="说明" />
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.verified ? 'success' : 'info'" size="small">{{ row.verified ? '已跑通' : '未验证' }}</el-tag></template></el-table-column>
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="自有数据集" name="custom">
      <el-table :data="custom" v-loading="loading" stripe empty-text="还没有上传过自有评测集">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="版本" width="80"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
        <el-table-column label="类型" width="150"><template #default="{ row }">{{ KIND_LABEL[row.kind] ?? row.kind }}</template></el-table-column>
        <el-table-column label="能力" width="110"><template #default="{ row }">{{ CAPABILITY_LABEL[row.capability] ?? '-' }}</template></el-table-column>
        <el-table-column prop="num_samples" label="样本数" width="90" />
        <el-table-column label="上传时间" width="180"><template #default="{ row }">{{ fmtTime(row.created_at) }}</template></el-table-column>
        <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="preview(row)">预览</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
  </el-tabs>

  <el-dialog v-model="dialog" title="上传评测集" width="700px">
    <el-form label-width="90px">
      <el-form-item label="名称"><el-input v-model="form.name" placeholder="同名再上传会生成新版本" /></el-form-item>
      <el-form-item label="类型">
        <el-radio-group v-model="form.kind">
          <el-radio-button v-for="(_, k) in EXAMPLES" :key="k" :value="k">{{ KIND_LABEL[k] }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="格式说明">
        <div>
          <b>{{ EXAMPLES[form.kind].title }}</b>
          <div class="muted">{{ EXAMPLES[form.kind].hint }}</div>
          <pre class="mono example">{{ EXAMPLES[form.kind].example }}</pre>
        </div>
      </el-form-item>
      <el-form-item label="能力">
        <el-select v-model="form.capability" clearable placeholder="可选"><el-option v-for="(l, k) in CAPABILITY_LABEL" :key="k" :label="l" :value="k" /></el-select>
      </el-form-item>
      <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
      <el-form-item label="文件">
        <input type="file" accept=".jsonl,.zip" @change="pick" />
        <div class="muted">.jsonl；带本地图片/视频时打包成 .zip（里面一个 .jsonl，媒体用相对路径引用）。</div>
      </el-form-item>
    </el-form>
    <el-alert v-if="errors.length" type="error" :closable="false" title="数据集校验未通过">
      <div v-for="e in errors" :key="e">{{ e }}</div>
    </el-alert>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="uploading" @click="upload">上传并校验</el-button>
    </template>
  </el-dialog>

  <el-dialog :model-value="!!previewing" :title="`预览：${previewing?.name}（前 5 条）`" width="760px" @close="previewing = null">
    <pre v-for="(r, i) in previewing?.rows" :key="i" class="mono example">{{ JSON.stringify(r, null, 1) }}</pre>
  </el-dialog>
</template>

<style scoped>
.example { background: #f5f7fa; padding: 8px 10px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; margin: 6px 0; max-height: 260px; overflow: auto; }
</style>
