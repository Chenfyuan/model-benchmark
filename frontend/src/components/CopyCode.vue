<script setup lang="ts">
import { CopyOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const props = defineProps<{ text: string }>()
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    message.success('已复制')
  } catch { message.warning('浏览器不允许复制，请手动选中') }
}
</script>

<template>
  <div style="position: relative">
    <pre class="code">{{ text }}</pre>
    <a-tooltip title="复制"><a-button size="small" type="text" style="position: absolute; top: 6px; right: 6px" @click="copy"><template #icon><CopyOutlined /></template></a-button></a-tooltip>
  </div>
</template>
