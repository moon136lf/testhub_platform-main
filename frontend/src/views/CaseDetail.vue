<template>
  <div class="case-detail-page">
    <!-- 批内用例模式（#case-batch T3）：来自生成记录列表的「查看」入口 -->
    <el-card v-if="batchMode" v-loading="loading">
      <template #header>
        <div class="detail-header">
          <div class="header-left">
            <el-button :icon="ArrowLeft" @click="goBack">返回</el-button>
            <span class="page-title">批内用例</span>
          </div>
          <div class="header-actions">
            <el-button
              type="success" plain :icon="Check"
              :disabled="!selectedCases.length"
              :loading="finalizing"
              @click="handleBatchFinalize"
            >
              批量定稿
            </el-button>
            <el-button
              type="primary" plain :icon="View"
              :disabled="!selectedCases.length"
              @click="goReview"
            >
              用例评审
            </el-button>
            <el-button
              type="warning" plain :icon="MagicStick"
              :disabled="!selectedCases.length"
              :loading="converting"
              @click="goConvert"
            >
              用例转自动化脚本
            </el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        生成记录：{{ batchName }}（共 {{ cases.length }} 条用例）
      </el-alert>

      <el-table :data="cases" stripe @selection-change="s => (selectedCases = s)">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="name" label="用例名称" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" @click="openCase(row)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="100">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="case_type" label="用例类型" width="110">
          <template #default="{ row }">{{ getCaseTypeLabel(row.case_type) }}</template>
        </el-table-column>
        <el-table-column prop="is_finalized" label="定稿状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_finalized ? 'success' : 'info'">
              {{ row.is_finalized ? '已定稿' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="automation_status" label="自动化状态" width="110">
          <template #default="{ row }">
            <el-tag :type="getAutomationStatusType(row.automation_status)">
              {{ getAutomationStatusLabel(row.automation_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openCase(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 单用例详情模式（原有逻辑，路由 /cases/:id） -->
    <el-card v-else v-loading="loading">
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
              <strong>{{ caseData.name }}</strong>
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
              <el-tag :type="caseData.is_finalized ? 'success' : 'info'" size="large">
                {{ caseData.is_finalized ? '已定稿' : '草稿' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="版本">
              <el-tag size="large">v{{ caseData.version }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 详细信息卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>详细信息</h3>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="前置条件">
              <div class="text-content">{{ caseData.precondition || '无' }}</div>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- W5: 评审与精修卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <div class="refine-header">
              <h3>评审与精修</h3>
              <div>
                <el-button type="primary" :loading="refining" @click="handleRefine">
                  触发精修
                </el-button>
                <el-button
                  v-if="refinementReport && refinementReport.refined_case && refinementReport.refined_case.steps"
                  type="success" plain :loading="applying" @click="handleApplyAll"
                >
                  应用全部建议
                </el-button>
              </div>
            </div>
          </template>

          <el-descriptions :column="2" border style="margin-bottom: 12px">
            <el-descriptions-item label="评审状态">
              <el-tag :type="reviewTagType(caseData.review_status)">
                {{ reviewStatusLabel(caseData.review_status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="可行性">
              <el-tag v-if="caseData.feasibility_level" :type="feasibilityTagType(caseData.feasibility_level)">
                {{ feasibilityLabel(caseData.feasibility_level) }}
              </el-tag>
              <span v-else class="empty-text">未评估</span>
            </el-descriptions-item>
            <el-descriptions-item label="不可自动化原因" :span="2">
              {{ caseData.cannot_automate_reason || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="评审意见" :span="2">
              {{ caseData.review_comment || '—' }}
            </el-descriptions-item>
          </el-descriptions>

          <!-- 评审表单 -->
          <el-form :model="reviewForm" inline size="small" style="margin-bottom: 12px">
            <el-form-item label="评审状态">
              <el-select v-model="reviewForm.review_status" style="width: 140px">
                <el-option label="待评审" value="pending" />
                <el-option label="已通过" value="passed" />
                <el-option label="需修改" value="needs_revision" />
              </el-select>
            </el-form-item>
            <el-form-item label="可行性">
              <el-select v-model="reviewForm.feasibility_level" clearable style="width: 140px">
                <el-option label="完全自动化" value="full" />
                <el-option label="部分自动化" value="partial" />
                <el-option label="需手工执行" value="manual" />
              </el-select>
            </el-form-item>
            <el-form-item label="评审意见">
              <el-input v-model="reviewForm.review_comment" placeholder="评审意见" style="width: 220px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleSaveReview">保存评审</el-button>
            </el-form-item>
          </el-form>

          <!-- 精修报告 -->
          <div v-if="refinementReport" class="refine-report">
            <div class="refine-score">
              精修评分：<strong>{{ refinementReport.score }}</strong> / 100
            </div>
            <el-table :data="refinementReport.suggestions || []" border stripe size="small">
              <el-table-column prop="id" label="编号" width="70" />
              <el-table-column prop="dimension" label="维度" width="130" />
              <el-table-column prop="severity" label="级别" width="90">
                <template #default="{ row }">
                  <el-tag :type="severityTagType(row.severity)" size="small">{{ row.severity }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="issue" label="问题" min-width="180" show-overflow-tooltip />
              <el-table-column prop="suggestion" label="建议" min-width="200" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'applied' ? 'success' : 'info'" size="small">
                    {{ row.status }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="refinementReport.normativity" class="refine-norm">
              规范度：步骤完整 {{ refinementReport.normativity.steps_complete ? '✓' : '✗' }} ·
              断言可执行 {{ refinementReport.normativity.assertion_executable ? '✓' : '✗' }} ·
              前置完整 {{ refinementReport.normativity.precondition_complete ? '✓' : '✗' }}
            </div>
          </div>
          <el-empty v-else description="尚未精修，点击「触发精修」生成报告" :image-size="60" />
        </el-card>

        <!-- W3: 版本历史卡片 -->
        <el-card class="info-card" shadow="never">
          <template #header>
            <h3>版本历史</h3>
          </template>
          <el-timeline v-if="versions.length > 0">
            <el-timeline-item
              v-for="v in versions"
              :key="v.id"
              :timestamp="formatTime(v.created_at)"
              placement="top"
            >
              <div class="version-item">
                <strong>v{{ v.version }}</strong>
                <span class="version-meta">修改人：{{ v.changed_by || '—' }}</span>
                <div class="version-diff">{{ v.diff_summary || '无变更摘要' }}</div>
                <el-button
                  type="primary"
                  link
                  size="small"
                  @click="handleRollback(v.version)"
                >
                  回滚到此版本
                </el-button>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无版本历史" :image-size="60" />
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
            <el-table-column prop="step" label="步骤" width="80" align="center" />
            <el-table-column prop="action" label="操作" min-width="250" show-overflow-tooltip />
            <el-table-column prop="target" label="目标" min-width="160" show-overflow-tooltip />
            <el-table-column prop="data" label="测试数据" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.data || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="expected" label="预期结果" min-width="250" show-overflow-tooltip />
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Edit, Delete, Check, Close, View, MagicStick } from '@element-plus/icons-vue'
import CaseForm from '@/components/testCase/CaseForm.vue'
import { testCaseAPI } from '@/api/testCase.js'
import { projectAPI } from '@/api/project.js'
import { scriptAPI } from '@/api/script.js'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const isEditing = ref(false)
const caseData = ref(null)
const editData = ref({})
const projects = ref([])
const caseFormRef = ref(null)

// ---- 批内用例模式（#case-batch T3）----
const batchMode = ref(false)
const batchId = ref('')
const batchName = ref('')
const cases = ref([])
const selectedCases = ref([])
const finalizing = ref(false)
const converting = ref(false)

const loadBatchCases = async () => {
  loading.value = true
  try {
    const res = await testCaseAPI.listBatchCases(batchId.value)
    const data = (res && res.data) || res
    cases.value = Array.isArray(data) ? data : (data.items || [])
  } catch (error) {
    ElMessage.error('加载批内用例失败: ' + (error.message || error))
  } finally {
    loading.value = false
  }
}

const openCase = (row) => {
  router.push({ name: 'CaseDetail', params: { id: row.id } })
}

const handleBatchFinalize = async () => {
  try {
    await ElMessageBox.confirm(
      `确定将选中的 ${selectedCases.value.length} 个用例标记为已定稿吗？`,
      '确认批量定稿',
      { type: 'info' }
    )
    finalizing.value = true
    const res = await testCaseAPI.batchOperation({
      action: 'finalize',
      case_ids: selectedCases.value.map(c => c.id)
    })
    ElMessage.success(`成功定稿 ${res.success_count} 个用例`)
    await loadBatchCases()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('批量定稿失败: ' + (error.message || error))
    }
  } finally {
    finalizing.value = false
  }
}

const goReview = () => {
  router.push({
    name: 'ReviewCenter',
    query: {
      batch_id: batchId.value,
      case_ids: selectedCases.value.map(c => c.id).join(',')
    }
  })
}

const goConvert = async () => {
  const caseIds = selectedCases.value.map(c => c.id)
  if (!caseIds.length) return
  converting.value = true
  try {
    const projectId = cases.value[0]?.project_id
    if (!projectId) {
      ElMessage.warning('无法确定项目，请从用例详情发起转换')
      return
    }
    const res = await scriptAPI.convert(projectId, caseIds, false)
    if (res?.data?.session_id) {
      scriptAPI.subscribe(res.data.session_id, () => {}, () => {})
    }
    ElMessage.success('转换任务已提交，脚本将自动入脚本库')
    await loadBatchCases()
  } catch (error) {
    ElMessage.error('提交转换失败: ' + (error.message || error))
  } finally {
    converting.value = false
  }
}

// W3/W5 状态
const versions = ref([])
const refinementReport = ref(null)
const refining = ref(false)
const applying = ref(false)
const reviewForm = ref({
  review_status: 'pending',
  feasibility_level: null,
  review_comment: ''
})

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

const reviewLabelMap = { pending: '待评审', passed: '已通过', needs_revision: '需修改' }
const feasibilityLabelMap = { full: '完全自动化', partial: '部分自动化', manual: '需手工执行' }
const reviewStatusLabel = (s) => reviewLabelMap[s] || '待评审'
const reviewTagType = (s) => ({ passed: 'success', needs_revision: 'warning', pending: 'info' }[s] || 'info')
const feasibilityLabel = (s) => feasibilityLabelMap[s] || s
const feasibilityTagType = (s) => ({ full: 'success', partial: 'warning', manual: 'info' }[s] || 'info')
const severityTagType = (s) => ({ high: 'danger', medium: 'warning', low: 'info' }[s] || 'info')

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
    // W5: 初始化评审表单
    reviewForm.value = {
      review_status: response.review_status || 'pending',
      feasibility_level: response.feasibility_level || null,
      review_comment: response.review_comment || ''
    }
    refinementReport.value = response.refinement_report || null
    // W3: 加载版本历史
    loadVersions(caseId)
  } catch (error) {
    ElMessage.error('加载用例详情失败: ' + error.message)
    goBack()
  } finally {
    loading.value = false
  }
}

const loadVersions = async (caseId) => {
  try {
    const res = await testCaseAPI.listVersions(caseId)
    versions.value = (res && res.data) || res || []
  } catch (error) {
    versions.value = []
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
  if (batchMode.value) {
    router.push({ name: 'Cases' })
    return
  }
  if (route.params.id) {
    router.push({ name: 'Cases' })
  }
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

// ---- W5 精修 ----
const handleRefine = async () => {
  refining.value = true
  try {
    const res = await testCaseAPI.refineCase(caseData.value.id)
    const report = (res && res.data) || res
    refinementReport.value = report
    // 同步可行性字段到 caseData
    if (report) {
      caseData.value.feasibility_level = report.feasibility_level
      caseData.value.cannot_automate_reason = report.cannot_automate_reason
      caseData.value.refined_at = new Date().toISOString()
    }
    ElMessage.success(`精修完成，评分 ${report ? report.score : '-'}`)
  } catch (error) {
    ElMessage.error('精修失败: ' + (error.message || error))
  } finally {
    refining.value = false
  }
}

const handleApplyAll = async () => {
  applying.value = true
  try {
    const res = await testCaseAPI.applySuggestions(caseData.value.id, null)
    const data = (res && res.data) || res
    ElMessage.success('已应用全部精修建议')
    await loadCaseDetail()
  } catch (error) {
    ElMessage.error('应用建议失败: ' + (error.message || error))
  } finally {
    applying.value = false
  }
}

const handleSaveReview = async () => {
  try {
    await testCaseAPI.updateReview(caseData.value.id, {
      review_status: reviewForm.value.review_status,
      feasibility_level: reviewForm.value.feasibility_level,
      review_comment: reviewForm.value.review_comment
    })
    ElMessage.success('评审已保存')
    await loadCaseDetail()
  } catch (error) {
    ElMessage.error('保存评审失败: ' + (error.message || error))
  }
}

// ---- W3 回滚 ----
const handleRollback = async (version) => {
  try {
    await ElMessageBox.confirm(
      `确定回滚到 v${version} 吗？当前版本将被覆盖（版本号继续递增）。`,
      '确认回滚',
      { type: 'warning' }
    )
    await testCaseAPI.rollback(caseData.value.id, version)
    ElMessage.success('回滚成功')
    await loadCaseDetail()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('回滚失败: ' + (error.message || error))
    }
  }
}

onMounted(() => {
  // #case-batch T3: 有 batch_id query 时进入批内用例模式
  if (route.query.batch_id) {
    batchMode.value = true
    batchId.value = String(route.query.batch_id)
    batchName.value = String(route.query.batch_name || '未命名记录')
    loadProjects()
    loadBatchCases()
    return
  }
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
  font-weight: 600;
  color: var(--mt-text);
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
  border: 1px solid var(--mt-border);
}

.info-card:last-child {
  margin-bottom: 0;
}

.info-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--mt-text);
}

.text-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  color: var(--mt-text-secondary);
}

.empty-text {
  color: var(--mt-text-secondary);
  font-style: italic;
}

.refine-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.refine-header h3 {
  margin: 0;
}

.refine-report {
  margin-top: 8px;
}

.refine-score {
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--mt-text);
}

.refine-norm {
  margin-top: 8px;
  font-size: 12px;
  color: var(--mt-text-secondary);
}

.version-item {
  padding-left: 4px;
}

.version-meta {
  margin-left: 12px;
  color: var(--mt-text-secondary);
  font-size: 12px;
}

.version-diff {
  margin: 6px 0;
  color: var(--mt-text-secondary);
  font-size: 13px;
}

.edit-mode {
  padding: 12px 0;
}
</style>
