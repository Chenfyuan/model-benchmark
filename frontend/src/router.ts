import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/runs' },
    { path: '/models', component: () => import('./views/ModelsView.vue'), meta: { title: '模型管理' } },
    { path: '/datasets', component: () => import('./views/DatasetsView.vue'), meta: { title: '评测集' } },
    { path: '/runs/new', component: () => import('./views/NewRunView.vue'), meta: { title: '发起评测' } },
    { path: '/runs', component: () => import('./views/RunsView.vue'), meta: { title: '评测任务' } },
    { path: '/compare', component: () => import('./views/CompareView.vue'), meta: { title: '模型对比' } },
    { path: '/settings', component: () => import('./views/SettingsView.vue'), meta: { title: '费用限额' } },
    { path: '/runs/:id', component: () => import('./views/RunDetailView.vue'), meta: { title: '评测结果' } },
  ],
})
