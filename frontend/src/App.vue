<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const active = computed(() => (route.path.startsWith('/runs') && route.path !== '/runs/new' ? '/runs' : route.path))
</script>

<template>
  <el-container class="shell">
    <el-aside width="200px" class="aside">
      <div class="brand">多模态模型<br />评测平台</div>
      <el-menu :default-active="active" router class="menu">
        <el-menu-item index="/runs/new">发起评测</el-menu-item>
        <el-menu-item index="/runs">评测任务</el-menu-item>
        <el-menu-item index="/models">模型管理</el-menu-item>
        <el-menu-item index="/datasets">评测集</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f5f7fa; }
.shell { min-height: 100%; }
.aside { background: #fff; border-right: 1px solid #e4e7ed; }
.brand { padding: 20px 20px 12px; font-size: 18px; font-weight: 600; line-height: 1.4; }
.menu { border-right: none; }
.main { padding: 24px 32px; max-width: 1400px; }
.page-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-head h2 { margin: 0; font-size: 20px; }
.muted { color: #909399; font-size: 13px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
</style>
