<template>
  <div class="project-management">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>项目管理</span>
          <el-button type="primary" :icon="Plus" @click="showCreateDialog">新建项目</el-button>
        </div>
      </template>

      <el-table :data="projects" v-loading="loading" stripe>
        <el-table-column prop="name" label="项目名称" min-width="150" />
        <el-table-column prop="code" label="项目编码" width="120" />
        <el-table-column prop="description" label="项目描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="target_url" label="被测应用URL" min-width="180" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :icon="View" @click="viewProject(row)">查看</el-button>
            <el-button type="primary" link :icon="Edit" @click="editProject(row)">编辑</el-button>
            <el-button type="danger" link :icon="Delete" @click="deleteProject(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="fetchProjects"
          @current-change="fetchProjects"
        />
      </div>
    </el-card>

    <!-- Create/Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑项目' : '新建项目'"
      width="600px"
      @close="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="项目编码" prop="code">
          <el-input v-model="form.code" placeholder="请输入项目编码" maxlength="20" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="项目描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            placeholder="请输入项目描述"
            maxlength="500"
            show-word-limit
            :rows="4"
          />
        </el-form-item>
        <el-form-item label="被测应用URL" prop="target_url">
          <el-input v-model="form.target_url" placeholder="http://localhost:81" />
        </el-form-item>
        <el-form-item v-if="isEdit" label="状态" prop="status">
          <el-radio-group v-model="form.status">
            <el-radio label="active">启用</el-radio>
            <el-radio label="archived">归档</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, View, Edit, Delete } from '@element-plus/icons-vue'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const projects = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)

const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const form = ref({
  name: '',
  code: '',
  description: '',
  target_url: 'http://localhost:81',
  status: 'active'
})

const rules = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  code: [
    { required: true, message: '请输入项目编码', trigger: 'blur' },
    { pattern: /^[A-Z0-9_]+$/, message: '项目编码只能包含大写字母、数字和下划线', trigger: 'blur' }
  ],
  target_url: [
    { required: true, message: '请输入被测应用URL', trigger: 'blur' },
    { type: 'url', message: '请输入有效的URL', trigger: 'blur' }
  ]
}

const fetchProjects = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const response = await projectAPI.list({ skip, limit: pageSize.value })
    // projectAPI.list 已解包为裸数组（兼容 {items} 形状）
    const list = Array.isArray(response) ? response : (response?.items || [])
    projects.value = list
    total.value = list.length
  } catch (error) {
    ElMessage.error('获取项目列表失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

const showCreateDialog = () => {
  isEdit.value = false
  dialogVisible.value = true
}

const viewProject = (project) => {
  ElMessage.info('查看项目: ' + project.name)
}

const editProject = (project) => {
  isEdit.value = true
  form.value = { ...project }
  dialogVisible.value = true
}

const deleteProject = async (project) => {
  try {
    await ElMessageBox.confirm(`确定要删除项目 "${project.name}" 吗？`, '确认删除', {
      type: 'warning'
    })

    await projectAPI.delete(project.id)
    ElMessage.success('删除成功')
    fetchProjects()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

const submitForm = async () => {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
    submitting.value = true

    if (isEdit.value) {
      await projectAPI.update(form.value.id, form.value)
      ElMessage.success('更新成功')
    } else {
      await projectAPI.create(form.value)
      ElMessage.success('创建成功')
    }

    dialogVisible.value = false
    fetchProjects()
  } catch (error) {
    if (error.message) {
      ElMessage.error(isEdit.value ? '更新失败: ' + error.message : '创建失败: ' + error.message)
    }
  } finally {
    submitting.value = false
  }
}

const resetForm = () => {
  form.value = {
    name: '',
    code: '',
    description: '',
    target_url: 'http://localhost:81',
    status: 'active'
  }
  formRef.value?.clearValidate()
}

onMounted(() => {
  fetchProjects()
})
</script>

<style scoped>
.project-management {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>
