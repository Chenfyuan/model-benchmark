<script setup lang="ts">
// Heng progress bar: width eases to the real value; a sheen runs only while the run is really going (`live`).
defineProps<{ percent: number; live?: boolean }>()
</script>

<template>
  <div class="track" role="progressbar" :aria-valuenow="Math.round(percent)" aria-valuemin="0" aria-valuemax="100">
    <div class="fill" :class="{ live }" :style="{ width: Math.min(100, Math.max(0, percent)) + '%' }" />
  </div>
</template>

<style scoped>
.track { height: 6px; border-radius: var(--radius-sm); background: var(--surface-2); overflow: hidden; }
.fill { height: 100%; border-radius: inherit; background: var(--signal); transition: width var(--hg-med, 320ms) cubic-bezier(.2, .8, .2, 1); }
.fill.live { background: linear-gradient(90deg, var(--signal) 0%, color-mix(in srgb, var(--signal) 55%, #fff) 50%, var(--signal) 100%); background-size: 200% 100%; animation: sheen 1.8s linear infinite; }
@keyframes sheen { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .fill { transition: none; } .fill.live { animation: none; } }
</style>
