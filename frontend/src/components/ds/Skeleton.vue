<script setup lang="ts">
// Placeholder block while data loads: a quiet surface-2 slab with a slow sheen (static under prefers-reduced-motion).
withDefaults(defineProps<{ h?: number; w?: number | string }>(), { h: 16 })
</script>

<template>
  <div class="sk" :style="{ height: h + 'px', width: typeof w === 'number' ? w + 'px' : w }" aria-hidden="true" />
</template>

<style scoped>
.sk { border-radius: var(--radius-md); background: linear-gradient(90deg, var(--surface-2) 0%, color-mix(in srgb, var(--surface-2) 55%, var(--surface)) 50%, var(--surface-2) 100%); background-size: 200% 100%; animation: sk-sheen 1.6s ease-in-out infinite; }
@keyframes sk-sheen { from { background-position: 100% 0; } to { background-position: -100% 0; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
