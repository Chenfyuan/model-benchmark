<script setup lang="ts">
import type { Run } from '../api'
import { STAGE_LABEL, STATUS_BADGE, STATUS_LABEL } from '../format'

defineProps<{ run: Pick<Run, 'status' | 'stage' | 'progress'>; showProgress?: boolean }>()
</script>

<template>
  <div>
    <a-badge :status="STATUS_BADGE[run.status]" :text="STATUS_LABEL[run.status]" />
    <span v-if="run.status === 'running' && STAGE_LABEL[run.stage]" class="faint" style="margin-left: 8px; font-size: 12px">{{ STAGE_LABEL[run.stage] }}</span>
    <a-progress v-if="showProgress && run.status === 'running' && run.stage === 'evaluating'" :percent="Math.round(run.progress * 100)" size="small" :show-info="false" style="margin: 2px 0 0; width: 140px" />
  </div>
</template>
