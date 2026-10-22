<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { chartTheme } from '../chartTheme'
import { isDark } from '../theme'

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ categories: string[]; series: { name: string; values: (number | null)[]; displays: string[] }[]; max?: number }>()
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
    legend: { top: 0, textStyle: { color: text }, icon: 'roundRect' },
    grid: { left: 4, right: 56, top: 36, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...t.tooltip },
    xAxis: { type: 'value', min: 0, max: props.max, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
    yAxis: { type: 'category', inverse: true, data: props.categories, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: text } },
    series: props.series.map((s, i) => ({
      name: s.name, type: 'bar', barMaxWidth: 16, data: s.values,
      label: { show: true, position: 'right', color: t.ink, fontSize: 11, formatter: (p: { dataIndex: number }) => s.displays[p.dataIndex] },
      itemStyle: t.series(i),
    })),
  }, true)
}
const onResize = () => chart?.resize()
onMounted(() => { draw(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
watch(() => [props.categories, props.series, isDark.value], draw, { deep: true })
</script>

<template>
  <div ref="el" :style="{ height: Math.max(160, props.categories.length * props.series.length * 22 + 70) + 'px' }" />
</template>
