<template>
  <el-container class="main-layout">
    <el-aside width="200px" class="sidebar">
      <div class="logo">
        <h2>🌙 MoonTest</h2>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409EFF"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>

        <el-sub-menu index="ai">
          <template #title>
            <el-icon><MagicStick /></el-icon>
            <span>AI与用例</span>
          </template>
          <el-menu-item index="/ai/generate">AI智能用例生成</el-menu-item>
          <el-menu-item index="/ai/knowledge">知识库管理</el-menu-item>
          <el-menu-item index="/ai/rules">测试规则管理</el-menu-item>
          <el-menu-item index="/ai/history">生成历史</el-menu-item>
          <el-menu-item index="/reviews">用例评审与E2E精修</el-menu-item>
          <el-menu-item index="/ai/convert">用例转自动化脚本</el-menu-item>
          <el-menu-item index="/cases">用例管理</el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/elements">
          <el-icon><Grid /></el-icon>
          <span>元素库</span>
        </el-menu-item>

        <el-sub-menu index="api">
          <template #title>
            <el-icon><Connection /></el-icon>
            <span>接口与执行</span>
          </template>
          <el-menu-item index="/api/parse">接口文档解析</el-menu-item>
          <el-menu-item index="/api/manage">接口管理</el-menu-item>
          <el-menu-item index="/api/debug">单接口调试</el-menu-item>
          <el-menu-item index="/api/oneclick">一键测试</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="auto">
          <template #title>
            <el-icon><VideoCameraFilled /></el-icon>
            <span>自动化</span>
          </template>
          <el-menu-item index="/auto/ui">UI自动化测试</el-menu-item>
          <el-menu-item index="/auto/regression">回归测试</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="quality">
          <template #title>
            <el-icon><Document /></el-icon>
            <span>质量与报告</span>
          </template>
          <el-menu-item index="/whitescan">白盒测试</el-menu-item>
          <el-menu-item index="/reports">执行记录与报告</el-menu-item>
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
      <el-header class="header">
        <div class="header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta?.title || '首页')
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

.sidebar {
  background-color: #304156;
  overflow-x: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 20px;
}

.logo h2 {
  margin: 0;
}

.header {
  background: #fff;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.main-content {
  background: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}
</style>
