<script setup lang="ts">
import { CheckCircleFilled, DeleteOutlined, EyeOutlined, InboxOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onMounted, ref } from 'vue'
import { api, type Dataset } from '../api'
import CopyCode from '../components/CopyCode.vue'
import PageHeader from '../components/PageHeader.vue'
import { CAPABILITY_HINT, CAPABILITY_LABEL, KIND_LABEL, fmtAgo } from '../format'

const datasets = ref<Dataset[]>([])
const loading = ref(true)
const tab = ref<'builtin' | 'custom'>('builtin')
const drawer = ref(false)
const uploading = ref(false)
const errors = ref<string[]>([])
const file = ref<File | null>(null)
const form = ref({ name: '', kind: 'vqa', capability: undefined as string | undefined, description: '' })
const previewing = ref<{ name: string; rows: unknown[] } | null>(null)

const builtin = computed(() => datasets.value.filter((d) => d.source === 'builtin'))
const custom = computed(() => datasets.value.filter((d) => d.source === 'custom'))
const groups = computed(() => ['doc_chart', 'general_qa', 'tool_call'].map((c) => [c, builtin.value.filter((d) => d.capability === c)] as const).filter(([, l]) => l.length))

const FORMATS: Record<string, { title: string; hint: string; example: string }> = {
  vqa: {
    title: '视觉问答',
    hint: '开放问答、OCR、图表问答。answer 是标准答案；配上裁判模型才能算准确率，否则只有 BLEU / ROUGE。',
    example: '{"messages":[{"role":"user","content":[{"type":"text","text":"图里写了什么？"},{"type":"image_url","image_url":{"url":"img/1.png"}}]}],"answer":"ORBIT-208"}',
  },
  vmcq: {
    title: '选择题',
    hint: '选项可以是文字或图片。question 里用 <image 1> 引用图片，对应 image_1 列；answer 是正确选项的字母。',
    example: '{"question":"<image 1> 背景是什么颜色？","options":["黄色","蓝色","绿色"],"image_1":"img/1.png","answer":"B"}',
  },
  fc: {
    title: '工具调用',
    hint: 'should_call_tool 标明这条输入该不该调用工具。只评“该不该调、工具名和参数格式对不对”，不检查参数的值。',
    example: '{"messages":[{"role":"user","content":"巴黎天气怎么样？"}],"tools":[{"type":"function","function":{"name":"get_weather","description":"查询天气","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],"should_call_tool":true}',
  },
}

async function load() {
  try { datasets.value = await api.datasets() } finally { loading.value = false }
}
onMounted(load)

function openUpload() {
  form.value = { name: '', kind: 'vqa', capability: undefined, description: '' }
  file.value = null
  errors.value = []
  drawer.value = true
}
const beforeUpload = (f: File) => { file.value = f; return false } // keep it local; we upload with the form
async function upload() {
  if (!form.value.name || !file.value) { message.warning('请填写名称并选择文件'); return }
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
    message.success(`已上传：${ds.name} v${ds.version}，${ds.num_samples} 条`)
    drawer.value = false
    await load()
  } catch (e: any) {
    errors.value = e.response?.data?.details ?? []
  } finally { uploading.value = false }
}
async function preview(d: Dataset) { previewing.value = { name: `${d.name} v${d.version}`, rows: await api.previewDataset(d.id) } }
async function remove(d: Dataset) { await api.deleteDataset(d.id); message.success('已删除'); await load() }

const columns = [
  { title: '名称', key: 'name' }, { title: '类型', key: 'kind', width: 130 }, { title: '能力', key: 'cap', width: 120 },
  { title: '样本数', dataIndex: 'num_samples', width: 100 }, { title: '上传', key: 'time', width: 130 }, { title: '', key: 'actions', width: 110, align: 'right' as const },
]
</script>

<template>
  <div class="page">
    <PageHeader title="评测集" sub="公开基准和你自己上传的数据集。">
      <a-button v-if="tab === 'custom'" type="primary" size="large" @click="openUpload"><template #icon><UploadOutlined /></template>上传评测集</a-button>
    </PageHeader>

    <a-segmented v-model:value="tab" style="margin-bottom: 16px" :options="[{ value: 'builtin', label: `内置基准 ${builtin.length}` }, { value: 'custom', label: `自有数据集 ${custom.length}` }]" />

    <a-spin :spinning="loading">
      <template v-if="tab === 'builtin'">
        <p class="muted" style="margin-top: 0">数据在第一次评测时自动下载并缓存。<b>已跑通</b>表示这个基准已经在本平台上实际跑过，其余来自 EvalScope 的官方列表，还没有在这里验证。</p>
        <div v-for="[cap, list] in groups" :key="cap" style="margin-bottom: 24px">
          <div class="row" style="margin-bottom: 10px"><b style="font-size: 16px">{{ CAPABILITY_LABEL[cap] }}</b><span class="faint">{{ CAPABILITY_HINT[cap] }}</span></div>
          <div class="grid grid-3">
            <div v-for="d in list" :key="d.id" class="card card-pad">
              <div class="row-between"><b>{{ d.name }}</b>
                <a-tag v-if="d.verified" color="success" style="margin: 0"><CheckCircleFilled /> 已跑通</a-tag>
                <a-tag v-else style="margin: 0">未验证</a-tag>
              </div>
              <div class="muted" style="margin: 6px 0 8px; font-size: 13.5px">{{ d.description }}</div>
              <span class="mono faint">{{ d.benchmark_id }}</span>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="card" style="overflow: hidden">
        <a-table :columns="columns" :data-source="custom" row-key="id" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'"><b>{{ record.name }}</b> <a-tag style="margin-left: 6px">v{{ record.version }}</a-tag><div v-if="record.description" class="faint" style="font-size: 12.5px">{{ record.description }}</div></template>
            <template v-else-if="column.key === 'kind'">{{ KIND_LABEL[record.kind] ?? record.kind }}</template>
            <template v-else-if="column.key === 'cap'">{{ CAPABILITY_LABEL[record.capability] ?? '—' }}</template>
            <template v-else-if="column.key === 'time'"><span class="muted">{{ fmtAgo(record.created_at) }}</span></template>
            <template v-else-if="column.key === 'actions'">
              <div class="row" style="justify-content: flex-end">
                <a-tooltip title="预览"><a-button type="text" size="small" @click="preview(record as Dataset)"><template #icon><EyeOutlined /></template></a-button></a-tooltip>
                <a-popconfirm title="删除这个评测集版本？" ok-text="删除" cancel-text="取消" :ok-button-props="{ danger: true }" @confirm="remove(record as Dataset)"><a-button type="text" size="small" danger><template #icon><DeleteOutlined /></template></a-button></a-popconfirm>
              </div>
            </template>
          </template>
          <template #emptyText>
            <a-empty description="还没有上传过自有评测集"><a-button type="primary" @click="openUpload">上传评测集</a-button></a-empty>
          </template>
        </a-table>
      </div>
    </a-spin>

    <a-drawer v-model:open="drawer" title="上传评测集" :width="620" destroy-on-close>
      <a-form layout="vertical" :model="form">
        <a-form-item label="名称" name="name" extra="同名再上传会生成新版本，历史结果不受影响。"><a-input v-model:value="form.name" /></a-form-item>
        <a-form-item label="类型" name="kind">
          <a-segmented v-model:value="form.kind" block :options="Object.entries(FORMATS).map(([value, f]) => ({ value, label: f.title }))" />
          <div class="muted" style="margin: 10px 0 8px; font-size: 13px">{{ FORMATS[form.kind].hint }}</div>
          <CopyCode :text="FORMATS[form.kind].example" />
        </a-form-item>
        <a-form-item label="能力（可选）" name="capability"><a-select v-model:value="form.capability" allow-clear placeholder="用于分组" :options="Object.entries(CAPABILITY_LABEL).map(([value, label]) => ({ value, label }))" /></a-form-item>
        <a-form-item label="说明（可选）" name="description"><a-input v-model:value="form.description" /></a-form-item>
        <a-form-item label="文件">
          <a-upload-dragger :before-upload="beforeUpload" :max-count="1" accept=".jsonl,.zip" :show-upload-list="true" @remove="file = null">
            <p class="ant-upload-drag-icon"><InboxOutlined /></p>
            <p class="ant-upload-text">点击或拖拽文件到这里</p>
            <p class="ant-upload-hint">.jsonl；带本地图片 / 视频时打包成 .zip（里面一个 .jsonl，媒体用相对路径引用）</p>
          </a-upload-dragger>
        </a-form-item>
      </a-form>
      <a-alert v-if="errors.length" type="error" show-icon message="数据集校验未通过">
        <template #description><div v-for="e in errors" :key="e">{{ e }}</div></template>
      </a-alert>
      <template #footer>
        <div class="row" style="justify-content: flex-end"><a-button @click="drawer = false">取消</a-button><a-button type="primary" :loading="uploading" @click="upload">上传并校验</a-button></div>
      </template>
    </a-drawer>

    <a-modal :open="!!previewing" :title="`预览 · ${previewing?.name}（前 5 条）`" :footer="null" :width="760" @cancel="previewing = null">
      <pre v-for="(r, i) in previewing?.rows" :key="i" class="code" style="margin-bottom: 10px; max-height: 240px; overflow: auto">{{ JSON.stringify(r, null, 1) }}</pre>
    </a-modal>
  </div>
</template>
