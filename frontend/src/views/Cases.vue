<template>
  <div class="cases-management">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>用例管理</span>
          <div class="header-actions">
            <el-button type="primary" :icon="Plus" @click="showCreateDialog">新建用例</el-button>
            <el-dropdown split-button type="success" @click="handleExport('xlsx')" @command="handleExport">
              导出
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="xlsx">Excel (.xlsx)</el-dropdown-item>
                  <el-dropdown-item command="json">JSON (.json)</el-dropdown-item>
                  <el-dropdown-item command="xmind">XMind (.xmind)</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button :icon="Upload" @click="triggerImport">导入</el-button>
            <input ref="importInput" type="file" accept=".csv,.xlsx,.md" style="display:none" @change="handleImport" />
            <el-button
              type="danger"
              :icon="Delete"
              :disabled="selectedCases.length === 0"
              @click="handleBatchDelete"
            >
              批量删除
            </el-button>
            <el-button
              type="success"
              :icon="Check"
              :disabled="selectedCases.length === 0"
              @click="handleBatchFinalize"
            >
              批量定稿
            </el-button>
          </div>
        </div>
      </template>

      <!-- 筛选区域 -->
      <CaseFilter
        :projects="projects"
        :test-points="testPoints"
        @filter-change="handleFilterChange"
      />

      <!-- 列表 -->
      <el-table
        :data="cases"
        v-loading="loading"
        stripe
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" label="用例名称" min-width="200" show-overflow-tooltip />
        <el-table-column prop="point_name" label="测试点" width="150" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="100">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="case_type" label="用例类型" width="120">
          <template #default="{ row }">
            {{ getCaseTypeLabel(row.case_type) }}
          </template>
        </el-table-column>
        <el-table-column prop="automation_status" label="自动化状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getAutomationStatusType(row.automation_status)">
              {{ getAutomationStatusLabel(row.automation_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_finalized" label="定稿状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_finalized ? 'success' : 'info'">
              {{ row.is_finalized ? '已定稿' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hallucination_status" label="幻觉标记" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.hallucination_status === 'detected'" type="warning">存在幻觉</el-tag>
            <el-tag v-else type="success">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="review_status" label="评审状态" width="100">
          <template #default="{ row }">
            <el-tag :type="reviewTagType(row.review_status)">
              {{ reviewStatusLabel(row.review_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :icon="View" @click="goToDetail(row)">查看</el-button>
            <el-button type="primary" link :icon="Edit" @click="editCase(row)">编辑</el-button>
            <el-button type="danger" link :icon="Delete" @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="fetchCases"
          @current-change="fetchCases"
        />
      </div>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑用例' : '新建用例'"
      width="900px"
      :close-on-click-modal="false"
      @close="resetForm"
    >
      <CaseForm
        ref="caseFormRef"
        v-model="currentCase"
        :is-edit="isEdit"
        :projects="projects"
        @submit="handleSubmit"
        @cancel="dialogVisible = false"
      />
    </el-dialog>

    <!-- 查看详情对话框 -->
    <el-dialog
      v-model="viewDialogVisible"
      title="用例详情"
      width="900px"
    >
      <div v-if="viewingCase" class="case-detail">
        <el-descriptions>
          <el-descriptions-item label="用例名称" :span="2">
            {{ viewingCase.name }}
          </el-descriptions-item>
          <el-descriptions-item label="所属项目">
            {{ viewingCase.project_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="测试点">
            {{ viewingCase.point_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="优先级">
            <el-tag :type="getPriorityType(viewingCase.priority)">
              {{ viewingCase.priority }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用例类型">
            {{ getCaseTypeLabel(viewingCase.case_type) }}
          </el-descriptions-item>
          <el-descriptions-item label="自动化状态">
            <el-tag :type="getAutomationStatusType(viewingCase.automation_status)">
              {{ getAutomationStatusLabel(viewingCase.automation_status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="定稿状态">
            <el-tag :type="viewingCase.is_finalized ? 'success' : 'info'">
              {{ viewingCase.is_finalized ? '已定稿' : '草稿' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="幻觉标记" :span="2">
            <el-tag v-if="viewingCase.hallucination_status === 'detected'" type="warning">存在幻觉</el-tag>
            <el-tag v-else type="success">正常</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用例描述" :span="2">
            {{ viewingCase.description || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="前置条件" :span="2">
            {{ viewingCase.preconditions || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="后置条件" :span="2">
            {{ viewingCase.postconditions || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="标签" :span="2">
            <el-tag
              v-for="tag in viewingCase.tags"
              :key="tag"
              style="margin-right: 8px"
            >
              {{ tag }}
            </el-tag>
            <span v-if="!viewingCase.tags || viewingCase.tags.length === 0">-</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="steps-section">
          <h3>测试步骤</h3>
          <el-table :data="viewingCase.steps" border stripe>
            <el-table-column prop="step_number" label="步骤" width="80" align="center" />
            <el-table-column prop="action" label="操作" min-width="200" />
            <el-table-column prop="expected" label="预期结果" min-width="200" />
            <el-table-column prop="data" label="测试数据" min-width="150" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, View, Edit, Delete, Check, Upload } from '@element-plus/icons-vue'
import CaseFilter from '@/components/testCase/CaseFilter.vue'
import CaseForm from '@/components/testCase/CaseForm.vue'
import { testCaseAPI } from '@/api/testCase.js'
import { projectAPI } from '@/api/project.js'
import axios from '@/api/axios.js'

const router = useRouter()

const loading = ref(false)
const cases = ref([])
const projects = ref([])
const testPoints = ref([])
const selectedCases = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const filters = ref({})
const importInput = ref(null)

const REVIEW_STATUS_MAP = { pending: '待评审', passed: '已通过', needs_revision: '需修改' }
const reviewStatusLabel = (s) => REVIEW_STATUS_MAP[s] || '待评审'
const reviewTagType = (s) => ({ passed: 'success', needs_revision: 'warning', pending: 'info' }[s] || 'info')

const dialogVisible = ref(false)
const viewDialogVisible = ref(false)
const isEdit = ref(false)
const caseFormRef = ref(null)
const currentCase = ref({})
const viewingCase = ref(null)

const caseTypeMap = {
  functional: '功能用例',
  interface_case: '接口用例'
}

const automationStatusMap = {
  pending: '未转化',
  converted: '已转脚本',
  partial_automated: '部分自动化',
  automated: '已自动化'
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
    pending: 'info',
    converted: 'warning',
    partial_automated: 'warning',
    automated: 'success'
  }
  return typeMap[status] || 'info'
}

const fetchCases = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = {
      ...filters.value,
      skip,
      limit: pageSize.value
    }
    // 空 project_id 不传（后端 UUID('') 会 400/422）——未选项目时靠后端返回全部或前端提示
    if (!params.project_id) delete params.project_id
    const response = await testCaseAPI.list(params)
    cases.value = response.items || response
    total.value = response.total || cases.value.length
  } catch (error) {
    ElMessage.error('获取用例列表失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const fetchProjects = async () => {
  try {
    const response = await projectAPI.list()
    projects.value = response.items || response
    // 默认选中第一个项目再查询（后端 project_id 必填，避免首载 422）
    if (!filters.value.project_id && projects.value.length) {
      filters.value.project_id = projects.value[0].id
      fetchCases()
    }
  } catch (error) {
    console.error('获取项目列表失败:', error)
  }
}

const handleFilterChange = (newFilters) => {
  filters.value = newFilters
  currentPage.value = 1
  fetchCases()
}

const handleSelectionChange = (selection) => {
  selectedCases.value = selection
}

const showCreateDialog = () => {
  isEdit.value = false
  currentCase.value = {
    name: '',
    project_id: '',
    description: '',
    priority: 'P2',
    case_type: 'functional',
    preconditions: '',
    postconditions: '',
    tags: [],
    steps: []
  }
  dialogVisible.value = true
}

const goToDetail = (caseItem) => {
  router.push({ name: 'CaseDetail', params: { id: caseItem.id } })
}

const viewCase = async (caseItem) => {
  try {
    const response = await testCaseAPI.get(caseItem.id)
    viewingCase.value = response
    viewDialogVisible.value = true
  } catch (error) {
    ElMessage.error('获取用例详情失败: ' + error.message)
  }
}

const editCase = async (caseItem) => {
  try {
    const response = await testCaseAPI.get(caseItem.id)
    currentCase.value = { ...response }
    isEdit.value = true
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error('获取用例详情失败: ' + error.message)
  }
}

const deleteCase = async (caseItem) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除用例 "${caseItem.name}" 吗？`,
      '确认删除',
      {
        type: 'warning'
      }
    )

    await testCaseAPI.delete(caseItem.id)
    ElMessage.success('删除成功')
    fetchCases()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

const handleBatchDelete = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedCases.value.length} 个用例吗？`,
      '确认批量删除',
      {
        type: 'warning'
      }
    )

    const caseIds = selectedCases.value.map(c => c.id)
    const response = await testCaseAPI.batchOperation({
      action: 'delete',
      case_ids: caseIds
    })

    ElMessage.success(`成功删除 ${response.success_count} 个用例`)
    fetchCases()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('批量删除失败: ' + error.message)
    }
  }
}

const handleBatchFinalize = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要将选中的 ${selectedCases.value.length} 个用例标记为已定稿吗？`,
      '确认批量定稿',
      {
        type: 'info'
      }
    )

    const caseIds = selectedCases.value.map(c => c.id)
    const response = await testCaseAPI.batchOperation({
      action: 'finalize',
      case_ids: caseIds
    })

    ElMessage.success(`成功定稿 ${response.success_count} 个用例`)
    fetchCases()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('批量定稿失败: ' + error.message)
    }
  }
}

// ---- W4 导入导出 ----
const handleExport = async (format) => {
  const projectId = filters.value.project_id || (projects.value[0] && projects.value[0].id)
  if (!projectId) {
    ElMessage.warning('请先选择项目')
    return
  }
  try {
    const res = await testCaseAPI.exportCases(projectId, format)
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `test_cases.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error('导出失败: ' + (error.message || error))
  }
}

const triggerImport = () => {
  importInput.value?.click()
}

const handleImport = async (e) => {
  const file = e.target.files[0]
  if (!file) return
  const projectId = filters.value.project_id || (projects.value[0] && projects.value[0].id)
  if (!projectId) {
    ElMessage.warning('请先选择项目')
    e.target.value = ''
    return
  }
  const format = file.name.split('.').pop().toLowerCase()
  try {
    const res = await testCaseAPI.importCases(projectId, file, format)
    const data = res.data || res
    ElMessage.success(`导入成功 ${data.imported} 条，失败 ${data.failed} 条`)
    fetchCases()
  } catch (error) {
    ElMessage.error('导入失败: ' + (error.message || error))
  } finally {
    e.target.value = ''
  }
}

const handleSubmit = async (formData) => {
  try {
    if (isEdit.value) {
      await testCaseAPI.update(currentCase.value.id, formData)
      ElMessage.success('更新成功')
    } else {
      await testCaseAPI.create(formData)
      ElMessage.success('创建成功')
    }

    dialogVisible.value = false
    fetchCases()
  } catch (error) {
    ElMessage.error(isEdit.value ? '更新失败: ' + error.message : '创建失败: ' + error.message)
  }
}

const resetForm = () => {
  caseFormRef.value?.resetForm()
  currentCase.value = {}
}

onMounted(async () => {
  await fetchProjects()
  fetchCases()
})
</script>

<style scoped>
.cases-management {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.case-detail {
  padding: 12px 0;
}

.steps-section {
  margin-top: 24px;
}

.steps-section h3 {
  margin-bottom: 16px;
  font-size: 16px;
  font-weight: 500;
  color: #303133;
}
</style>
