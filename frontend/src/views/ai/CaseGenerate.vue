<template>
  <div class="case-generate">
    <el-card>
      <el-steps :active="currentStep" finish-status="success" align-center>
        <el-step title="选择项目" />
        <el-step title="上传PRD" />
        <el-step title="知识库检索" />
        <el-step title="识别测试点" />
        <el-step title="编辑测试点" />
        <el-step title="生成用例" />
        <el-step title="查看用例" />
      </el-steps>
    </el-card>

    <el-card class="step-content">
      <!-- Step 1: 选择项目 -->
      <div v-if="currentStep === 0" class="step-container">
        <h3>选择项目</h3>
        <el-form :model="formData" label-width="120px">
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
          <el-button type="primary" :disabled="!formData.projectId" @click="nextStep">
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 2: 上传PRD -->
      <div v-if="currentStep === 1" class="step-container">
        <h3>上传PRD文档</h3>
        <el-upload
          class="upload-demo"
          drag
          :auto-upload="false"
          :on-change="handleFileChange"
          :file-list="fileList"
          accept=".docx,.pdf,.txt,.md"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            将文件拖到此处，或<em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持 docx/pdf/txt/md 格式，文件大小不超过 10MB
            </div>
          </template>
        </el-upload>
        <div v-if="uploadProgress > 0" class="upload-progress">
          <el-progress :percentage="uploadProgress" />
        </div>
        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="uploadDocument">
            上传并继续
          </el-button>
        </div>
      </div>

      <!-- Step 3: 知识库检索 -->
      <div v-if="currentStep === 2" class="step-container">
        <h3>知识库检索</h3>
        <el-form :model="formData" label-width="120px">
          <el-form-item label="检索查询">
            <el-input
              v-model="formData.knowledgeQuery"
              type="textarea"
              :rows="4"
              placeholder="输入查询内容，从知识库中检索相关文档"
            />
          </el-form-item>
          <el-form-item label="返回数量">
            <el-input-number v-model="formData.topK" :min="1" :max="50" />
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="searching" @click="searchKnowledge">
          检索知识库
        </el-button>

        <div v-if="knowledgeResults.length > 0" class="knowledge-results">
          <h4>检索结果 ({{ knowledgeResults.length }})</h4>
          <el-table :data="knowledgeResults" border>
            <el-table-column type="selection" width="55" />
            <el-table-column prop="doc_name" label="文档名称" width="200" />
            <el-table-column prop="chunk_text" label="内容片段" show-overflow-tooltip />
            <el-table-column prop="similarity" label="相似度" width="100">
              <template #default="scope">
                {{ (scope.row.similarity * 100).toFixed(2) }}%
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" @click="nextStep">
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 4: 识别测试点 -->
      <div v-if="currentStep === 3" class="step-container">
        <h3>AI识别测试点</h3>
        <el-form :model="formData" label-width="120px">
          <el-form-item label="PRD内容">
            <el-input
              v-model="formData.prdContent"
              type="textarea"
              :rows="6"
              placeholder="PRD文档内容（已自动提取）"
              readonly
            />
          </el-form-item>
          <el-form-item label="选择规则">
            <el-select
              v-model="formData.selectedRules"
              multiple
              placeholder="选择测试规则"
              style="width: 100%"
            >
              <el-option
                v-for="rule in rules"
                :key="rule.id"
                :label="rule.name"
                :value="rule.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="identifying" @click="identifyTestPoints">
          AI识别测试点
        </el-button>

        <div v-if="testPoints.length > 0" class="test-points-preview">
          <h4>识别的测试点 ({{ testPoints.length }})</h4>
          <el-table :data="testPoints" border>
            <el-table-column prop="point_name" label="测试点名称" />
            <el-table-column prop="point_desc" label="描述" show-overflow-tooltip />
            <el-table-column prop="test_type" label="类型" width="100" />
          </el-table>
        </div>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :disabled="testPoints.length === 0" @click="nextStep">
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 5: 编辑测试点 -->
      <div v-if="currentStep === 4" class="step-container">
        <h3>编辑测试点</h3>
        <div class="table-toolbar">
          <el-button type="primary" :icon="Plus" @click="addTestPoint">添加测试点</el-button>
          <el-button type="danger" :icon="Delete" :disabled="selectedPoints.length === 0" @click="deleteSelectedPoints">
            删除选中
          </el-button>
        </div>
        <el-table
          :data="testPoints"
          border
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="55" />
          <el-table-column prop="point_name" label="测试点名称" width="200">
            <template #default="scope">
              <el-input v-model="scope.row.point_name" size="small" />
            </template>
          </el-table-column>
          <el-table-column prop="point_desc" label="描述">
            <template #default="scope">
              <el-input v-model="scope.row.point_desc" type="textarea" :rows="2" size="small" />
            </template>
          </el-table-column>
          <el-table-column prop="test_type" label="类型" width="120">
            <template #default="scope">
              <el-select v-model="scope.row.test_type" size="small">
                <el-option label="功能测试" value="functional" />
                <el-option label="接口测试" value="api" />
                <el-option label="性能测试" value="performance" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="scope">
              <el-button
                type="danger"
                size="small"
                :icon="Delete"
                link
                @click="deleteTestPoint(scope.$index)"
              />
            </template>
          </el-table-column>
        </el-table>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :disabled="testPoints.length === 0" @click="nextStep">
            下一步
          </el-button>
        </div>
      </div>

      <!-- Step 6: 生成用例 -->
      <div v-if="currentStep === 5" class="step-container">
        <h3>生成测试用例</h3>
        <el-form :model="formData" label-width="140px">
          <el-form-item label="选择测试点">
            <el-select
              v-model="formData.selectedTestPoints"
              multiple
              placeholder="选择要生成用例的测试点"
              style="width: 100%"
            >
              <el-option
                v-for="point in testPoints"
                :key="point.id"
                :label="point.point_name"
                :value="point.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="生成模式">
            <el-radio-group v-model="formData.generationMode">
              <el-radio value="comprehensive">全面覆盖</el-radio>
              <el-radio value="boundary">边界条件</el-radio>
              <el-radio value="equivalence">等价类</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="幻觉检测">
            <el-switch v-model="formData.enableHallucinationCheck" />
          </el-form-item>
        </el-form>
        <el-button
          type="primary"
          :loading="generating"
          :disabled="formData.selectedTestPoints.length === 0"
          @click="generateTestCases"
        >
          生成测试用例
        </el-button>

        <div v-if="generationStatus" class="generation-status">
          <el-alert :title="generationStatus.message" :type="generationStatus.type" show-icon />
        </div>

        <div class="step-actions">
          <el-button @click="prevStep">上一步</el-button>
          <el-button type="primary" :disabled="!generationStatus || generationStatus.type !== 'success'" @click="nextStep">
            查看用例
          </el-button>
        </div>
      </div>

      <!-- Step 7: 查看用例 -->
      <div v-if="currentStep === 6" class="step-container">
        <h3>生成的测试用例</h3>
        <div class="table-toolbar">
          <el-button type="success" :icon="Download" @click="exportTestCases">导出用例</el-button>
          <el-button @click="resetWizard">重新开始</el-button>
        </div>
        <el-table :data="testCases" border>
          <el-table-column prop="case_name" label="用例名称" width="200" />
          <el-table-column prop="case_desc" label="用例描述" show-overflow-tooltip />
          <el-table-column prop="test_steps" label="测试步骤" width="300">
            <template #default="scope">
              <div v-for="(step, index) in parseSteps(scope.row.test_steps)" :key="index" class="test-step">
                {{ index + 1 }}. {{ step }}
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="expected_result" label="预期结果" show-overflow-tooltip />
          <el-table-column prop="priority" label="优先级" width="80" />
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Plus, Delete, Download } from '@element-plus/icons-vue'
import { aiCaseAPI } from '@/api/ai-case'

const currentStep = ref(0)
const projects = ref([])
const selectedFile = ref(null)
const fileList = ref([])
const uploadProgress = ref(0)
const uploading = ref(false)
const searching = ref(false)
const identifying = ref(false)
const generating = ref(false)

const formData = ref({
  projectId: '',
  knowledgeQuery: '',
  topK: 10,
  prdContent: '',
  selectedRules: [],
  selectedTestPoints: [],
  generationMode: 'comprehensive',
  enableHallucinationCheck: true
})

const knowledgeResults = ref([])
const rules = ref([])
const testPoints = ref([])
const selectedPoints = ref([])
const testCases = ref([])
const generationStatus = ref(null)

const nextStep = () => {
  if (currentStep.value < 6) {
    currentStep.value++
  }
}

const prevStep = () => {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

const onProjectChange = () => {
  // Reset form when project changes
  knowledgeResults.value = []
  testPoints.value = []
  testCases.value = []
}

const handleFileChange = (file) => {
  selectedFile.value = file.raw
  fileList.value = [file]
}

const uploadDocument = async () => {
  if (!selectedFile.value) {
    ElMessage.warning('请选择文件')
    return
  }

  uploading.value = true
  uploadProgress.value = 0

  try {
    const simulateProgress = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += 10
      }
    }, 200)

    const result = await aiCaseAPI.uploadDocument(
      formData.value.projectId,
      selectedFile.value,
      'prd'
    )

    clearInterval(simulateProgress)
    uploadProgress.value = 100

    formData.value.prdContent = result.content || ''

    ElMessage.success('文档上传成功')
    setTimeout(() => {
      nextStep()
      uploadProgress.value = 0
    }, 500)
  } catch (error) {
    ElMessage.error('文档上传失败: ' + error.message)
    uploadProgress.value = 0
  } finally {
    uploading.value = false
  }
}

const searchKnowledge = async () => {
  if (!formData.value.knowledgeQuery) {
    ElMessage.warning('请输入检索查询')
    return
  }

  searching.value = true
  try {
    const result = await aiCaseAPI.searchKnowledge(
      formData.value.projectId,
      formData.value.knowledgeQuery,
      formData.value.topK
    )
    knowledgeResults.value = result.results || []
    ElMessage.success(`检索到 ${knowledgeResults.value.length} 条相关内容`)
  } catch (error) {
    ElMessage.error('知识库检索失败: ' + error.message)
  } finally {
    searching.value = false
  }
}

const identifyTestPoints = async () => {
  if (!formData.value.prdContent) {
    ElMessage.warning('请先上传PRD文档')
    return
  }

  identifying.value = true
  try {
    const result = await aiCaseAPI.identifyTestPoints(
      formData.value.projectId,
      formData.value.prdContent,
      formData.value.selectedRules,
      knowledgeResults.value.map(r => r.document_id)
    )

    testPoints.value = result.test_points || []
    ElMessage.success(`识别到 ${testPoints.value.length} 个测试点`)
  } catch (error) {
    ElMessage.error('测试点识别失败: ' + error.message)
  } finally {
    identifying.value = false
  }
}

const addTestPoint = () => {
  testPoints.value.push({
    id: `temp_${Date.now()}`,
    point_name: '新测试点',
    point_desc: '',
    test_type: 'functional'
  })
}

const deleteTestPoint = (index) => {
  testPoints.value.splice(index, 1)
}

const handleSelectionChange = (selection) => {
  selectedPoints.value = selection
}

const deleteSelectedPoints = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedPoints.value.length} 个测试点吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const idsToDelete = selectedPoints.value.map(p => p.id)
    testPoints.value = testPoints.value.filter(p => !idsToDelete.includes(p.id))
    ElMessage.success('删除成功')
  } catch {
    // User cancelled
  }
}

const generateTestCases = async () => {
  if (formData.value.selectedTestPoints.length === 0) {
    ElMessage.warning('请至少选择一个测试点')
    return
  }

  generating.value = true
  generationStatus.value = null

  try {
    const result = await aiCaseAPI.generateTestCases(
      formData.value.projectId,
      formData.value.selectedTestPoints,
      formData.value.generationMode,
      formData.value.enableHallucinationCheck
    )

    generationStatus.value = {
      type: 'success',
      message: `成功生成 ${result.generated_count || 0} 个测试用例`
    }

    ElMessage.success('用例生成成功')
  } catch (error) {
    generationStatus.value = {
      type: 'error',
      message: '用例生成失败: ' + error.message
    }
    ElMessage.error('用例生成失败: ' + error.message)
  } finally {
    generating.value = false
  }
}

const parseSteps = (steps) => {
  if (!steps) return []
  if (typeof steps === 'string') {
    try {
      return JSON.parse(steps)
    } catch {
      return steps.split('\n').filter(s => s.trim())
    }
  }
  return steps
}

const exportTestCases = () => {
  ElMessage.info('导出功能开发中')
}

const resetWizard = () => {
  currentStep.value = 0
  formData.value = {
    projectId: '',
    knowledgeQuery: '',
    topK: 10,
    prdContent: '',
    selectedRules: [],
    selectedTestPoints: [],
    generationMode: 'comprehensive',
    enableHallucinationCheck: true
  }
  knowledgeResults.value = []
  testPoints.value = []
  testCases.value = []
  selectedFile.value = null
  fileList.value = []
  generationStatus.value = null
}

const finish = () => {
  ElMessage.success('AI用例生成流程完成！')
  // Navigate to test cases list or dashboard
}

const loadProjects = async () => {
  // Mock data - replace with actual API call
  projects.value = [
    { id: '1', name: '项目A' },
    { id: '2', name: '项目B' },
    { id: '3', name: '项目C' }
  ]
}

const loadRules = async () => {
  try {
    const result = await aiCaseAPI.getRules(0, 100)
    rules.value = result.rules || []
  } catch (error) {
    console.error('Failed to load rules:', error)
  }
}

const loadTestCases = async () => {
  if (!formData.value.projectId) return

  try {
    const result = await aiCaseAPI.getTestCases(formData.value.projectId, 0, 100)
    testCases.value = result.cases || []
  } catch (error) {
    console.error('Failed to load test cases:', error)
  }
}

onMounted(() => {
  loadProjects()
  loadRules()
})
</script>

<style scoped>
.case-generate {
  padding: 20px;
}

.step-content {
  margin-top: 20px;
  min-height: 500px;
}

.step-container {
  padding: 30px;
}

.step-container h3 {
  margin-bottom: 20px;
  color: #303133;
  font-size: 18px;
}

.step-actions {
  margin-top: 30px;
  text-align: center;
  padding-top: 20px;
  border-top: 1px solid #ebeef5;
}

.step-actions .el-button {
  min-width: 120px;
}

.upload-demo {
  margin-bottom: 20px;
}

.upload-progress {
  margin: 20px 0;
}

.knowledge-results,
.test-points-preview {
  margin-top: 30px;
}

.knowledge-results h4,
.test-points-preview h4 {
  margin-bottom: 15px;
  color: #606266;
  font-size: 16px;
}

.table-toolbar {
  margin-bottom: 15px;
}

.test-step {
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.5;
}

.generation-status {
  margin-top: 20px;
}
</style>
