<template>
  <div class="env-management page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>环境管理</h2>
        <div class="page-subtitle">管理被测环境地址，供回归执行时切换</div>
      </div>
      <el-button type="primary" @click="openCreate">新增环境</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="envs" v-loading="loading" border>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="url" label="URL" min-width="250" show-overflow-tooltip />
        <el-table-column prop="env_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="envTagType(row.env_type)">{{ envLabel(row.env_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button type="primary" link :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button type="danger" link :icon="Delete" @click="remove(row)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑环境' : '新增环境'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="URL"><el-input v-model="form.url" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.env_type" style="width: 200px">
            <el-option label="开发" value="dev" />
            <el-option label="测试" value="staging" />
            <el-option label="生产" value="prod" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemAPI } from '@/api/system.js'

const loading = ref(false)
const envs = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const form = ref({ name: '', url: '', env_type: 'dev', status: 'active' })

const envLabel = (t) => ({ dev: '开发', staging: '测试', prod: '生产' }[t] || t)
const envTagType = (t) => ({ dev: 'info', staging: 'warning', prod: 'danger' }[t] || 'info')

const load = async () => {
  loading.value = true
  try {
    const res = await systemAPI.listEnvs()
    envs.value = res.data || res || []
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const openCreate = () => {
  isEdit.value = false
  form.value = { name: '', url: '', env_type: 'dev', status: 'active' }
  dialogVisible.value = true
}

const openEdit = (row) => {
  isEdit.value = true
  form.value = { ...row }
  dialogVisible.value = true
}

const submit = async () => {
  try {
    if (isEdit.value) {
      await systemAPI.updateEnv(form.value.id, form.value)
    } else {
      await systemAPI.createEnv(form.value)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } catch (e) { ElMessage.error('保存失败') }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确定停用环境「${row.name}」？`, '确认', { type: 'warning' })
    await systemAPI.deleteEnv(row.id)
    ElMessage.success('已停用')
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

onMounted(load)
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}
</style>
