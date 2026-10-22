<script setup lang="ts">
// Heng mark: a balance (beam + two pans) on a signal tile. Static on purpose: loops are for things that are really running.
withDefaults(defineProps<{ size?: number }>(), { size: 28 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 28 28" aria-hidden="true" class="mark">
    <rect width="28" height="28" rx="8" class="bg" />
    <path d="M6 10h16M14 10v11M10 21h8" class="beam" />
    <circle cx="7" cy="15" r="2.4" class="dot" />
    <circle cx="21" cy="15" r="2.4" class="dot" />
  </svg>
</template>

<style scoped>
.mark { flex: none; display: block; }
.bg { fill: var(--signal); }
.beam { fill: none; stroke: var(--on-signal); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.dot { fill: var(--on-signal); }
</style>
