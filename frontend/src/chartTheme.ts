import { H, isDark } from './theme'

// Heng series order is fixed: signal -> coral -> teal -> amber. Series 5-8 reuse those hues at a different lightness
// (contrast against the card >= 3.2:1 in both themes) and get a stripe decal so they never rely on colour alone.
// Past 8 series: muted grey, also striped.
const SERIES = {
  dark: ['#c8f169', '#ff8a66', '#5fd6c6', '#f4bb45', '#5f830c', '#e03500', '#228679', '#9f6e09'],
  light: ['#4c7600', '#b8400f', '#0c6f67', '#94590a', '#669e00', '#ed6026', '#119c91', '#cd7c0e'],
}

export function chartTheme() {
  const c = isDark.value ? H.dark : H.light
  const palette = isDark.value ? SERIES.dark : SERIES.light
  const stripe = { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [3, 4], rotation: -Math.PI / 4, color: isDark.value ? 'rgba(13,15,11,.5)' : 'rgba(255,255,255,.55)' }
  return {
    text: c.muted,
    ink: c.ink,
    grid: c.line,
    track: c.surface2,
    signal: c.signal,
    /** itemStyle of the i-th series */
    series: (i: number) => ({ color: i < palette.length ? palette[i] : c.muted, decal: i >= 4 ? stripe : undefined, borderRadius: 6 }),
    tooltip: { backgroundColor: c.surface, borderColor: c.line, textStyle: { color: c.ink } },
    animation: { animationDuration: 900, animationEasing: 'cubicOut' as const },
  }
}
