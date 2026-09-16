<template>
  <el-container class="main-layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <h2>🌙 <span class="logo-text">MoonTest</span></h2>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>

        <el-sub-menu index="case-assets">
          <template #title>
            <el-icon><MagicStick /></el-icon>
            <span>用例资产</span>
          </template>
          <el-menu-item index="/cases">用例管理</el-menu-item>
          <el-menu-item index="/reviews">用例评审与E2E精修</el-menu-item>
          <el-menu-item index="/ai/generate">AI智能用例生成</el-menu-item>
          <el-menu-item index="/ai/knowledge">知识库管理</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="element-assets">
          <template #title>
            <el-icon><Grid /></el-icon>
            <span>元素资产</span>
          </template>
          <el-menu-item index="/elements/capture">元素抓取</el-menu-item>
          <el-menu-item index="/elements/list">元素管理</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="auto">
          <template #title>
            <el-icon><VideoCameraFilled /></el-icon>
            <span>自动化</span>
          </template>
          <el-menu-item index="/ai/convert">用例转自动化脚本</el-menu-item>
          <el-menu-item index="/auto/ui">UI自动化测试</el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/whitescan">
          <el-icon><Document /></el-icon>
          <span>白盒测试</span>
        </el-menu-item>

        <el-sub-menu index="api">
          <template #title>
            <el-icon><Connection /></el-icon>
            <span>接口与执行</span>
          </template>
          <el-menu-item index="/api/parse" disabled>接口文档解析（二期）</el-menu-item>
          <el-menu-item index="/api/manage" disabled>接口管理（二期）</el-menu-item>
          <el-menu-item index="/api/debug" disabled>单接口调试（二期）</el-menu-item>
          <el-menu-item index="/api/oneclick" disabled>一键测试（二期）</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="settings">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统设置</span>
          </template>
          <el-menu-item index="/settings/ai">AI设置</el-menu-item>
          <el-menu-item index="/settings/runtime">运行配置</el-menu-item>
          <el-menu-item index="/settings/env">环境管理</el-menu-item>
          <el-menu-item index="/settings/tokens">Token成本管理</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header" height="56px">
        <div class="header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-for="(c, i) in trail" :key="c.key"
              :to="c.path ? { path: c.path } : undefined">{{ c.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-icon><User /></el-icon>
          <span>管理员</span>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta?.title || '首页')

// 访问轨迹面包屑：静态层级（meta.crumbs 中间层）+ 本会话内点过的页面链。
// 例：首页 → UI自动化测试 → 测试集详情 → 报告详情，全程可点回跳。
const STATIC_PARENT_PATHS = {
  '用例管理': '/cases',
  '执行记录与报告': '/reports',
  'UI自动化测试': '/auto/ui',
}
const MAX_TRAIL = 6
const visitTrail = ref([]) // [{ title, path }]
const lastRecorded = ref('')

watch(() => route.fullPath, () => {
  const title = currentTitle.value
  const path = route.path
  // 同页参数变化（如详情页内切换 id）不重复入栈
  if (visitTrail.value.length && visitTrail.value[visitTrail.value.length - 1].path === path) return
  if (lastRecorded.value === path + '|' + title) return
  lastRecorded.value = path + '|' + title
  // 去重：回到轨迹中已有页面则截断到该处（返回语义）
  const idx = visitTrail.value.findIndex(v => v.path === path)
  if (idx >= 0) {
    visitTrail.value = visitTrail.value.slice(0, idx)
    return
  }
  visitTrail.value.push({ title, path })
  if (visitTrail.value.length > MAX_TRAIL) visitTrail.value.shift()
}, { immediate: true })

const trail = computed(() => {
  // 静态中间层（meta.crumbs）在最前，然后是访问轨迹（不含当前页——当前页已是轨迹最后一项）
  const crumbs = (route.meta?.crumbs || []).map(t => ({
    title: t, path: STATIC_PARENT_PATHS[t] || '', key: 'static-' + t,
  }))
  return [...crumbs, ...visitTrail.value.map((v, i) => ({ ...v, key: `v${i}-${v.path}` }))]
})

</script>

<style scoped>
.main-layout {
  height: 100vh;
}

/* ---- 侧边栏：浅色 ---- */
.sidebar {
  background: var(--mt-sidebar);
  border-right: 1px solid var(--mt-border);
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--mt-border);
  flex-shrink: 0;
}

.logo h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
}

.logo-text {
  background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* ---- 菜单（去掉 el-menu 深色默认，全 CSS 接管） ---- */
.sidebar-menu {
  border-right: none;
  background: transparent;
  padding: 8px;
  flex: 1;
  overflow-y: auto;
}
.sidebar-menu .el-menu-item,
.sidebar-menu :deep(.el-sub-menu__title) {
  height: 42px;
  line-height: 42px;
  border-radius: 6px;
  margin: 2px 0;
  color: var(--mt-sidebar-text);
}
.sidebar-menu :deep(.el-menu-item:hover),
.sidebar-menu :deep(.el-sub-menu__title:hover) {
  background: var(--mt-sidebar-hover-bg);
  color: var(--mt-text);
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--mt-sidebar-active-bg);
  color: var(--mt-sidebar-active-text);
  font-weight: 600;
}
.sidebar-menu :deep(.el-menu-item.is-active .el-icon) {
  color: var(--mt-sidebar-active-text);
}
/* 二级菜单缩进区背景 */
.sidebar-menu :deep(.el-menu .el-menu-item) {
  padding-left: 48px !important;
  min-width: 0;
}
.sidebar-menu :deep(.el-sub-menu.is-disabled .el-menu-item) {
  color: #CBD5E1;
  cursor: not-allowed;
}

/* ---- 顶栏 ---- */
.header {
  background: var(--mt-surface);
  border-bottom: 1px solid var(--mt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--mt-text-secondary);
  padding: 6px 12px;
  border-radius: 6px;
  cursor: default;
}
.header-right:hover {
  background: var(--mt-sidebar-hover-bg);
}

/* ---- 主内容区 ---- */
.main-content {
  background: var(--mt-bg);
  padding: 24px;
  overflow-y: auto;
}

/* 面包屑当前项主色 */
.header-left :deep(.el-breadcrumb__inner.is-link),
.header-left :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--mt-primary);
  font-weight: 500;
}
/* 中间层级不可点时保持默认灰（无 is-link class 则无 hover） */
</style>
