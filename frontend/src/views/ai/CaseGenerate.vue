<template>
  <div class="case-generate page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>AI 用例生成</h2>
        <div class="page-subtitle">上传材料 → AI 识别测试点 → 生成用例，全程可查看直播日志</div>
      </div>
    </div>

    <el-card shadow="never" class="steps-card">
      <el-steps :active="currentStep" finish-status="success" align-center>
        <el-step title="选择项目" />
        <el-step title="上传材料" />
        <el-step title="选择规则" />
        <el-step title="AI识别测试点" />
        <el-step title="勾选测试点" />
        <el-step title="生成用例" />
        <el-step title="结果预览" />
      </el-steps>
    </el-card>

    <el-card class="step-content" shadow="never">
      <!-- Step 1: 选择项目 -->
      <div v-if="currentStep === 0" class="step-container">
        <h3>选择项目</h3>
        <el-form label-width="120px">
          <el-form-item label="项目" required>
            <el-select
              v-model="formData.projectId"
              placeholder="请选择项目"
              style="width: 100%"
              @change="onProjectChange"
            >
              <el-option
                v-for="project in projects"
                :key="project.id"
                :label="project.name"
                :value="project.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <div class="step-actions">
          <el-button type="primary" :disabled="!formData.projectId" @click="nextStep">下一步</el-button>
        </div>
      </div>

      <!-- Step 2: 上传 / 输入材料（3 源 + 文本，至少一种，≤10MB） -->
      <div v-if="currentStep === 1" class="step-container">
        <h3>上传 / 输入材料</h3>
        <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
          PRD文档 / 设计方案 / UI原型 三选一（或多选），或直接输入需求文本；至少一种，单文件 ≤ 10MB
        </el-alert>

        <el-row :gutter="16">
          <el-col :span="8">
            <div class="upload-box">
              <div class="upload-label">PRD 文档</div>
              <el-upload
                :auto-upload="false"
                :show-file-list="true"
                :on-change="(f) => handleMaterialChange(f, 'prd')"
                :on-remove="() => clearMaterial('prd')"
                :before-upload="beforeUpload"
                accept=".docx,.pdf,.txt,.md"
                :limit="1"
              >
                <el-button :icon="UploadFilled">选择 PRD</el-button>
              </el-upload>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="upload-box">
              <div class="upload-label">设计方案</div>
              <el-upload
                :auto-upload="false"
                :show-file-list="true"
                :on-change="(f) => handleMaterialChange(f, 'design')"
                :on-remove="() => clearMaterial('design')"
                :before-upload="beforeUpload"
                accept=".docx,.pdf,.txt,.md"
                :limit="1"
              >
                <el-button :icon="UploadFilled">选择设计文档</el-button>
              </el-upload>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="upload-box">
              <div class="upload-label">UI 原型</div>
              <el-upload
                :auto-upload="false"
                :show-file-list="true"
                :on-change="(f) => handleMaterialChange(f, 'prototype')"
                :on-remove="() => clearMaterial('prototype')"
                :before-upload="beforeUpload"
                accept=".png,.jpg,.jpeg,.zip,.html"
                :limit="1"
              >
                <el-button :icon="UploadFilled">选择 UI 原型</el-button>
              </el-upload>
            </div>
          </el-col>
        </el-row>

        <el-form label-width="120px" style="margin-top: 16px">
          <el-form-item label="需求文本">
            <el-input
              v-model="formData.requirementText"
              type="textarea"
              :rows="6"
              placeholder="或直接粘贴需求文本（与上方上传三选一，至少一种）"
            />
          </el-form-item>
        </el-form>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button
            type="primary"
            :loading="uploading"
            :disabled="!hasMaterial"
            @click="prepareContent"
          >
            解析并继续
          </el-button>
        </div>
      </div>

      <!-- Step 3: 选择生成规则（4 开关，automation_thinking 强制开） -->
      <div v-if="currentStep === 2" class="step-container">
        <h3>选择生成规则</h3>
        <el-form label-width="180px">
          <el-form-item label="自动化思维规则">
            <el-switch v-model="rules.automation_thinking" disabled /> 强制开启（禁用观察/验证等软断言）
          </el-form-item>
          <el-form-item label="边界值分析">
            <el-switch v-model="rules.boundary_value" />
          </el-form-item>
          <el-form-item label="场景法覆盖">
            <el-switch v-model="rules.scenario_analysis" />
          </el-form-item>
          <el-form-item label="等价类划分">
            <el-switch v-model="rules.equivalence_partition" />
          </el-form-item>
        </el-form>
        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" @click="nextStep">下一步</el-button>
        </div>
      </div>

      <!-- Step 4: AI识别测试点 + 文字直播 -->
      <div v-if="currentStep === 3" class="step-container">
        <h3>AI 识别测试点</h3>
        <el-button type="primary" :loading="identifying" @click="identifyTestPoints">
          开始 AI 识别
        </el-button>
        <span class="token-info" v-if="sseMessages.length > 0">
          已消耗 {{ tokensUsed }} / 预估 {{ tokensEstimate }}
        </span>

        <div class="live-log" v-if="sseMessages.length > 0 || sseProgress > 0">
          <el-progress :percentage="Math.round(sseProgress * 100)" />
          <div class="log-list">
            <div
              v-for="(msg, idx) in sseMessages"
              :key="idx"
              :class="['log-line', 'type-' + (msg.type || 'system')]"
            >
              [{{ msg.stage || '-' }}] {{ msg.content }}
            </div>
          </div>
        </div>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button
            type="primary"
            :disabled="testPoints.length === 0"
            @click="nextStep"
          >
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 5: 测试点勾选（按 page_name 分组 + 类型筛选） -->
      <div v-if="currentStep === 4" class="step-container">
        <h3>勾选测试点</h3>
        <div class="toolbar">
          <el-select v-model="pointTypeFilter" placeholder="类型筛选" clearable style="width: 160px">
            <el-option label="正常流程" value="正常流程" />
            <el-option label="异常流程" value="异常流程" />
            <el-option label="边界值" value="边界值" />
            <el-option label="等价类" value="等价类" />
            <el-option label="场景法" value="场景法" />
          </el-select>
          <el-button @click="selectAllPoints">全选</el-button>
          <el-button @click="invertSelection">反选</el-button>
          <span class="selected-count">已选 {{ selectedPointIds.length }} / {{ testPoints.length }}</span>
        </div>

        <el-collapse v-model="expandedPages">
          <el-collapse-item
            v-for="(points, pageName) in groupedPoints"
            :key="pageName"
            :title="`${pageName} (${points.length})`"
            :name="pageName"
          >
            <el-table :data="points" border size="small" @selection-change="onPageSelectionChange">
              <el-table-column type="selection" width="45" :selectable="canSelect" />
              <el-table-column prop="name" label="测试点" min-width="200" />
              <el-table-column prop="type_label" label="类型" width="100">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.type_label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
            </el-table>
          </el-collapse-item>
        </el-collapse>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :disabled="selectedPointIds.length === 0" @click="nextStep">
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 6: 生成用例（继续 SSE） -->
      <div v-if="currentStep === 5" class="step-container">
        <h3>生成测试用例</h3>
        <el-form label-width="140px">
          <el-form-item label="幻觉检测策略">
            <el-radio-group v-model="formData.hallucinationStrategy">
              <el-radio value="strict">严格</el-radio>
              <el-radio value="moderate">适中</el-radio>
              <el-radio value="permissive">宽松</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="generating" @click="generateTestCases">
          生成所选用例（{{ selectedPointIds.length }} 个测试点）
        </el-button>

        <div class="live-log" v-if="sseMessages.length > 0 || sseProgress > 0">
          <el-progress :percentage="Math.round(sseProgress * 100)" />
          <div class="log-list">
            <div
              v-for="(msg, idx) in sseMessages"
              :key="idx"
              :class="['log-line', 'type-' + (msg.type || 'system'), msg.stage === 'detect_hallucination' ? 'hallucination' : '']"
            >
              [{{ msg.stage || '-' }}] {{ msg.content }}
            </div>
          </div>
        </div>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :disabled="generatedCases.length === 0" @click="nextStep">
            查看结果
          </el-button>
        </div>
      </div>

      <!-- Step 7: 结果预览 + 幻觉标记 -->
      <div v-if="currentStep === 6" class="step-container">
        <h3>结果预览</h3>
        <div class="toolbar">
          <span>共 {{ generatedCases.length }} 条用例</span>
          <el-button @click="resetWizard">重新开始</el-button>
        </div>
        <el-table :data="generatedCases" border>
          <el-table-column prop="name" label="用例名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="priority" label="优先级" width="80" />
          <el-table-column prop="hallucination_status" label="幻觉标记" width="120">
            <template #default="{ row }">
              <el-tag :type="hallucinationTagType(row.hallucination_status)">
                {{ hallucinationLabel(row.hallucination_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="expected_result" label="预期结果" min-width="220" show-overflow-tooltip />
        </el-table>
        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="success" @click="finish">完成</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { aiCaseAPI } from '@/api/ai-case'
import { projectAPI } from '@/api/project.js'

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB

const currentStep = ref(0)
const projects = ref([])
const uploading = ref(false)
const identifying = ref(false)
const generating = ref(false)

const formData = ref({
  projectId: '',
  requirementText: '',
  hallucinationStrategy: 'moderate'
})

const materials = ref({ prd: null, design: null, prototype: null })
const parsedContent = ref('')

const rules = ref({
  automation_thinking: true,
  boundary_value: true,
  scenario_analysis: true,
  equivalence_partition: true
})

const testPoints = ref([])
const selectedPointIds = ref([])
const pointTypeFilter = ref('')
const expandedPages = ref([])
const generatedCases = ref([])

// SSE 状态
const sseMessages = ref([])
const sseProgress = ref(0)
const tokensUsed = ref(0)
const tokensEstimate = ref(0)
let eventSource = null

const hasMaterial = computed(() =>
  !!(materials.value.prd || materials.value.design || materials.value.prototype || formData.value.requirementText?.trim())
)

const groupedPoints = computed(() => {
  const groups = {}
  for (const p of testPoints.value) {
    if (pointTypeFilter.value && p.type_label !== pointTypeFilter.value) continue
    const key = p.page_name || '未分组'
    if (!groups[key]) groups[key] = []
    groups[key].push(p)
  }
  return groups
})

const nextStep = () => { if (currentStep.value < 6) currentStep.value++ }
const prevStep = () => { if (currentStep.value > 0) currentStep.value-- }

const onProjectChange = () => {
  testPoints.value = []
  generatedCases.value = []
  selectedPointIds.value = []
}

const beforeUpload = (file) => {
  if (file.size > MAX_FILE_SIZE) {
    ElMessage.error('文件大小不能超过 10MB')
    return false
  }
  return true
}

const handleMaterialChange = (file, kind) => {
  if (!beforeUpload(file.raw)) return
  materials.value[kind] = file.raw
}

const clearMaterial = (kind) => {
  materials.value[kind] = null
}

// Step 2 -> 3: 解析材料为文本（前端仅做轻量拼接，真正解析在后端 parse_document_task；
// 此处把上传文件名 + 需求文本聚合为 doc_content，实际文件流交给后端识别任务时附带）
const prepareContent = async () => {
  uploading.value = true
  try {
    const parts = []
    if (materials.value.prd) parts.push(`[PRD文档] ${materials.value.prd.name}`)
    if (materials.value.design) parts.push(`[设计方案] ${materials.value.design.name}`)
    if (materials.value.prototype) parts.push(`[UI原型] ${materials.value.prototype.name}`)
    if (formData.value.requirementText?.trim()) parts.push(`[需求文本]\n${formData.value.requirementText}`)
    parsedContent.value = parts.join('\n\n')
    ElMessage.success('材料已准备')
    nextStep()
  } finally {
    uploading.value = false
  }
}

// Step 4: AI 识别测试点（SSE 文字直播）
const identifyTestPoints = async () => {
  identifying.value = true
  sseMessages.value = []
  sseProgress.value = 0
  tokensUsed.value = 0
  tokensEstimate.value = 0

  try {
    const res = await aiCaseAPI.identifyTestPoints(
      formData.value.projectId,
      parsedContent.value,
      { ...rules.value },
      [],
      []
    )
    const data = res.data || res
    const sessionId = data.session_id || (data.data && data.data.session_id)

    // 订阅 SSE 文字直播
    if (sessionId) {
      eventSource = aiCaseAPI.subscribeSSE(sessionId, onSSEMessage, onSSEError)
    }

    // 轮询/拉取测试点列表（任务异步，这里用 getTestPoints 拉取已识别的点）
    setTimeout(async () => {
      try {
        const tpRes = await aiCaseAPI.getTestPoints(formData.value.projectId, 0, 500)
        const tpData = tpRes.data || tpRes
        testPoints.value = tpData.items || tpData || []
        expandedPages.value = [...new Set(testPoints.value.map(p => p.page_name || '未分组'))]
        ElMessage.success(`识别到 ${testPoints.value.length} 个测试点`)
      } catch (e) {
        ElMessage.warning('测试点识别中，请稍后查看')
      } finally {
        identifying.value = false
        sseProgress.value = 1
      }
    }, 2500)
  } catch (error) {
    ElMessage.error('测试点识别失败: ' + (error.message || error))
    identifying.value = false
  }
}

const onSSEMessage = (msg) => {
  sseMessages.value.push(msg)
  if (typeof msg.progress === 'number') sseProgress.value = msg.progress
  if (typeof msg.tokens_used === 'number') tokensUsed.value = msg.tokens_used
  if (typeof msg.tokens_estimated_total === 'number') tokensEstimate.value = msg.tokens_estimated_total
}

const onSSEError = () => {
  // 连续 3 次重连失败（api 层已 close），给出明确提示并复位加载态
  ElMessage.error('实时日志连接失败（已重试 3 次），任务仍在后台执行，结果稍后可在列表查看')
  identifying.value = false
  generating.value = false
}

// Step 5: 测试点勾选
const canSelect = (row) => {
  if (pointTypeFilter.value && row.type_label !== pointTypeFilter.value) return false
  return true
}

const onPageSelectionChange = (selection) => {
  const ids = selection.map(p => p.id)
  // merge into selectedPointIds (simple union for this page)
  selectedPointIds.value = Array.from(new Set([...selectedPointIds.value, ...ids]))
}

const selectAllPoints = () => {
  selectedPointIds.value = testPoints.value.map(p => p.id)
}

const invertSelection = () => {
  const all = new Set(testPoints.value.map(p => p.id))
  selectedPointIds.value = testPoints.value
    .filter(p => !selectedPointIds.value.includes(p.id))
    .map(p => p.id)
}

// Step 6: 生成用例
const generateTestCases = async () => {
  generating.value = true
  sseMessages.value = []
  sseProgress.value = 0

  try {
    const res = await aiCaseAPI.generateTestCases(
      formData.value.projectId,
      selectedPointIds.value,
      'comprehensive',
      formData.value.hallucinationStrategy !== 'permissive'
    )
    const data = res.data || res
    const sessionId = data.session_id || (data.data && data.data.session_id)
    if (sessionId) {
      eventSource = aiCaseAPI.subscribeSSE(sessionId, onSSEMessage, onSSEError)
    }
    // 拉取生成结果
    setTimeout(async () => {
      try {
        const tcRes = await aiCaseAPI.getTestCases(formData.value.projectId, 0, 500)
        const tcData = tcRes.data || tcRes
        generatedCases.value = tcData.items || tcData || []
        ElMessage.success(`生成完成，共 ${generatedCases.value.length} 条用例`)
      } catch (e) {
        ElMessage.warning('用例生成中，请稍后查看')
      } finally {
        generating.value = false
        sseProgress.value = 1
      }
    }, 3000)
  } catch (error) {
    ElMessage.error('用例生成失败: ' + (error.message || error))
    generating.value = false
  }
}

const hallucinationLabel = (s) => ({ normal: '正常', suspected: '疑似幻觉', confirmed: '已确认', unknown: '未知' }[s] || s || '正常')
const hallucinationTagType = (s) => ({ suspected: 'warning', confirmed: 'danger', unknown: 'info' }[s] || 'success')

const resetWizard = () => {
  currentStep.value = 0
  formData.value = { projectId: '', requirementText: '', hallucinationStrategy: 'moderate' }
  materials.value = { prd: null, design: null, prototype: null }
  parsedContent.value = ''
  testPoints.value = []
  generatedCases.value = []
  selectedPointIds.value = []
  sseMessages.value = []
  sseProgress.value = 0
  tokensUsed.value = 0
  tokensEstimate.value = 0
}

const finish = () => {
  ElMessage.success('AI 用例生成流程完成')
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = res.items || res || []
  } catch (error) {
    projects.value = []
  }
}

onMounted(() => {
  loadProjects()
})

onUnmounted(() => {
  if (eventSource) eventSource.close()
})
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}

.steps-card {
  margin-bottom: 16px;
}

.step-content {
  margin-top: 0;
  min-height: 500px;
}

.step-container {
  padding: 30px;
}

.step-container h3 {
  margin-bottom: 20px;
  color: var(--mt-text);
  font-size: 18px;
  font-weight: 600;
}

.step-actions {
  margin-top: 30px;
  text-align: center;
  padding-top: 20px;
  border-top: 1px solid var(--mt-border);
}

.step-actions .el-button {
  min-width: 120px;
}

.upload-box {
  border: 1px dashed var(--mt-border);
  border-radius: var(--mt-radius-sm);
  padding: 16px;
  text-align: center;
}

.upload-label {
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--mt-text-secondary);
}

.token-info {
  margin-left: 16px;
  color: var(--mt-text-secondary);
  font-size: 13px;
}

.live-log {
  margin-top: 20px;
}

.log-list {
  margin-top: 12px;
  max-height: 240px;
  overflow-y: auto;
  background: var(--mt-bg);
  border: 1px solid var(--mt-border);
  border-radius: var(--mt-radius-sm);
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.6;
}

.log-line.type-ai {
  color: var(--mt-primary);
}

.log-line.type-error {
  color: var(--mt-danger);
}

.log-line.hallucination {
  color: var(--mt-warning);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.selected-count {
  color: var(--mt-text-secondary);
  font-size: 13px;
}
</style>
