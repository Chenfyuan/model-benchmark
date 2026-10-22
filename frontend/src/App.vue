<script setup lang="ts">
import {
  ApiOutlined, BarChartOutlined, BulbFilled, ControlOutlined, BulbOutlined, DatabaseOutlined, ExperimentOutlined, SafetyCertificateOutlined, ThunderboltOutlined, UnorderedListOutlined,
} from '@ant-design/icons-vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { antdTheme, isDark, toggleTheme } from './theme'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const selected = computed(() => [route.path.startsWith('/runs') && route.path !== '/runs/new' ? '/runs' : route.path])
const go = ({ key }: { key: string | number }) => router.push(String(key))
</script>

<template>
  <a-config-provider :locale="zhCN" :theme="antdTheme">
    <a-layout style="min-height: 100vh">
      <a-layout-sider v-model:collapsed="collapsed" :width="232" :collapsed-width="72" collapsible theme="light" class="sider">
        <div class="logo" @click="router.push('/')">
          <div class="logo-mark"><ExperimentOutlined /></div>
          <div v-if="!collapsed" class="logo-text"><b>评测平台</b><span>多模态模型</span></div>
        </div>
        <a-menu theme="light" mode="inline" :selected-keys="selected" @click="go">
          <a-menu-item key="/runs/new"><template #icon><ThunderboltOutlined /></template>发起评测</a-menu-item>
          <a-menu-item key="/runs"><template #icon><UnorderedListOutlined /></template>评测任务</a-menu-item>
          <a-menu-item key="/compare"><template #icon><BarChartOutlined /></template>模型对比</a-menu-item>
          <a-menu-item key="/schemes"><template #icon><ControlOutlined /></template>评分方案</a-menu-item>
          <a-menu-item key="/models"><template #icon><ApiOutlined /></template>模型管理</a-menu-item>
          <a-menu-item key="/datasets"><template #icon><DatabaseOutlined /></template>评测集</a-menu-item>
          <a-menu-item key="/settings"><template #icon><SafetyCertificateOutlined /></template>费用限额</a-menu-item>
        </a-menu>
      </a-layout-sider>

      <a-layout>
        <a-layout-header class="topbar">
          <span class="faint">多模态模型评测平台</span>
          <a-tooltip :title="isDark ? '切换到浅色' : '切换到深色'">
            <a-button type="text" shape="circle" @click="toggleTheme">
              <template #icon><component :is="isDark ? BulbFilled : BulbOutlined" /></template>
            </a-button>
          </a-tooltip>
        </a-layout-header>
        <a-layout-content>
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in"><component :is="Component" /></transition>
          </router-view>
        </a-layout-content>
      </a-layout>
    </a-layout>
  </a-config-provider>
</template>

<style scoped>
.sider { position: sticky; top: 0; height: 100vh; overflow: auto; background: var(--surface) !important; border-right: 1px solid var(--line); }
.sider :deep(.ant-menu) { background: transparent; border-inline-end: 0; }
.sider :deep(.ant-menu-item-selected) { background: var(--signal-soft); box-shadow: inset 2px 0 0 var(--signal); }
.sider :deep(.ant-layout-sider-trigger) { background: var(--surface-2) !important; color: var(--ink-muted); border-top: 1px solid var(--line); }
:deep(.ant-layout-header) { background: transparent !important; }
.logo { display: flex; align-items: center; gap: 12px; padding: 20px 22px 18px; cursor: pointer; }
.logo-mark { width: 36px; height: 36px; border-radius: 10px; background: var(--signal); display: flex; align-items: center; justify-content: center; color: var(--on-signal); font-size: 18px; flex: none; }
.logo-text { display: flex; flex-direction: column; line-height: 1.25; color: var(--ink); }
.logo-text b { font-size: 16px; }
.logo-text span { font-size: 12px; color: var(--ink-muted); }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 0 32px; height: 56px; line-height: 56px; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.12s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
