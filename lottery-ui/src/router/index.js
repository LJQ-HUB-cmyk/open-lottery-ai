/**
 * Vue Router 配置
 * 定义路由映射和页面懒加载
 */
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    component: () => import('@/views/dashboard/index.vue'),
    meta: { title: '首页' }
  },
  {
    path: '/data',
    component: () => import('@/views/data/index.vue'),
    meta: { title: '数据管理' }
  },
  {
    path: '/train',
    component: () => import('@/views/train/index.vue'),
    meta: { title: '模型训练' }
  },
  {
    path: '/predict',
    component: () => import('@/views/predict/index.vue'),
    meta: { title: '预测结果' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router