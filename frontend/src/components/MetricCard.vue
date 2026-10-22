<script setup lang="ts">
import CountUp from './ds/CountUp.vue'

// `value` is the already formatted text. Pass `num` (+ `format`) as well to have the number count up to it.
defineProps<{ label: string; value: string; hint?: string; accent?: 'good' | 'bad' | 'primary'; num?: number | null; format?: (n: number) => string }>()
</script>

<template>
  <div class="card card-pad metric">
    <div class="muted label-row">{{ label }}</div>
    <div class="value" :class="accent"><CountUp v-if="num != null" :value="num" :format="format" /><template v-else>{{ value }}</template></div>
    <div v-if="hint" class="faint hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.metric { padding: 16px 18px; }
.label-row { font-size: 13px; }
.value { font-family: var(--font-display); font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 6px 0 2px; font-variant-numeric: tabular-nums; }
.value.good { color: var(--teal); }
.value.bad { color: var(--danger); }
.value.primary { color: var(--signal); }
.hint { font-size: 12px; }
</style>
