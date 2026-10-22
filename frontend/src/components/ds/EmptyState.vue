<script setup lang="ts">
// Empty state: a quiet line icon (the balance motif), what is missing, what to do next (default slot = the action).
defineProps<{ title: string; hint?: string; card?: boolean; compact?: boolean }>()
</script>

<template>
  <div class="empty" :class="{ card, compact }">
    <svg width="44" height="44" viewBox="0 0 44 44" fill="none" aria-hidden="true" class="ic">
      <path d="M9 16h26M22 16v18M15 34h14" />
      <circle cx="11" cy="24" r="4" />
      <circle cx="33" cy="24" r="4" class="on" />
    </svg>
    <div class="title">{{ title }}</div>
    <div v-if="hint" class="hint">{{ hint }}</div>
    <div v-if="$slots.default" class="act"><slot /></div>
  </div>
</template>

<style scoped>
.empty { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 48px 20px; }
.empty.compact { padding: 28px 20px; }
.card { padding-top: 56px; padding-bottom: 56px; }
.ic { stroke: var(--line-strong); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; margin-bottom: 14px; }
.ic .on { fill: var(--signal-soft); stroke: var(--signal); }
.title { font-size: 15px; font-weight: 600; color: var(--ink); }
.hint { margin-top: 4px; font-size: 13px; color: var(--ink-muted); max-width: 420px; }
.act { margin-top: 16px; }
</style>
