import { onBeforeUnmount, ref, watch } from 'vue'

const easeOutCubic = (t: number) => 1 - (1 - t) ** 3
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** A number that eases toward `source()`: 0 -> value on first show, current -> new value on change (no restart from 0). */
export function useTween(source: () => number, duration = 900) {
  const out = ref(0)
  let raf = 0

  watch(source, (to) => {
    cancelAnimationFrame(raf)
    if (reducedMotion() || duration <= 0) { out.value = to; return }
    const from = out.value
    const t0 = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / duration)
      out.value = from + (to - from) * easeOutCubic(t)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
  }, { immediate: true })

  onBeforeUnmount(() => cancelAnimationFrame(raf))
  return out
}
