<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ title: string; items: { name: string; value: number; display: string }[]; max?: number }>()
const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function draw() {
  if (!el.value) return
  chart ??= echarts.init(el.value)
  chart.setOption({
    grid: { left: 8, right: 64, top: 16, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (p: { dataIndex: number }[]) => `${props.items[p[0].dataIndex].name}: ${props.items[p[0].dataIndex].display}` },
    xAxis: { type: 'value', min: 0, max: props.max },
    yAxis: { type: 'category', inverse: true, data: props.items.map((i) => i.name) },
    series: [{ type: 'bar', barMaxWidth: 28, data: props.items.map((i) => i.value), label: { show: true, position: 'right', formatter: (p: { dataIndex: number }) => props.items[p.dataIndex].display }, itemStyle: { color: '#409eff' } }],
  })
}
const onResize = () => chart?.resize()
onMounted(() => { draw(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
watch(() => props.items, draw, { deep: true })
</script>

<template>
  <div>
    <div class="muted" style="margin-bottom: 4px">{{ title }}</div>
    <div ref="el" :style="{ height: Math.max(120, items.length * 44 + 32) + 'px' }" />
  </div>
</template>
