<template>
  <div class="cases-management page-container">
    <!-- 页头：标题 + 主操作组 -->
    <div class="page-header">
      <div>
        <h2>用例管理</h2>
        <div class="page-subtitle">管理用例生成记录：查看、删除，点「查看」进入批内用例操作</div>
      </div>
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
      </div>
    </div>

    <el-card shadow="never">
      <!-- 筛选区域 -->
      <el-form inline style="margin-bottom: 4px">
        <el-form-item label="项目">
          <el-select v-model="filters.project_id" filterable clearable placeholder="全部项目"
            style="width: 220px" @change="onFilterChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="filters.batch_type" clearable placeholder="全部类型"
            style="width: 180px" @change="onFilterChange">
            <el-option v-for="(v, k) in typeMap" :key="k" :label="v.label" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="记录名称">
          <el-input v-model="keyword" placeholder="按记录名搜索，回车触发" clearable
            style="width: 240px" @keyup.enter="onFilterChange" @clear="onFilterChange" />
        </el-form-item>
      </el-form>

      <!-- 列表 -->
      <el-table :data="batches" v-loading="loading" stripe>
        <el-table-column prop="batch_name" label="记录名称" min-width="280" show-overflow-tooltip />
        <el-table-column prop="batch_type" label="类型" width="150">
          <template #default="{ row }">
            <el-tag :type="typeMap[row.batch_type]?.tag || 'info'">
              {{ typeMap[row.batch_type]?.label || row.batch_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="case_count" label="用例数" width="100" align="center" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :icon="View" @click="goToDetail(row)">查看</el-button>
            <el-button type="danger" link :icon="Delete" @click="deleteBatch(row)">删除</el-button>
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
          @size-change="fetchBatches"
          @current-change="fetchBatches"
        />
      </div>
    </el-card>

    <!-- 新建用例对话框（仅创建入口；isEdit 恒为 false，编辑在 CaseDetail 完成） -->
    <el-dialog
      v-model="dialogVisible"
      title="新建用例"
      width="900px"
      :close-on-click-modal="false"
      @close="resetForm"
    >
      <CaseForm
        ref="caseFormRef"
        v-model="currentCase"
        :is-edit="false"
        :projects="projects"
        @submit="handleSubmit"
        @cancel="dialogVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, View, Upload } from '@element-plus/icons-vue'
import CaseForm from '@/components/testCase/CaseForm.vue'
import { testCaseAPI } from '@/api/testCase.js'
import { projectAPI } from '@/api/project.js'

const router = useRouter()

const loading = ref(false)
const batches = ref([])
const projects = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const filters = ref({ project_id: '', batch_type: '' })
const keyword = ref('')
const importInput = ref(null)

const typeMap = {
  whitescan_api: { label: '白盒-接口回归', tag: 'warning' },
  whitescan_ui: { label: '白盒-UI回归', tag: 'success' },
  ai_generate: { label: 'AI需求生成', tag: 'primary' },
  manual: { label: '手工创建', tag: 'info' },
}

const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  })
}

const fetchBatches = async () => {
  loading.value = true
  try {
    const params = {
      project_id: filters.value.project_id || undefined,
      batch_type: filters.value.batch_type || undefined,
      keyword: keyword.value || undefined,
      page: currentPage.value,
      page_size: pageSize.value
    }
    const response = await testCaseAPI.listBatches(params)
    const data = (response && response.data) || response
    batches.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error('获取生成记录列表失败: ' + (error.message || error))
  } finally {
    loading.value = false
  }
}

const fetchProjects = async () => {
  try {
    const response = await projectAPI.list()
    projects.value = response.items || response
  } catch (error) {
    console.error('获取项目列表失败:', error)
  }
}

const onFilterChange = () => {
  currentPage.value = 1
  fetchBatches()
}

const goToDetail = (row) => {
  router.push({ name: 'CaseDetail', params: { id: row.id }, query: { batch_id: row.id, batch_name: row.batch_name } })
}

const deleteBatch = async (row) => {
  try {
    await ElMessageBox.confirm(
      `将删除记录《${row.batch_name}》及其 ${row.case_count} 条用例，不可恢复`,
      '确认删除',
      { type: 'warning' }
    )
    await testCaseAPI.deleteBatch(row.id)
    ElMessage.success('删除成功')
    fetchBatches()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + (error.message || error))
    }
  }
}

// ---- 新建用例（保留原有能力，用例归属到项目，出现在「手工创建」类记录中）----
const dialogVisible = ref(false)
const caseFormRef = ref(null)
const currentCase = ref({})

const showCreateDialog = () => {
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

const handleSubmit = async (formData) => {
  try {
    await testCaseAPI.create(formData)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    fetchBatches()
  } catch (error) {
    ElMessage.error('创建失败: ' + error.message)
  }
}

const resetForm = () => {
  caseFormRef.value?.resetForm()
  currentCase.value = {}
}

// ---- W4 导入导出（按项目维度，保留原逻辑）----
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
    fetchBatches()
  } catch (error) {
    ElMessage.error('导入失败: ' + (error.message || error))
  } finally {
    e.target.value = ''
  }
}

onMounted(async () => {
  await fetchProjects()
  fetchBatches()
})
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
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
</style>
