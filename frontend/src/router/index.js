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
          meta: { title: 'AI智能用例生成', crumbs: ['AI与用例'] }
        },
        {
          path: 'ai/knowledge',
          name: 'KnowledgeManagement',
          component: () => import('@/views/ai/KnowledgeManagement.vue'),
          meta: { title: '知识库管理', crumbs: ['AI与用例'] }
        },
        { // 菜单已隐藏，直链可访问
          path: 'ai/rules',
          name: 'RuleManagement',
          component: () => import('@/views/ai/RuleManagement.vue'),
          meta: { title: '测试规则管理', crumbs: ['AI与用例'] }
        },
        { // 菜单已隐藏，直链可访问
          path: 'ai/history',
          name: 'GenerationHistory',
          component: () => import('@/views/ai/GenerationHistory.vue'),
          meta: { title: '生成历史', crumbs: ['AI与用例'] }
        },
        {
          path: 'elements',
          name: 'Elements',
          redirect: '/elements/capture',
        },
        {
          path: 'elements/capture',
          name: 'ElementCapture',
          component: () => import('@/views/ElementLibrary.vue'),
          meta: { title: '元素抓取', crumbs: ['元素库'] }
        },
        {
          path: 'elements/list',
          name: 'ElementList',
          component: () => import('@/views/ElementList.vue'),
          meta: { title: '元素管理', crumbs: ['元素库'] }
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
          meta: { title: '用例详情', crumbs: ['用例管理'] }
        },
        {
          path: 'ai/convert',
          name: 'ScriptConvert',
          component: () => import('@/views/ScriptConvert.vue'),
          meta: { title: '用例转自动化脚本', crumbs: ['UI自动化'] }
        },
        {
          path: 'scripts',
          name: 'ScriptConvertAlias',
          redirect: '/ai/convert'
        },
        {
          path: 'auto/ui',
          name: 'AutoUITest',
          component: () => import('@/views/AutoUITest.vue'),
          meta: { title: 'UI自动化测试', crumbs: ['UI自动化'] }
        },
        {
          path: 'auto/ui/set/:id',
          name: 'TestSetDetail',
          component: () => import('@/views/TestSetDetail.vue'),
          meta: { title: '测试集详情', crumbs: ['UI自动化', 'UI自动化测试'] }
        },
        {
          path: 'settings/ai',
          name: 'AISettings',
          component: () => import('@/views/system/AISettings.vue'),
          meta: { title: 'AI设置', crumbs: ['系统设置'] }
        },
        {
          path: 'settings/runtime',
          name: 'RuntimeConfig',
          component: () => import('@/views/system/RuntimeConfig.vue'),
          meta: { title: '运行配置', crumbs: ['系统设置'] }
        },
        {
          path: 'settings/env',
          name: 'EnvManagement',
          component: () => import('@/views/system/EnvManagement.vue'),
          meta: { title: '环境管理', crumbs: ['系统设置'] }
        },
        {
          path: 'settings/tokens',
          name: 'TokenDashboard',
          component: () => import('@/views/system/TokenDashboard.vue'),
          meta: { title: 'Token成本管理', crumbs: ['系统设置'] }
        },
        { // 菜单已隐藏，直链可访问
          path: 'reports',
          name: 'ExecutionList',
          component: () => import('@/views/reports/ExecutionList.vue'),
          meta: { title: '执行记录与报告' }
        },
        {
          path: 'reports/:execId',
          name: 'ReportDetail',
          component: () => import('@/views/reports/ReportDetail.vue'),
          meta: { title: '报告详情', crumbs: ['执行记录与报告'] }
        },
        {
          path: 'reviews',
          name: 'ReviewCenter',
          component: () => import('@/views/reviews/ReviewCenter.vue'),
          meta: { title: '用例评审与E2E精修' }
        },
        {
          path: 'whitescan',
          name: 'WhiteScan',
          component: () => import('@/views/whitescan/WhiteScan.vue'),
          meta: { title: '白盒测试' }
        }
      ]
    }
  ]
})

export default router
