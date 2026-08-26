import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layouts/MainLayout.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: Layout,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/Dashboard.vue'),
          meta: { title: '仪表盘' }
        },
        {
          path: 'projects',
          name: 'Projects',
          component: () => import('@/views/ProjectManagement.vue'),
          meta: { title: '项目管理' }
        },
        {
          path: 'ai/generate',
          name: 'AIGenerate',
          component: () => import('@/views/ai/CaseGenerate.vue'),
          meta: { title: 'AI智能用例生成' }
        },
        {
          path: 'ai/knowledge',
          name: 'KnowledgeManagement',
          component: () => import('@/views/ai/KnowledgeManagement.vue'),
          meta: { title: '知识库管理' }
        },
        {
          path: 'ai/rules',
          name: 'RuleManagement',
          component: () => import('@/views/ai/RuleManagement.vue'),
          meta: { title: '测试规则管理' }
        },
        {
          path: 'ai/history',
          name: 'GenerationHistory',
          component: () => import('@/views/ai/GenerationHistory.vue'),
          meta: { title: '生成历史' }
        },
        {
          path: 'elements',
          name: 'Elements',
          component: () => import('@/views/ElementLibrary.vue'),
          meta: { title: '元素库' }
        },
        {
          path: 'cases',
          name: 'Cases',
          component: () => import('@/views/Cases.vue'),
          meta: { title: '用例管理' }
        },
        {
          path: 'cases/:id',
          name: 'CaseDetail',
          component: () => import('@/views/CaseDetail.vue'),
          meta: { title: '用例详情' }
        },
        {
          path: 'scripts',
          name: 'ScriptConvert',
          component: () => import('@/views/ScriptConvert.vue'),
          meta: { title: '用例转脚本' }
        },
        {
          path: 'settings/ai',
          name: 'AISettings',
          component: () => import('@/views/system/AISettings.vue'),
          meta: { title: 'AI设置' }
        },
        {
          path: 'settings/runtime',
          name: 'RuntimeConfig',
          component: () => import('@/views/system/RuntimeConfig.vue'),
          meta: { title: '运行配置' }
        },
        {
          path: 'settings/env',
          name: 'EnvManagement',
          component: () => import('@/views/system/EnvManagement.vue'),
          meta: { title: '环境管理' }
        },
        {
          path: 'settings/tokens',
          name: 'TokenDashboard',
          component: () => import('@/views/system/TokenDashboard.vue'),
          meta: { title: 'Token成本管理' }
        }
      ]
    }
  ]
})

export default router
