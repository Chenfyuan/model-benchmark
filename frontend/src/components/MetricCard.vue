<script setup lang="ts">
defineProps<{ label: string; value: string; hint?: string; accent?: 'good' | 'bad' | 'primary' }>()
</script>

<template>
  <div class="card card-pad metric">
    <div class="muted label-row">{{ label }}</div>
    <div class="value" :class="accent">{{ value }}</div>
    <div v-if="hint" class="faint hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.metric { padding: 16px 18px; }
.label-row { font-size: 13px; }
.value { font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 6px 0 2px; font-variant-numeric: tabular-nums; }
.value.good { color: var(--c-good); }
.value.bad { color: var(--c-bad); }
.value.primary { color: var(--c-primary); }
.hint { font-size: 12px; }
</style>
