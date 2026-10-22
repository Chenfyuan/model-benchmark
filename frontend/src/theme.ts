import { theme as antTheme } from 'ant-design-vue'
import type { ThemeConfig } from 'ant-design-vue/es/config-provider/context'
import { computed, ref, watchEffect } from 'vue'

const KEY = 'mb-theme'
function initial(): 'light' | 'dark' {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* storage unavailable */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const mode = ref<'light' | 'dark'>(initial())
export const isDark = computed(() => mode.value === 'dark')

watchEffect(() => {
  document.documentElement.dataset.theme = mode.value
  try { localStorage.setItem(KEY, mode.value) } catch { /* ignore */ }
})

export const toggleTheme = () => { mode.value = isDark.value ? 'light' : 'dark' }

// Heng tokens as literals: the ConfigProvider cannot read CSS variables (keep in sync with styles/tokens.css)
export const H = {
  dark: { bg: '#0d0f0b', surface: '#15180f', surface2: '#1e2218', line: '#2a2f22', lineStrong: '#454c39', ink: '#eef1e6', muted: '#9da391', signal: '#c8f169', onSignal: '#11140b', teal: '#5fd6c6', amber: '#f4bb45', danger: '#ff6b6b' },
  light: { bg: '#f5f4ee', surface: '#ffffff', surface2: '#eeede5', line: '#dedcd1', lineStrong: '#a9a797', ink: '#15170f', muted: '#5c604f', signal: '#4c7600', onSignal: '#ffffff', teal: '#0c6f67', amber: '#94590a', danger: '#c21d1d' },
}

export const antdTheme = computed<ThemeConfig>(() => {
  const c = isDark.value ? H.dark : H.light
  return {
    algorithm: isDark.value ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      colorPrimary: c.signal,
      colorInfo: c.signal,
      colorSuccess: c.teal,
      colorWarning: c.amber,
      colorError: c.danger,
      colorBgLayout: c.bg,
      colorBgContainer: c.surface,
      colorBgElevated: c.surface,
      colorBorder: c.lineStrong,
      colorBorderSecondary: c.line,
      colorText: c.ink,
      colorTextSecondary: c.muted,
      colorTextLightSolid: c.onSignal, // text on a primary button: the dark-mode signal is bright, Ant's default white would vanish
      borderRadius: 10,
      borderRadiusLG: 16,
      borderRadiusSM: 6,
      fontFamily: "'IBM Plex Sans', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
      motionEaseOut: 'cubic-bezier(.2,.8,.2,1)',
      boxShadowTertiary: isDark.value ? 'none' : '0 1px 2px rgba(21,23,15,.06), 0 10px 28px rgba(21,23,15,.06)',
    },
    components: {
      Table: { headerBg: 'transparent', headerColor: c.muted, rowHoverBg: c.surface2 },
      Card: { paddingLG: 20 },
    },
  }
})
