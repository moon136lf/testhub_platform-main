<template>
  <div class="element-library page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>元素库管理</h2>
        <div class="page-subtitle">从被测应用抓取页面元素，供用例转脚本使用</div>
      </div>
    </div>

    <el-card shadow="never">

      <!-- 抓取模式 tab（对齐原型：一次性 / 会话式） -->
      <el-tabs v-model="activeTab" class="fetch-tabs">
        <el-tab-pane label="一次性抓取" name="oneshot" />
        <el-tab-pane label="会话式抓取" name="session" />
      </el-tabs>

      <!-- 一次性抓取 tab 内容 -->
      <div v-show="activeTab === 'oneshot'">
        <div class="fetch-entry">
          <el-button type="primary" :icon="Search" :loading="fetching" @click="openOneShotDialog">
            抓取元素
          </el-button>
        </div>

        <FetchDialog
          v-model="fetchDialogVisible"
          :projects="projects"
          :loading="fetching"
          @start="handleFetchStart"
        />

        <!-- 一次性抓取直播 + 结果区（原有内容整体保留在该 tab 内） -->
        <div v-if="liveMessages.length > 0" class="live-feed">
          <el-alert title="抓取进度直播" type="info" :closable="false" style="margin-bottom: 10px">
            <div v-for="(msg, index) in liveMessages" :key="index" class="live-message" :class="{ 'is-error': msg.type === 'error' }">
              <span class="live-time">{{ msg.timestamp }}</span>
              <el-tag :type="msgTypeTag(msg.type)" size="small" effect="plain">{{ msg.type }}</el-tag>
              <span class="live-text">{{ msg.content }}</span>
            </div>
          </el-alert>
          <el-progress
            :percentage="Math.round(progress * 100)"
            :status="progress >= 1 ? 'success' : undefined"
          />
        </div>

        <div v-if="elements.length > 0" class="elements-result">
          <el-alert title="抓取结果" type="success" :closable="false" style="margin-bottom: 20px">
            共识别 {{ elements.length }} 个有效元素（{{ filterDescription }}），已勾选 {{ selectedElementIds.length }} 个
          </el-alert>

          <el-row :gutter="20">
            <el-col :span="16">
              <el-card>
                <template #header><span>页面截图</span></template>
                <div class="screenshot-container">
                  <ElementHighlight
                    v-if="screenshotUrl"
                    :screenshot-url="screenshotUrl"
                    :elements="elements"
                    :selected-ids="selectedElementIds"
                    :hover-id="hoverId"
                    @pick="togglePick"
                    @card-hover="hoverId = $event || ''"
                  />
                  <div v-else class="no-screenshot">暂无截图</div>
                </div>
              </el-card>
            </el-col>

            <el-col :span="8">
              <el-card>
                <template #header>
                  <span>元素列表（含定位策略）</span>
                </template>
                <div class="element-list">
                  <div class="element-list-toolbar">
                    <el-checkbox v-model="selectAll" @change="handleSelectAll">全选</el-checkbox>
                    <el-button type="primary" size="small" :disabled="selectedElementIds.length === 0" @click="showImportDialog">
                      一键入库 ({{ selectedElementIds.length }})
                    </el-button>
                  </div>
                  <el-checkbox-group v-model="selectedElementIds">
                    <div
                      v-for="element in elements"
                      :key="element.temp_id"
                      class="element-item"
                      :data-eid="element.temp_id"
                      @mouseenter="hoverId = element.temp_id"
                      @mouseleave="hoverId = ''"
                    >
                      <el-checkbox :label="element.temp_id">
                        <div class="element-info">
                          <el-tag :type="getElementTypeColor(element.element_type)" size="small">
                            {{ element.element_type }}
                          </el-tag>
                          <el-input
                            v-model="element.element_name"
                            size="small"
                            style="width: 130px"
                            :placeholder="defaultAlias(element)"
                            @click.stop
                          />
                          <el-tooltip :content="formatStrategies(element.locator_strategies)" placement="top">
                            <el-tag size="small" type="info" effect="plain">
                              {{ strategyCount(element.locator_strategies) }} 策略
                            </el-tag>
                          </el-tooltip>
                        </div>
                      </el-checkbox>
                    </div>
                  </el-checkbox-group>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>

        <el-empty v-if="elements.length === 0 && liveMessages.length === 0" description="请先抓取页面元素" />
      </div>

      <!-- 会话式抓取 tab 内容：工作台自持状态机（idle→登录→抓取→入库） -->
      <div v-show="activeTab === 'session'">
        <CaptureWorkbench
          :projects="projects"
          :default-project-id="fetchForm.project_id"
          @imported="handleCaptureImported"
          @closed="handleCaptureClosed"
        />
      </div>

    </el-card>

    <!-- 入库弹窗：已有页面下拉 + 别名编辑 + 策略预览 -->
    <el-dialog v-model="importDialogVisible" title="入库确认" width="900px">
      <el-form :model="importForm" label-width="120px">
        <el-form-item label="页面归属">
          <el-select v-model="importForm.pageMode" placeholder="选择页面模式" style="width: 100%">
            <el-option label="新建页面" value="new" />
            <el-option label="选择已有页面" value="existing" :disabled="pages.length === 0" />
          </el-select>
        </el-form-item>

        <template v-if="importForm.pageMode === 'new'">
          <el-form-item label="页面名称">
            <el-input v-model="importForm.page_name" placeholder="如：登录页" />
          </el-form-item>
          <el-form-item label="页面URL">
            <el-input v-model="importForm.page_url" placeholder="如：/login" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="选择页面">
            <el-select v-model="importForm.page_id" placeholder="选择已有页面" style="width: 100%">
              <el-option
                v-for="page in pages"
                :key="page.id"
                :label="`${page.page_name} (${page.page_url})`"
                :value="page.id"
              />
            </el-select>
          </el-form-item>
        </template>

        <el-divider content-position="left">元素别名编辑与策略预览</el-divider>

        <el-table :data="selectedElementsData" border max-height="300">
          <el-table-column prop="temp_id" label="临时ID" width="120" show-overflow-tooltip />
          <el-table-column label="元素别名" width="180">
            <template #default="{ row }">
              <el-input v-model="row.element_name" size="small" placeholder="可编辑" />
            </template>
          </el-table-column>
          <el-table-column prop="element_type" label="类型" width="90" />
          <el-table-column label="定位策略预览">
            <template #default="{ row }">
              <el-tag
                v-for="(s, i) in (row.locator_strategies?.strategies || []).slice(0, 3)"
                :key="i"
                size="small"
                :type="s.score >= 100 ? 'success' : 'info'"
                effect="plain"
                style="margin-right: 4px"
              >
                {{ s.type }}: {{ s.value.substring(0, 20) }}{{ s.value.length > 20 ? '...' : '' }} ({{ s.score }})
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-form>

      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">确认入库</el-button>
      </template>
    </el-dialog>

    <!-- 已入库元素（P3 工作台 T4c：页面树 + 元素列表） -->
    <el-card shadow="never" class="stored-card">
      <template #header>
        <div class="stored-header">
          <span>已入库元素</span>
          <div class="stored-toolbar">
            <el-select v-model="storedRange" style="width: 110px" @change="filterStoredElements">
              <el-option label="近 7 日" value="7d" />
              <el-option label="近 30 日" value="30d" />
              <el-option label="全部" value="all" />
            </el-select>
            <el-button @click="loadPageTree">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="stored-layout">
        <div class="stored-tree">
          <el-tree
            :data="pageTree"
            node-key="id"
            :props="{ label: 'page_name', children: 'children' }"
            highlight-current
            @node-click="handleTreeNodeClick"
          >
            <template #default="{ data }">
              <span class="tree-node">
                {{ data.page_name }}
                <el-badge :value="data.element_count" type="info" class="tree-badge" />
              </span>
            </template>
          </el-tree>
        </div>

        <div class="stored-table">
          <el-table :data="filteredStoredElements" border max-height="480" v-loading="storedLoading">
            <el-table-column type="index" label="序号" width="70" align="center" />
            <el-table-column prop="element_name" label="别名" min-width="140" show-overflow-tooltip />
            <el-table-column prop="element_type" label="类型" width="90" />
            <el-table-column label="定位策略数" width="100">
              <template #default="{ row }">{{ strategyCount(row.locator_strategies) }}</template>
            </el-table-column>
            <el-table-column prop="confidence" label="置信度" width="80" />
            <el-table-column label="入库时间" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button type="danger" link size="small" @click="handleDeleteStored(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!selectedPageId" class="stored-empty">请在左侧选择页面</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { elementAPI } from '@/api/element'
import { projectAPI } from '@/api/project'
import FetchDialog from '@/components/element/FetchDialog.vue'
import CaptureWorkbench from '@/components/element/CaptureWorkbench.vue'
import ElementHighlight from '@/components/element/ElementHighlight.vue'

const hoverId = ref('')

// 点截图上的高亮框 → 切换勾选 + 右侧卡片滚动可见
const togglePick = async (tempId) => {
  const i = selectedElementIds.value.indexOf(tempId)
  if (i >= 0) {
    selectedElementIds.value.splice(i, 1)
  } else {
    selectedElementIds.value.push(tempId)
  }
  await nextTick()
  const el = document.querySelector(`[data-eid="${tempId}"]`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

const fetching = ref(false)
const fetchDialogVisible = ref(false)
const importing = ref(false)
const elements = ref([])
const selectedElementIds = ref([])
const screenshotUrl = ref('')
const importDialogVisible = ref(false)
const liveMessages = ref([])
const progress = ref(0)
const projects = ref([])
const pages = ref([])
let sseConnection = null

const fetchForm = ref({
  project_id: '',
  url: '',
  username: '',
  password: '',
  text_filter: '',
  type_filter: '',
  debug_mode: false,
  include_text: false
})

// ---- P3 会话式抓取（工作台内部自持状态机，本页只做事件响应） ----
const activeTab = ref('oneshot')

const openOneShotDialog = () => {
  fetchDialogVisible.value = true
}

const handleFetchStart = async (params) => {
  fetchForm.value = { ...fetchForm.value, ...params }
  fetchDialogVisible.value = false

  if (activeTab.value === 'session') {
    ElMessage.info('请在会话式工作台内输入 URL 开始抓取')
    return
  }
  // 一次性抓取（旧路径）
  handleFetch()
}

const handleCaptureImported = async (result) => {
  ElMessage.success(`已入库 ${result.imported_count} 个元素`)
  await loadPageTree()
}

const handleCaptureClosed = () => {
  // 工作台已自行清空
}

const importForm = ref({
  pageMode: 'new',
  page_id: '',
  page_name: '',
  page_url: ''
})

const selectAll = computed({
  get: () =>
    selectedElementIds.value.length === elements.value.length &&
    elements.value.length > 0,
  set: (val) => {
    selectedElementIds.value = val ? elements.value.map((e) => e.temp_id) : []
  }
})

const selectedElementsData = computed(() =>
  elements.value.filter((e) => selectedElementIds.value.includes(e.temp_id))
)

const filterDescription = computed(() => {
  const form = fetchForm.value
  if (form.debug_mode) return '调试模式'
  const parts = []
  if (form.type_filter) parts.push(`类型: ${form.type_filter}`)
  if (form.text_filter) parts.push(`文本: ${form.text_filter}`)
  return parts.length > 0 ? parts.join('、') : '未过滤'
})

// 抓取元素
const handleFetch = async () => {
  if (!fetchForm.value.project_id) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!fetchForm.value.url) {
    ElMessage.warning('请输入页面URL')
    return
  }

  fetching.value = true
  liveMessages.value = []
  progress.value = 0
  elements.value = []
  selectedElementIds.value = []
  screenshotUrl.value = ''

  try {
    const response = await elementAPI.fetchElements(fetchForm.value)
    const { session_id, sse_url } = response.data || response

    // SSE 直播订阅
    sseConnection = elementAPI.createSSEConnection(session_id)

    sseConnection.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        liveMessages.value.push({
          timestamp: new Date(data.timestamp).toLocaleTimeString('zh-CN'),
          content: data.content,
          type: data.type
        })

        progress.value = data.progress || 0

        // 完成消息（type=success, progress=1.0）：加载元素结果
        if (data.type === 'success' && data.progress >= 1.0 && data.data?.elements) {
          elements.value = data.data.elements
          assignDefaultAliases()
          const raw = data.data.screenshot_url || ''
        // MinIO bucket 非公开, 直链 403 — 走后端代理
        const m = String(raw).match(/\/moontest\/(.+)$/)
        screenshotUrl.value = m ? `/api/v1/elements/screenshot?key=${encodeURIComponent(m[1])}` : raw
          fetching.value = false
          ElMessage.success(`元素抓取完成，共 ${elements.value.length} 个`)
          sseConnection?.close()
        }

        // 错误消息
        if (data.type === 'error') {
          ElMessage.error(data.content || '抓取失败')
          fetching.value = false
          sseConnection?.close()
        }
      } catch (err) {
        console.error('Failed to parse SSE message:', err)
      }
    }

    sseConnection.onerror = () => {
      sseConnection?.close()
      fetching.value = false
    }
  } catch (error) {
    ElMessage.error('抓取失败: ' + (error.response?.data?.detail || error.message))
    fetching.value = false
  }
}

const handleSelectAll = (val) => {
  selectedElementIds.value = val ? elements.value.map((e) => e.temp_id) : []
}

const getElementTypeColor = (type) => {
  const colorMap = {
    button: 'primary',
    input: 'success',
    link: 'warning',
    select: 'info',
    textarea: 'info',
    other: 'default'
  }
  return colorMap[type] || 'default'
}

const msgTypeTag = (type) => {
  const map = { system: 'info', ai: 'primary', success: 'success', error: 'danger', cost: 'warning' }
  return map[type] || 'info'
}

// 别名默认值：element_text > placeholder > 类型中文+序号（按类型计序，抓取完成时生成）
const TYPE_CN = { button: '按钮', input: '输入框', select: '下拉框', link: '链接', textarea: '文本域',
  span: '文本', p: '文本', h1: '标题', h2: '标题', h3: '标题', label: '标签', td: '单元格', th: '表头' }
const defaultAlias = (element) => {
  if (element.element_name) return element.element_name
  const hint = element.semantic_info?.placeholder
  if (hint) return hint
  const cn = TYPE_CN[element.element_type] || '元素'
  return cn
}

// 抓取完成后为每个元素生成默认中文别名（可编辑，随入库带入）
const assignDefaultAliases = () => {
  const counters = {}
  elements.value.forEach((el) => {
    if (el.element_name) return
    const hint = el.semantic_info?.placeholder
    if (hint && !el.element_text) {
      el.element_name = hint
      return
    }
    if (el.element_text) {
      el.element_name = el.element_text
      return
    }
    const cn = TYPE_CN[el.element_type] || '元素'
    counters[cn] = (counters[cn] || 0) + 1
    el.element_name = `${cn}${counters[cn]}`
  })
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return (iso || '').replace('T', ' ').slice(0, 19)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const strategyCount = (locatorStrategies) => {
  return locatorStrategies?.strategies?.length || 0
}

const formatStrategies = (locatorStrategies) => {
  const list = locatorStrategies?.strategies || []
  return list.map((s) => `${s.type}: ${s.value} (score=${s.score})`).join('\n')
}

// 入库弹窗
const showImportDialog = async () => {
  if (selectedElementIds.value.length === 0) {
    ElMessage.warning('请先选择要入库的元素')
    return
  }

  // 加载已有页面供下拉
  if (fetchForm.value.project_id) {
    try {
      const res = await elementAPI.listPages(fetchForm.value.project_id)
      pages.value = res.data || res || []
    } catch (err) {
      console.error('Failed to load pages:', err)
      pages.value = []
    }
  }

  importForm.value = {
    pageMode: 'new',
    page_id: '',
    page_name: '',
    page_url: fetchForm.value.url
  }
  importDialogVisible.value = true
}

// 确认入库
const confirmImport = async () => {
  if (importForm.value.pageMode === 'new') {
    if (!importForm.value.page_name || !importForm.value.page_url) {
      ElMessage.warning('请填写页面名称和URL')
      return
    }
  } else {
    if (!importForm.value.page_id) {
      ElMessage.warning('请选择已有页面')
      return
    }
  }

  importing.value = true
  try {
    // 构造请求数据（对接 Task 15 的 /import 端点契约）
    const requestData = {
      project_id: fetchForm.value.project_id,
      selected_element_ids: selectedElementIds.value,
      elements_data: selectedElementsData.value.map((e) => ({
        ...e,
        element_name: e.element_name || e.element_text || e.temp_id
      })),
      screenshot_url: screenshotUrl.value
    }

    if (importForm.value.pageMode === 'new') {
      requestData.page_name = importForm.value.page_name
      requestData.page_url = importForm.value.page_url
    } else {
      requestData.page_id = importForm.value.page_id
    }

    const result = await elementAPI.importElements(requestData)
    const dupNote = result.failed_count > 0 ? `，${result.failed_count} 条重复未入库` : ''
    ElMessage.success(`成功入库 ${result.imported_count} 个元素到 ${result.page_name || '页面'}${dupNote}`)
    await loadPageTree()

    importDialogVisible.value = false
    elements.value = []
    selectedElementIds.value = []
    screenshotUrl.value = ''
    liveMessages.value = []
  } catch (error) {
    ElMessage.error('入库失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  try {
    const projectList = await projectAPI.list()
    projects.value = projectList.items || projectList || []
    if (projects.value.length > 0) {
      fetchForm.value.project_id = projects.value[0].id
      await loadPageTree()
    }
  } catch (error) {
    console.error('Failed to load projects:', error)
  }
})

onUnmounted(() => {
  sseConnection?.close()
})

// ---- P3 工作台 T4c：已入库元素列表区（页面树 + 表格 + 近 N 日筛选） ----
const pageTree = ref([])
const selectedPageId = ref('')
const storedElements = ref([])
const storedRange = ref('7d')
const storedLoading = ref(false)

const loadPageTree = async () => {
  const projectId = fetchForm.value.project_id
  if (!projectId) return
  try {
    const res = await elementAPI.getPageTree(projectId)
    pageTree.value = res.data || res || []
  } catch (err) {
    console.error('Failed to load page tree:', err)
    pageTree.value = []
  }
}

const handleTreeNodeClick = async (node) => {
  selectedPageId.value = node.id
  storedLoading.value = true
  try {
    const res = await elementAPI.getPageElements(node.id)
    storedElements.value = res.data || res || []
  } catch (err) {
    console.error('Failed to load page elements:', err)
    storedElements.value = []
  } finally {
    storedLoading.value = false
  }
}

const filteredStoredElements = computed(() => {
  if (storedRange.value === 'all') return storedElements.value
  const days = storedRange.value === '7d' ? 7 : 30
  const cutoff = Date.now() - days * 24 * 3600 * 1000
  return storedElements.value.filter(
    (e) => e.created_at && new Date(e.created_at).getTime() >= cutoff
  )
})

const filterStoredElements = () => {
  // 前端过滤为 computed，此处仅触发响应式更新（保留 hook 便于后续改后端参数）
}

const handleDeleteStored = async (row) => {
  try {
    await elementAPI.deleteElement(row.id)
    ElMessage.success('已删除')
    await handleTreeNodeClick({ id: selectedPageId.value })
    await loadPageTree()
  } catch (err) {
    ElMessage.error('删除失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 工作台入库成功后刷新树
const refreshAfterImport = async () => {
  await loadPageTree()
}

onMounted(() => {
  // onMounted 既有逻辑之后追加加载页面树
})
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}

.fetch-entry {
  margin-bottom: 20px;
}

.live-feed {
  margin: 20px 0;
}

.live-message {
  padding: 4px 0;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-time {
  color: #909399;
  font-family: monospace;
}

.live-text {
  color: #303133;
}

.live-message.is-error .live-text {
  color: var(--el-color-danger, #EF4444);
  font-weight: 600;
}

.elements-result {
  margin-top: 20px;
}

.screenshot-container {
  width: 100%;
  min-height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  border-radius: 4px;
}

.screenshot {
  max-width: 100%;
  border-radius: 4px;
}

.no-screenshot {
  color: #909399;
  font-size: 14px;
}

.element-list-toolbar {
  position: sticky;
  top: 0;
  background: #fff;
  padding: 8px 12px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 40px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5);
}

.element-list {
  max-height: 400px;
  overflow-y: auto;
}

.element-list > .el-button {
  position: sticky;
  bottom: 0;
  z-index: 1;
  margin-top: 8px;
}

.element-item {
  padding: 12px;
  border-bottom: 1px solid #ebeef5;
}

.element-item:last-child {
  border-bottom: none;
}

.element-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.element-text {
  flex: 1;
}

/* 已入库元素列表区 */
.stored-card {
  margin-top: 20px;
}

.stored-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stored-toolbar {
  display: flex;
  gap: 8px;
}

.stored-layout {
  display: flex;
  gap: 16px;
}

.stored-tree {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  padding-right: 12px;
}

.tree-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.stored-table {
  flex: 1;
  min-width: 0;
}

.stored-empty {
  text-align: center;
  color: #909399;
  padding: 20px 0;
}
</style>
