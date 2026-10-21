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

export const PRIMARY = '#5b5bd6'

export const antdTheme = computed<ThemeConfig>(() => ({
  algorithm: isDark.value ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
  token: {
    colorPrimary: PRIMARY,
    colorInfo: PRIMARY,
    colorSuccess: '#12a594',
    colorWarning: '#f5a524',
    colorError: '#e5484d',
    borderRadius: 10,
    borderRadiusLG: 14,
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    colorBgLayout: isDark.value ? '#0d0f14' : '#f4f5fa',
    colorBgContainer: isDark.value ? '#161922' : '#ffffff',
    colorBorderSecondary: isDark.value ? '#262a36' : '#e8eaf2',
    boxShadowTertiary: isDark.value ? 'none' : '0 1px 2px rgba(20,24,40,.04), 0 4px 16px rgba(20,24,40,.04)',
  },
  components: {
    Menu: { darkItemBg: 'transparent', darkItemSelectedBg: 'rgba(91,91,214,.28)', darkItemColor: 'rgba(255,255,255,.66)', itemMarginInline: 12, itemBorderRadius: 10 },
    Table: { headerBg: 'transparent', headerColor: isDark.value ? '#9aa1b5' : '#6b7285', rowHoverBg: isDark.value ? '#1c202b' : '#f7f8fd' },
    Card: { paddingLG: 20 },
  },
}))
