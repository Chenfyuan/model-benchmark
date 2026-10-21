<script setup lang="ts">
import type { CheckResult } from '../api'

defineProps<{ result: CheckResult }>()
const LABELS = { text: '文本调用', image: '图片输入（模型真的看到了图）', tools: '工具调用' } as const
</script>

<template>
  <div>
    <el-alert v-for="w in result.warnings" :key="w" :title="w" type="warning" show-icon :closable="false" style="margin-bottom: 8px" />
    <el-descriptions :column="1" border style="margin-top: 8px">
      <el-descriptions-item v-for="(label, key) in LABELS" :key="key" :label="label">
        <el-tag :type="result.checks[key].ok ? 'success' : 'danger'" size="small">{{ result.checks[key].ok ? '通过' : '未通过' }}</el-tag>
        <span style="margin-left: 8px">{{ result.checks[key].detail }}</span>
        <span v-if="result.checks[key].latency_ms" class="muted" style="margin-left: 8px">{{ result.checks[key].latency_ms }} ms</span>
      </el-descriptions-item>
    </el-descriptions>
    <p v-if="!result.ok" class="muted">文本和图片必须都通过，这个模型才适合做多模态评测。</p>
  </div>
</template>
