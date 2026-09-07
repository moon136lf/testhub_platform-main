<template>
  <div class="capture-workbench">
    <!-- idle: 开始表单 -->
    <div v-if="phase === 'idle'" class="wb-idle">
      <el-form inline @submit.prevent>
        <el-form-item label="项目">
          <el-select v-model="projectId" placeholder="选择项目" style="width: 220px">
            <el-option v-for="p in projects" :key="p.id" :label="p.project_name || p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-input v-model="url" placeholder="页面 URL，如 http://localhost:3000/login" style="width: 320px" @keyup.enter="start" />
        </el-form-item>
        <el-form-item>
          <el-switch v-model="needLogin" active-text="需要人工登录" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" :loading="starting" :disabled="!url || !projectId" @click="start">
            开始
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- awaiting_login -->
    <div v-else-if="phase === 'awaiting_login'">
      <el-alert type="info" :closable="false" show-icon class="login-banner">
        <template #title>浏览器已打开，请人工完成登录</template>
        <div class="login-banner-body">
          <span v-if="statusUrl">当前：{{ statusUrl }}</span>
          <span v-else>正在检测登录状态…</span>
        </div>
      </el-alert>
      <div class="login-actions">
        <el-button type="primary" :loading="checking" @click="confirmLogin">✅ 登录完成</el-button>
        <el-button @click="forceContinue">强制继续</el-button>
        <el-button @click="retryCheck" :loading="checking">重试</el-button>
        <el-button type="danger" plain @click="cancelSession">取消</el-button>
      </div>
    </div>

    <!-- ready / released 双栏工作台 -->
    <template v-else-if="phase === 'ready'">
      <div class="wb-toolbar">
        <el-tag type="success" size="small" effect="plain">会话进行中</el-tag>
        <span v-if="statusUrl" class="wb-url">{{ statusUrl }}</span>
        <div class="wb-toolbar-actions">
          <el-button size="small" @click="refreshScreenshot" :loading="refreshingShot">刷新截图</el-button>
          <el-button size="small" type="danger" plain @click="releasePage" :disabled="browserReleased">释放页面</el-button>
          <el-button size="small" type="danger" @click="closeSession">关闭会话</el-button>
        </div>
      </div>

      <el-alert
        v-if="browserReleased"
        type="warning" :closable="false" show-icon style="margin-bottom: 10px"
        title="页面已释放（浏览器已关闭），已抓元素保留。输入新 URL 重新打开可继续抓取。"
      >
        <div style="display:flex; gap:8px; margin-top:6px">
          <el-input v-model="url" placeholder="新页面 URL" size="small" style="width: 320px" />
          <el-button size="small" type="primary" :loading="starting" @click="reopen">打开新页面</el-button>
        </div>
      </el-alert>

      <el-row :gutter="16">
        <!-- 左：浏览器截图 -->
        <el-col :span="14">
          <el-card shadow="never">
            <template #header>
              <div class="shot-header">
                <span>浏览器实时画面</span>
                <div class="shot-header-actions">
                  <el-switch v-model="pickMode" size="small" active-text="点选补抓" />
                  <el-button size="small" type="primary" :loading="capturing" :disabled="browserReleased" @click="captureNow">
                    开始抓取元素
                  </el-button>
                </div>
              </div>
            </template>
            <div class="shot-container" :class="{ picking: pickMode && !browserReleased }" @click="onShotClick">
              <img v-if="screenshotSrc" :src="screenshotSrc" class="shot-img" referrerpolicy="no-referrer" />
              <div v-else class="no-screenshot">{{ browserReleased ? '浏览器已释放' : '暂无截图，点击「刷新截图」' }}</div>
            </div>
            <div v-if="pickMode" class="pick-hint">点选模式已开启：点击截图中目标元素即可补抓单个元素</div>
          </el-card>
        </el-col>

        <!-- 右：staging 元素列表 + 入库 -->
        <el-col :span="10">
          <el-card shadow="never">
            <template #header>
              <div class="shot-header">
                <span>
                  已抓元素
                  <el-tag v-if="stagingState" size="small" type="success" effect="plain">
                    {{ stagingState.included_count }}/{{ stagingState.total_elements }} 已勾选
                  </el-tag>
                </span>
                <div>
                  <el-button size="small" @click="toggleAll(false)" :disabled="!stagingState || stagingState.total_elements === 0">全不选</el-button>
                  <el-button size="small" @click="toggleAll(true)" :disabled="!stagingState || stagingState.total_elements === 0">全选</el-button>
                </div>
              </div>
            </template>

            <el-empty v-if="!stagingState || stagingState.total_elements === 0" description="尚未抓取，点击左侧「开始抓取元素」" :image-size="60" />
            <div v-else class="wb-elements">
              <div
                v-for="el in stagingState.elements"
                :key="el.temp_id"
                class="wb-element"
                :class="{ excluded: !el.included }"
              >
                <el-checkbox :model-value="el.included" @change="(v) => toggleElement(el.temp_id, v)">
                  <el-tag :type="typeColor(el.element_type)" size="small">{{ el.element_type }}</el-tag>
                  <span class="wb-el-text">{{ el.element_text || el.temp_id }}</span>
                  <el-tag size="small" type="info" effect="plain">批次 {{ (el.batch_idx ?? 0) + 1 }}</el-tag>
                </el-checkbox>
                <el-button size="small" type="danger" text @click="removeElement(el.temp_id)">删除</el-button>
              </div>
            </div>

            <!-- 入库 -->
            <div class="wb-import" v-if="stagingState && stagingState.included_count > 0">
              <el-select v-model="pageMode" style="width: 110px" size="small">
                <el-option label="新建页面" value="new" />
                <el-option label="已有页面" value="existing" :disabled="pages.length === 0" />
              </el-select>
              <template v-if="pageMode === 'new'">
                <el-input v-model="pageName" placeholder="页面名称（留空取 URL）" size="small" style="width: 170px" />
                <el-input v-model="pageUrl" placeholder="页面 URL（留空取抓取页）" size="small" style="width: 190px" />
              </template>
              <el-select v-else v-model="pageId" placeholder="选择已有页面" size="small" style="width: 200px">
                <el-option v-for="p in pages" :key="p.id" :label="p.page_name" :value="p.id" />
              </el-select>
              <el-button type="primary" size="small" :loading="importing" @click="importSelected">
                入库 {{ stagingState.included_count }} 个
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 点选补抓定位卡片弹层 -->
      <el-dialog v-model="pickCardVisible" title="点选补抓 — 定位卡片" width="560px">
        <div v-if="pickCard">
          <div class="pick-card-row">
            <el-tag :type="typeColor(pickCard.element_type)" size="small">{{ pickCard.element_type }}</el-tag>
            <span class="pick-card-text">{{ pickCard.element_text || '(无文本)' }}</span>
          </div>
          <div class="pick-card-row" v-if="bestStrategy">
            <span class="pick-label">最优策略：</span>
            <el-tag size="small" type="success" effect="plain">
              {{ bestStrategy.type }}: {{ bestStrategy.value }} (score {{ bestStrategy.score }})
            </el-tag>
          </div>
          <div class="pick-card-row" v-else>
            <el-tag size="small" type="warning">未生成有效定位策略</el-tag>
          </div>
          <div class="pick-card-row" v-if="(pickCard.locator_strategies?.strategies || []).length > 1">
            <span class="pick-label">其余策略：</span>
            <el-tag
              v-for="(s, i) in pickCard.locator_strategies.strategies.slice(1, 5)"
              :key="i" size="small" type="info" effect="plain" style="margin-right:4px"
            >
              {{ s.type }} ({{ s.score }})
            </el-tag>
          </div>
        </div>
        <template #footer>
          <el-button @click="pickCardVisible = false">取消</el-button>
          <el-button type="primary" :loading="addingPicked" @click="addPickedToStaging">加入列表</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { elementAPI } from '@/api/element'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  defaultProjectId: { type: String, default: '' }
})
const emit = defineEmits(['imported', 'closed'])

// ---- 状态机: idle → awaiting_login → ready（→ released 子态由 browserReleased 表示）----
const phase = ref('idle')
const browserSessionId = ref('')   // bs_*：驱动浏览器操作
const stagingSessionId = ref('')   // cap_*：staging/入库端点使用
const browserReleased = ref(false)

// idle 表单
const url = ref('')
const needLogin = ref(false)

// 选定项目后预填项目管理里配置的系统地址（用户可改）
watch(
  () => props.defaultProjectId,
  (pid) => {
    if (!pid || url.value) return
    const p = props.projects.find((x) => x.id === pid)
    if (p?.target_url) url.value = p.target_url
  },
  { immediate: true }
)
const starting = ref(false)
const projectId = computed(() => props.defaultProjectId)

// login
const checking = ref(false)
const statusUrl = ref('')
let pollTimer = null

// ready
const screenshotSrc = ref('')
const refreshingShot = ref(false)
const capturing = ref(false)
const pickMode = ref(false)

// staging 列表
const stagingState = ref(null)
const pageMode = ref('new')
const pageName = ref('')
const pageUrl = ref('')
const pageId = ref('')
const pages = ref([])
const importing = ref(false)

// pick
const pickCard = ref(null)
const pickCardVisible = ref(false)
const addingPicked = ref(false)

// 实际视口尺寸：由 status 接口返回（headed 模式跟随窗口大小，动态变化）
const viewportW = ref(1920)
const viewportH = ref(1080)

const bestStrategy = computed(() => {
  const list = pickCard.value?.locator_strategies?.strategies || []
  return list.length > 0 ? list[0] : null
})

const typeColor = (type) => {
  const map = { button: 'primary', input: 'success', link: 'warning', select: 'info', textarea: 'info' }
  return map[type] || 'default'
}

// ---- idle → open ----
const start = async () => {
  if (!url.value || !projectId.value) return
  starting.value = true
  try {
    const r = await elementAPI.openBrowserSession({
      project_id: projectId.value,
      url: url.value,
      need_login: needLogin.value
    })
    browserSessionId.value = r.session_id
    browserReleased.value = false
    if (r.state === 'awaiting_login') {
      phase.value = 'awaiting_login'
      startPolling()
    } else {
      phase.value = 'ready'
      refreshScreenshot()
    }
  } catch (err) {
    ElMessage.error('打开浏览器会话失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    starting.value = false
  }
}

// released 后再 open：复用同一 bs 会话
const reopen = () => start()

// ---- awaiting_login 轮询与操作 ----
const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (phase.value !== 'awaiting_login') return stopPolling()
    try {
      const s = await elementAPI.getBrowserStatus(browserSessionId.value)
      statusUrl.value = s.url || ''
      if (s.state === 'ready') {
        phase.value = 'ready'
        stopPolling()
        refreshScreenshot()
        ElMessage.success('检测到登录成功，进入工作台')
      }
    } catch { /* 会话消失时由用户操作报错兜底 */ }
  }, 3000)
}
const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const confirmLogin = async () => {
  checking.value = true
  try {
    const s = await elementAPI.getBrowserStatus(browserSessionId.value)
    statusUrl.value = s.url || ''
    if (s.state === 'ready') {
      phase.value = 'ready'
      stopPolling()
      refreshScreenshot()
    } else {
      ElMessage.warning('未检测到登录成功（URL 仍含登录关键字），可强制继续或重试')
    }
  } catch (err) {
    ElMessage.error('查询状态失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    checking.value = false
  }
}

const forceContinue = () => {
  phase.value = 'ready'
  stopPolling()
  refreshScreenshot()
}

const retryCheck = () => confirmLogin()

const cancelSession = async () => {
  stopPolling()
  await closeSessionInternal(false)
}

// ---- ready：截图 ----
const refreshScreenshot = async () => {
  refreshingShot.value = true
  try {
    const s = await elementAPI.getBrowserStatus(browserSessionId.value)
    statusUrl.value = s.url || ''
    if (s.state === 'released' || !s.screenshot_b64) {
      screenshotSrc.value = ''
      if (s.state === 'released') browserReleased.value = true
    } else {
      screenshotSrc.value = `data:image/png;base64,${s.screenshot_b64}`
      if (s.viewport_width) viewportW.value = s.viewport_width
      if (s.viewport_height) viewportH.value = s.viewport_height
    }
  } catch (err) {
    // 404 = 会话消失
    screenshotSrc.value = ''
  } finally {
    refreshingShot.value = false
  }
}

// ---- ready：抓取 ----
const captureNow = async () => {
  capturing.value = true
  try {
    const r = await elementAPI.captureBrowserPage(browserSessionId.value)
    stagingSessionId.value = r.staging_session_id
    await refreshStaging()
    ElMessage.success(`批次 ${r.batch_idx + 1} 抓取完成：+${r.total_count} 元素`)
    refreshScreenshot()
  } catch (err) {
    ElMessage.error('抓取失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    capturing.value = false
  }
}

const refreshStaging = async () => {
  if (!stagingSessionId.value) { stagingState.value = null; return }
  try {
    stagingState.value = await elementAPI.getCaptureState(stagingSessionId.value)
  } catch {
    stagingState.value = null
  }
  loadPages()
}

const loadPages = async () => {
  if (!projectId.value) return
  try {
    pages.value = await elementAPI.listPages(projectId.value)
  } catch {
    pages.value = []
  }
}

// ---- ready：staging 元素操作（沿用 P3 交互） ----
const toggleElement = async (tempId, included) => {
  try {
    await elementAPI.setCaptureElementIncluded(stagingSessionId.value, tempId, included)
    const el = stagingState.value.elements.find((e) => e.temp_id === tempId)
    if (el) el.included = included
    stagingState.value.included_count += included ? 1 : -1
  } catch {
    ElMessage.error('操作失败（会话可能已过期）')
    refreshStaging()
  }
}

const toggleAll = async (included) => {
  try {
    await elementAPI.setCaptureAllIncluded(stagingSessionId.value, included)
    stagingState.value.elements.forEach((e) => (e.included = included))
    stagingState.value.included_count = included ? stagingState.value.total_elements : 0
  } catch {
    ElMessage.error('操作失败')
  }
}

const removeElement = async (tempId) => {
  try {
    await elementAPI.deleteCaptureElement(stagingSessionId.value, tempId)
    await refreshStaging()
  } catch {
    ElMessage.error('删除失败')
  }
}

// ---- ready：点选补抓 ----
const onShotClick = async (event) => {
  if (!pickMode.value || browserReleased.value) return
  const img = event.currentTarget.querySelector('.shot-img')
  if (!img) return
  const rect = img.getBoundingClientRect()
  const x = Math.round(((event.clientX - rect.left) / rect.width) * viewportW.value)
  const y = Math.round(((event.clientY - rect.top) / rect.height) * viewportH.value)
  try {
    pickCard.value = await elementAPI.pickBrowserElement(browserSessionId.value, x, y)
    pickCardVisible.value = true
  } catch (err) {
    if (err.response?.status === 404) {
      ElMessage.warning('该坐标未命中可交互元素，请重试')
    } else {
      ElMessage.error('点选失败: ' + (err.response?.data?.detail || err.message))
    }
  }
}

const addPickedToStaging = async () => {
  if (!pickCard.value) return
  addingPicked.value = true
  try {
    // 确保有 staging 会话：无则先跑一次页面抓取（懒创建）——pick 端点不落 staging，
    // 点选元素直接走 addCaptureBatch 单元素批次
    if (!stagingSessionId.value) {
      const c = await elementAPI.captureBrowserPage(browserSessionId.value)
      stagingSessionId.value = c.staging_session_id
      await refreshStaging()
    }
    const r = await elementAPI.addCaptureBatch(stagingSessionId.value, {
      url: statusUrl.value,
      screenshot_url: '',
      elements: [pickCard.value]
    })
    await refreshStaging()
    pickCardVisible.value = false
    ElMessage.success(`已加入列表（批次 ${r.batch_idx + 1}）`)
    refreshScreenshot()
  } catch (err) {
    ElMessage.error('加入列表失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    addingPicked.value = false
  }
}

// ---- ready：入库 ----
const importSelected = async () => {
  const data = {
    project_id: projectId.value,
    session_id: stagingSessionId.value,
    page_name: pageName.value || undefined,
    page_url: pageUrl.value || (statusUrl.value || undefined),
    page_id: pageMode.value === 'existing' ? pageId.value : undefined
  }
  if (pageMode.value === 'existing' && !data.page_id) {
    ElMessage.warning('请选择已有页面')
    return
  }
  importing.value = true
  try {
    const result = await elementAPI.importFromCaptureSession(data)
    ElMessage.success(`成功入库 ${result.imported_count} 个元素到「${result.page_name}」`)
    stagingSessionId.value = ''
    stagingState.value = null
    pageName.value = ''
    pageUrl.value = ''
    pageId.value = ''
    emit('imported', result)
    ElMessage.info('已入库，可继续抓取或释放页面')
  } catch (err) {
    ElMessage.error('入库失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    importing.value = false
  }
}

// ---- 释放 / 关闭 ----
const releasePage = async () => {
  try {
    await elementAPI.releaseBrowser(browserSessionId.value)
    browserReleased.value = true
    screenshotSrc.value = ''
    ElMessage.success('页面已释放（已抓元素保留），输入新 URL 可继续')
  } catch (err) {
    ElMessage.error('释放失败: ' + (err.response?.data?.detail || err.message))
  }
}

const closeSession = async () => {
  try {
    await ElMessageBox.confirm('关闭会话？浏览器与所有未入库元素将全部清空。', '确认', { type: 'warning' })
  } catch { return }
  await closeSessionInternal(true)
}

const closeSessionInternal = async (confirmMsg) => {
  if (stagingSessionId.value) {
    try { await elementAPI.discardCaptureSession(stagingSessionId.value) } catch { /* 已过期视为成功 */ }
  }
  try { await elementAPI.closeBrowserSession(browserSessionId.value) } catch { /* 已消失视为成功 */ }
  stopPolling()
  phase.value = 'idle'
  browserSessionId.value = ''
  stagingSessionId.value = ''
  stagingState.value = null
  screenshotSrc.value = ''
  browserReleased.value = false
  pickMode.value = false
  url.value = ''
  if (confirmMsg) ElMessage.success('会话已关闭')
  emit('closed')
}

watch(pickMode, (on) => { if (on && !screenshotSrc.value) refreshScreenshot() })
onUnmounted(stopPolling)

defineExpose({ phase, start })
</script>

<style scoped>
.wb-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.wb-url {
  flex: 1;
  font-size: 13px;
  color: var(--mt-text-secondary, #606266);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wb-toolbar-actions {
  display: flex;
  gap: 8px;
}
.login-banner {
  margin-bottom: 12px;
}
.login-banner-body {
  font-size: 13px;
}
.login-actions {
  display: flex;
  gap: 8px;
}
.shot-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.shot-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.shot-container {
  background: #f5f7fa;
  border-radius: 6px;
  min-height: 300px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow: auto;
}
.shot-container.picking {
  cursor: crosshair;
}
.shot-img {
  width: 100%;
  display: block;
}
.no-screenshot {
  color: #909399;
  font-size: 14px;
  padding: 60px 0;
}
.pick-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--mt-text-secondary, #909399);
}
.wb-elements {
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
  padding: 6px;
  margin-bottom: 10px;
}
.wb-element {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  border-radius: 4px;
}
.wb-element:hover {
  background: var(--el-fill-color-light, #f5f7fa);
}
.wb-element.excluded .wb-el-text {
  text-decoration: line-through;
  color: var(--mt-text-secondary, #c0c4cc);
}
.wb-el-text {
  margin: 0 8px;
  font-size: 13px;
}
.wb-import {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.pick-card-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.pick-card-text {
  font-size: 14px;
}
.pick-label {
  font-size: 13px;
  color: var(--mt-text-secondary, #606266);
}
</style>
