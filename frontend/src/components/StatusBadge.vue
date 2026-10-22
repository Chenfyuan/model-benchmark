<script setup lang="ts">
import type { Run } from '../api'
import { STAGE_LABEL, STATUS_LABEL, STATUS_TONE } from '../format'
import RunProgress from './ds/RunProgress.vue'

defineProps<{ run: Pick<Run, 'status' | 'stage' | 'progress'>; showProgress?: boolean }>()
</script>

<template>
  <div>
    <span class="pill" :class="[STATUS_TONE[run.status], { pulse: run.status === 'running' }]"><i class="dot" />{{ STATUS_LABEL[run.status] }}</span>
    <span v-if="run.status === 'running' && STAGE_LABEL[run.stage]" class="faint" style="margin-left: 8px; font-size: 12px">{{ STAGE_LABEL[run.stage] }}</span>
    <RunProgress v-if="showProgress && run.status === 'running' && run.stage === 'evaluating'" :percent="run.progress * 100" live style="margin-top: 6px; width: 140px" />
  </div>
</template>

<style scoped>
.pill { --tone: var(--ink-muted); display: inline-flex; align-items: center; gap: 6px; padding: 1px 10px 1px 8px; border-radius: var(--radius-pill); font-size: 12px; line-height: 20px; color: var(--tone); background: color-mix(in srgb, var(--tone) 12%, transparent); border: 1px solid color-mix(in srgb, var(--tone) 35%, transparent); }
.pill.signal { --tone: var(--signal); }
.pill.teal { --tone: var(--teal); }
.pill.amber { --tone: var(--amber); }
.pill.danger { --tone: var(--danger); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--tone); }
.pulse .dot { animation: pulse 1.4s ease-out infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--tone) 60%, transparent); } 100% { box-shadow: 0 0 0 7px transparent; } }
@media (prefers-reduced-motion: reduce) { .pulse .dot { animation: none; } }
</style>
