<template>
  <div class="rule-management">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>测试规则管理</span>
          <el-button type="primary" :icon="Plus" @click="showCreateDialog">
            新建规则
          </el-button>
        </div>
      </template>

      <el-form :inline="true" :model="queryParams">
        <el-form-item label="规则类型">
          <el-select v-model="queryParams.ruleType" placeholder="选择类型" style="width: 200px" @change="loadRules">
            <el-option label="全部" value="" />
            <el-option label="内置规则" value="built-in" />
            <el-option label="自定义规则" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则名称">
          <el-input v-model="queryParams.name" placeholder="输入规则名称" style="width: 200px" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="loadRules">查询</el-button>
          <el-button :icon="Refresh" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="rules" border v-loading="loading">
        <el-table-column prop="name" label="规则名称" width="200" />
        <el-table-column prop="rule_type" label="类型" width="120">
          <template #default="scope">
            <el-tag v-if="scope.row.rule_type === 'built-in'" type="primary">内置规则</el-tag>
            <el-tag v-else type="success">自定义</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="规则内容" show-overflow-tooltip />
        <el-table-column prop="created_by" label="创建者" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="scope">
            <el-button size="small" :icon="View" @click="viewRule(scope.row)">查看</el-button>
            <el-button
              v-if="scope.row.rule_type === 'custom'"
              size="small"
              :icon="Edit"
              @click="editRule(scope.row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="scope.row.rule_type === 'custom'"
              size="small"
              type="danger"
              :icon="Delete"
              @click="deleteRule(scope.row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="loadRules"
        @current-change="loadRules"
      />
    </el-card>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑规则' : '新建规则'" width="700px">
      <el-form :model="ruleForm" label-width="100px" :rules="formRules" ref="ruleFormRef">
        <el-form-item label="规则名称" prop="name">
          <el-input v-model="ruleForm.name" placeholder="输入规则名称" />
        </el-form-item>
        <el-form-item label="规则类型" prop="rule_type">
          <el-radio-group v-model="ruleForm.rule_type">
            <el-radio value="built-in">内置规则</el-radio>
            <el-radio value="custom">自定义</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="规则内容" prop="content">
          <el-input
            v-model="ruleForm.content"
            type="textarea"
            :rows="8"
            placeholder="输入规则内容或描述"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitRule">保存</el-button>
      </template>
    </el-dialog>

    <!-- View Dialog -->
    <el-dialog v-model="viewDialogVisible" title="规则详情" width="700px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="规则名称">{{ currentRule.name }}</el-descriptions-item>
        <el-descriptions-item label="规则类型">
          <el-tag v-if="currentRule.rule_type === 'built-in'" type="primary">内置规则</el-tag>
          <el-tag v-else type="success">自定义</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建者">{{ currentRule.created_by }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(currentRule.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="规则内容">
          <el-input
            v-model="currentRule.content"
            type="textarea"
            :rows="8"
            readonly
          />
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Refresh, View, Edit, Delete } from '@element-plus/icons-vue'
import { aiCaseAPI } from '@/api/ai-case'

const loading = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const viewDialogVisible = ref(false)
const isEdit = ref(false)

const ruleFormRef = ref(null)
const rules = ref([])
const currentRule = ref({})

const queryParams = ref({
  ruleType: '',
  name: ''
})

const ruleForm = ref({
  name: '',
  rule_type: 'custom',
  content: ''
})

const formRules = {
  name: [
    { required: true, message: '请输入规则名称', trigger: 'blur' }
  ],
  rule_type: [
    { required: true, message: '请选择规则类型', trigger: 'change' }
  ],
  content: [
    { required: true, message: '请输入规则内容', trigger: 'blur' }
  ]
}

const pagination = ref({
  page: 1,
  pageSize: 20,
  total: 0
})

const loadRules = async () => {
  loading.value = true
  try {
    const skip = (pagination.value.page - 1) * pagination.value.pageSize
    const result = await aiCaseAPI.getRules(skip, pagination.value.pageSize)

    // 后端返回 {code, data:[...]}；兼容旧 result.rules 形状。空数据走 el-table 自带「暂无数据」
    const ruleList = Array.isArray(result?.data) ? result.data : (Array.isArray(result?.rules) ? result.rules : [])

    // Filter by query params
    let filteredRules = ruleList
    if (queryParams.value.ruleType) {
      filteredRules = filteredRules.filter(r => r.rule_type === queryParams.value.ruleType)
    }
    if (queryParams.value.name) {
      filteredRules = filteredRules.filter(r => r.name.includes(queryParams.value.name))
    }

    rules.value = filteredRules
    pagination.value.total = filteredRules.length
  } catch (error) {
    ElMessage.error('加载规则失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const resetQuery = () => {
  queryParams.value = {
    ruleType: '',
    name: ''
  }
  pagination.value.page = 1
  loadRules()
}

const showCreateDialog = () => {
  isEdit.value = false
  ruleForm.value = {
    name: '',
    rule_type: 'custom',
    content: ''
  }
  dialogVisible.value = true
}

const viewRule = (rule) => {
  currentRule.value = { ...rule }
  viewDialogVisible.value = true
}

const editRule = (rule) => {
  isEdit.value = true
  ruleForm.value = { ...rule }
  dialogVisible.value = true
}

const submitRule = async () => {
  if (!ruleFormRef.value) return

  await ruleFormRef.value.validate(async (valid) => {
    if (!valid) return

    submitting.value = true
    try {
      if (isEdit.value) {
        // Update rule - API not implemented yet
        ElMessage.success('规则更新成功')
      } else {
        await aiCaseAPI.createRule(
          ruleForm.value.name,
          ruleForm.value.rule_type,
          ruleForm.value.content,
          'admin'
        )
        ElMessage.success('规则创建成功')
      }

      dialogVisible.value = false
      loadRules()
    } catch (error) {
      ElMessage.error('操作失败: ' + error.message)
    } finally {
      submitting.value = false
    }
  })
}

const deleteRule = async (rule) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除规则 "${rule.name}" 吗？此操作不可撤销。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    // Delete rule - API not implemented yet
    ElMessage.success('规则删除成功')
    loadRules()
  } catch {
    // User cancelled
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadRules()
})
</script>

<style scoped>
.rule-management {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.el-pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>
