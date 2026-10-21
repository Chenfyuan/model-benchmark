<script setup lang="ts">
defineProps<{ title: string; sub?: string }>()
</script>

<template>
  <div class="head">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="sub" class="muted">{{ sub }}</p>
    </div>
    <div class="row"><slot /></div>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin: 8px 0 20px; }
h1 { margin: 0; font-size: 24px; font-weight: 650; letter-spacing: -0.01em; }
p { margin: 4px 0 0; font-size: 14px; }
</style>
