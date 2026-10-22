<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { chartTheme } from '../chartTheme'
import { isDark } from '../theme'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ items: { name: string; value: number; display: string }[]; max?: number }>()
const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function draw() {
  if (!el.value) return
  chart ??= echarts.init(el.value)
  const t = chartTheme()
  const text = t.text
  const grid = t.grid
  chart.setOption({
    ...t.animation,
    grid: { left: 4, right: 64, top: 8, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'none' }, ...t.tooltip, formatter: (p: { dataIndex: number }[]) => `${props.items[p[0].dataIndex].name}<br/><b>${props.items[p[0].dataIndex].display}</b>` },
    xAxis: { type: 'value', min: 0, max: props.max, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
    yAxis: { type: 'category', inverse: true, data: props.items.map((i) => i.name), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: text, fontSize: 12 } },
    series: [{
      type: 'bar', barWidth: 16, showBackground: true, backgroundStyle: { color: t.track, borderRadius: 6 },
      data: props.items.map((i) => i.value),
      label: { show: true, position: 'right', color: t.ink, fontWeight: 600, formatter: (p: { dataIndex: number }) => props.items[p.dataIndex].display },
      itemStyle: { borderRadius: 6, color: t.signal },
    }],
  })
}
const onResize = () => chart?.resize()
onMounted(() => { draw(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
watch(() => [props.items, isDark.value], draw, { deep: true })
</script>

<template>
  <div ref="el" :style="{ height: Math.max(110, items.length * 44 + 24) + 'px' }" />
</template>
