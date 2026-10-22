<script setup lang="ts">
import { computed } from 'vue'
import { useTween } from '../../composables/useTween'

const props = defineProps<{ value: number; format?: (n: number) => string; duration?: number }>()
const shown = useTween(() => props.value, props.duration)
const text = computed(() => (props.format ? props.format(shown.value) : String(Math.round(shown.value))))
</script>

<template>
  <span class="num">{{ text }}</span>
</template>
