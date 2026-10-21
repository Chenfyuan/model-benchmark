<script setup lang="ts">
import { CheckCircleFilled, CloseCircleFilled, ExclamationCircleFilled } from '@ant-design/icons-vue'
import type { CheckResult } from '../api'

defineProps<{ result: CheckResult }>()
const ITEMS = [
  { key: 'text', title: '文本调用', sub: '能收到回复' },
  { key: 'image', title: '图片输入', sub: '模型真的读出了图里的随机码' },
  { key: 'tools', title: '工具调用', sub: '能返回结构化的工具调用' },
] as const
</script>

<template>
  <div>
    <div v-for="it in ITEMS" :key="it.key" class="item">
      <CheckCircleFilled v-if="result.checks[it.key].ok" class="ic good" />
      <CloseCircleFilled v-else class="ic bad" />
      <div style="flex: 1">
        <div class="row-between"><b>{{ it.title }}</b><span v-if="result.checks[it.key].latency_ms" class="faint mono">{{ result.checks[it.key].latency_ms }} ms</span></div>
        <div class="muted" style="font-size: 13px">{{ it.sub }}</div>
        <div v-if="!result.checks[it.key].ok" style="color: var(--c-bad); font-size: 13px; margin-top: 2px">{{ result.checks[it.key].detail }}</div>
      </div>
    </div>
    <div v-for="w in result.warnings" :key="w" class="item warn">
      <ExclamationCircleFilled class="ic" style="color: var(--c-warn)" />
      <div style="font-size: 13px">{{ w }}</div>
    </div>
    <p v-if="!result.ok" class="muted" style="margin: 12px 0 0; font-size: 13px">文本和图片必须都通过，这个模型才适合做多模态评测。</p>
  </div>
</template>

<style scoped>
.item { display: flex; gap: 12px; padding: 12px 14px; border: 1px solid var(--c-border); border-radius: 12px; margin-bottom: 10px; }
.item.warn { background: rgba(245, 165, 36, 0.08); border-color: rgba(245, 165, 36, 0.35); }
.ic { font-size: 20px; margin-top: 2px; }
.ic.good { color: var(--c-good); }
.ic.bad { color: var(--c-bad); }
</style>
