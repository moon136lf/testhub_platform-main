<template>
  <div class="element-library">
    <el-card>
      <template #header>
        <span>元素库管理</span>
      </template>

      <!-- 抓取表单 -->
      <el-form :inline="true" :model="fetchForm" class="fetch-form">
        <el-form-item label="项目">
          <el-select v-model="fetchForm.project_id" placeholder="选择项目" style="width: 200px">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="页面URL">
          <el-input v-model="fetchForm.url" placeholder="https://example.com/login" style="width: 300px" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="fetchForm.username" placeholder="留空则跳过登录" style="width: 150px" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="fetchForm.password" type="password" placeholder="留空则跳过登录" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" :loading="fetching" @click="handleFetch">
            抓取元素
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider />

      <!-- 文字直播区 + 进度条 -->
      <div v-if="liveMessages.length > 0" class="live-feed">
        <el-alert title="抓取进度直播" type="info" :closable="false" style="margin-bottom: 10px">
          <div v-for="(msg, index) in liveMessages" :key="index" class="live-message">
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

      <!-- 抓取结果：截图 + 元素列表 -->
      <div v-if="elements.length > 0" class="elements-result">
        <el-alert title="抓取结果" type="success" :closable="false" style="margin-bottom: 20px">
          共抓取 {{ elements.length }} 个有效元素，已勾选 {{ selectedElementIds.length }} 个
        </el-alert>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-card>
              <template #header><span>页面截图</span></template>
              <div class="screenshot-container">
                <img v-if="screenshotUrl" :src="screenshotUrl" alt="页面截图" class="screenshot" />
                <div v-else class="no-screenshot">暂无截图</div>
              </div>
            </el-card>
          </el-col>

          <el-col :span="12">
            <el-card>
              <template #header>
                <div class="element-list-header">
                  <span>元素列表（含定位策略）</span>
                  <div>
                    <el-checkbox v-model="selectAll" @change="handleSelectAll">全选</el-checkbox>
                    <el-button type="primary" size="small" @click="showImportDialog">
                      一键入库 ({{ selectedElementIds.length }})
                    </el-button>
                  </div>
                </div>
              </template>
              <div class="element-list">
                <el-checkbox-group v-model="selectedElementIds">
                  <div v-for="element in elements" :key="element.temp_id" class="element-item">
                    <el-checkbox :label="element.temp_id">
                      <div class="element-info">
                        <el-tag :type="getElementTypeColor(element.element_type)" size="small">
                          {{ element.element_type }}
                        </el-tag>
                        <span class="element-text">{{ element.element_text || element.temp_id }}</span>
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

      <el-empty v-else description="请先抓取页面元素" />
    </el-card>

    <!-- 入库弹窗：已有页面下拉 + 别名编辑 + 策略预览 -->
    <el-dialog v-model="importDialogVisible" title="入库确认" width="700px">
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { elementAPI } from '@/api/element'
import { projectAPI } from '@/api/project'

const fetching = ref(false)
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
  password: ''
})

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
          screenshotUrl.value = data.data.screenshot_url || ''
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
    ElMessage.success(`成功入库 ${result.imported_count} 个元素到 ${result.page_name || '页面'}`)

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
    }
  } catch (error) {
    console.error('Failed to load projects:', error)
  }
})

onUnmounted(() => {
  sseConnection?.close()
})
</script>

<style scoped>
.element-library {
  padding: 20px;
}

.fetch-form {
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
  max-height: 600px;
  border-radius: 4px;
}

.no-screenshot {
  color: #909399;
  font-size: 14px;
}

.element-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.element-list {
  max-height: 500px;
  overflow-y: auto;
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
</style>
