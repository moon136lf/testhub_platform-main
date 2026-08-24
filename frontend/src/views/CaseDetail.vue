<template>
  <div class="case-detail-page">
    <el-card v-loading="loading">
      <!-- 顶部操作栏 -->
      <template #header>
        <div class="detail-header">
          <div class="header-left">
            <el-button :icon="ArrowLeft" @click="goBack">返回</el-button>
            <span class="page-title">用例详情</span>
          </div>
          <div class="header-actions">
            <el-button v-if="!isEditing" type="primary" :icon="Edit" @click="enterEditMode">
              编辑
            </el-button>
            <el-button v-if="isEditing" type="success" :icon="Check" :loading="saving" @click="saveChanges">
              保存
            </el-button>
            <el-button v-if="isEditing" :icon="Close" @click="cancelEdit">
              取消
            </el-button>
            <el-popconfirm
              title="确定要删除此用例吗？"
              confirm-button-text="确定"
              cancel-button-text="取消"
              @confirm="handleDelete"
            >
              <template #reference>
                <el-button type="danger" :icon="Delete">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </template>

      <!-- 查看模式 -->
      <div v-if="!isEditing && caseData" class="view-mode">
        <!-- 幻觉警告 -->
        <el-alert
          v-if="caseData.has_hallucination"
          title="此用例可能包含AI幻觉内容"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 20px"
        >
          <template #default>
            <div>请仔细检查用例内容的准确性和合理性，必要时进行人工修正。</div>
          </template>
        </el-alert>

        <!-- 基本信息卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>基本信息</h3>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="用例名称" :span="2">
              <strong>{{ caseData.title }}</strong>
            </el-descriptions-item>
            <el-descriptions-item label="所属项目">
              {{ caseData.project_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="测试点">
              {{ caseData.test_point_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="优先级">
              <el-tag :type="getPriorityType(caseData.priority)" size="large">
                {{ caseData.priority }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="用例类型">
              <el-tag size="large">{{ getCaseTypeLabel(caseData.case_type) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="自动化状态">
              <el-tag :type="getAutomationStatusType(caseData.automation_status)" size="large">
                {{ getAutomationStatusLabel(caseData.automation_status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="定稿状态">
              <el-tag :type="caseData.finalized ? 'success' : 'info'" size="large">
                {{ caseData.finalized ? '已定稿' : '草稿' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 详细信息卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>详细信息</h3>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="用例描述">
              <div class="text-content">{{ caseData.description || '无' }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="前置条件">
              <div class="text-content">{{ caseData.preconditions || '无' }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="后置条件">
              <div class="text-content">{{ caseData.postconditions || '无' }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="标签">
              <div v-if="caseData.tags && caseData.tags.length > 0">
                <el-tag
                  v-for="tag in caseData.tags"
                  :key="tag"
                  style="margin-right: 8px"
                  size="large"
                >
                  {{ tag }}
                </el-tag>
              </div>
              <span v-else class="empty-text">无标签</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 测试步骤卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>测试步骤</h3>
          </template>
          <el-table
            :data="caseData.steps"
            border
            stripe
            style="width: 100%"
          >
            <el-table-column prop="step_number" label="步骤" width="80" align="center" />
            <el-table-column prop="action" label="操作" min-width="250" show-overflow-tooltip />
            <el-table-column prop="expected" label="预期结果" min-width="250" show-overflow-tooltip />
            <el-table-column prop="data" label="测试数据" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.data || '-' }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 元数据卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>元数据</h3>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="创建人">
              {{ caseData.created_by || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ formatTime(caseData.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="最后更新人">
              {{ caseData.updated_by || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">
              {{ formatTime(caseData.updated_at) }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </div>

      <!-- 编辑模式 -->
      <div v-if="isEditing" class="edit-mode">
        <CaseForm
          ref="caseFormRef"
          v-model="editData"
          :is-edit="true"
          :projects="projects"
          @submit="handleUpdate"
          @cancel="cancelEdit"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Edit, Delete, Check, Close } from '@element-plus/icons-vue'
import CaseForm from '@/components/testCase/CaseForm.vue'
import { testCaseAPI } from '@/api/testCase.js'
import { projectAPI } from '@/api/project.js'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const isEditing = ref(false)
const caseData = ref(null)
const editData = ref({})
const projects = ref([])
const caseFormRef = ref(null)

const caseTypeMap = {
  functional: '功能测试',
  api: '接口测试',
  performance: '性能测试',
  security: '安全测试',
  compatibility: '兼容测试'
}

const automationStatusMap = {
  none: '未自动化',
  partial: '部分自动化',
  full: '已自动化'
}

const getPriorityType = (priority) => {
  const typeMap = {
    P0: 'danger',
    P1: 'warning',
    P2: '',
    P3: 'info'
  }
  return typeMap[priority] || ''
}

const getCaseTypeLabel = (type) => {
  return caseTypeMap[type] || type
}

const getAutomationStatusLabel = (status) => {
  return automationStatusMap[status] || status
}

const getAutomationStatusType = (status) => {
  const typeMap = {
    none: 'info',
    partial: 'warning',
    full: 'success'
  }
  return typeMap[status] || 'info'
}

const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const loadCaseDetail = async () => {
  const caseId = route.params.id
  if (!caseId) {
    ElMessage.error('缺少用例ID')
    goBack()
    return
  }

  loading.value = true
  try {
    const response = await testCaseAPI.get(caseId)
    caseData.value = response
  } catch (error) {
    ElMessage.error('加载用例详情失败: ' + error.message)
    goBack()
  } finally {
    loading.value = false
  }
}

const loadProjects = async () => {
  try {
    const response = await projectAPI.list()
    projects.value = response.items || response
  } catch (error) {
    console.error('加载项目列表失败:', error)
  }
}

const goBack = () => {
  router.push({ name: 'Cases' })
}

const enterEditMode = () => {
  editData.value = { ...caseData.value }
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
  editData.value = {}
}

const saveChanges = async () => {
  if (!caseFormRef.value) return

  try {
    await caseFormRef.value.validate()
    await handleUpdate(editData.value)
  } catch (error) {
    ElMessage.warning('请完善表单信息')
  }
}

const handleUpdate = async (formData) => {
  saving.value = true
  try {
    await testCaseAPI.update(caseData.value.id, formData)
    ElMessage.success('更新成功')
    isEditing.value = false
    await loadCaseDetail()
  } catch (error) {
    ElMessage.error('更新失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

const handleDelete = async () => {
  try {
    await testCaseAPI.delete(caseData.value.id)
    ElMessage.success('删除成功')
    goBack()
  } catch (error) {
    ElMessage.error('删除失败: ' + error.message)
  }
}

onMounted(() => {
  loadProjects()
  loadCaseDetail()
})
</script>

<style scoped>
.case-detail-page {
  padding: 20px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-title {
  font-size: 18px;
  font-weight: 500;
  color: #303133;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.view-mode {
  padding: 8px 0;
}

.info-card {
  margin-bottom: 20px;
  border: 1px solid #EBEEF5;
}

.info-card:last-child {
  margin-bottom: 0;
}

.info-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 500;
  color: #303133;
}

.text-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  color: #606266;
}

.empty-text {
  color: #909399;
  font-style: italic;
}

.edit-mode {
  padding: 12px 0;
}
</style>
