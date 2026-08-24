<template>
  <div class="knowledge-management">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>知识库管理</span>
          <el-button type="primary" :icon="Plus" @click="showUploadDialog">
            上传文档
          </el-button>
        </div>
      </template>

      <el-form :inline="true" :model="queryParams">
        <el-form-item label="项目">
          <el-select v-model="queryParams.projectId" placeholder="选择项目" style="width: 200px" @change="loadDocuments">
            <el-option label="全部" value="" />
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="文档类型">
          <el-select v-model="queryParams.docType" placeholder="文档类型" style="width: 150px" @change="loadDocuments">
            <el-option label="全部" value="" />
            <el-option label="PRD" value="prd" />
            <el-option label="接口文档" value="api" />
            <el-option label="测试规范" value="standard" />
          </el-select>
        </el-form-item>
        <el-form-item label="向量化状态">
          <el-select v-model="queryParams.vectorStatus" placeholder="状态" style="width: 150px" @change="loadDocuments">
            <el-option label="全部" value="" />
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="processing" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="loadDocuments">查询</el-button>
          <el-button :icon="Refresh" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="documents" border v-loading="loading">
        <el-table-column prop="doc_name" label="文档名称" width="200" />
        <el-table-column prop="doc_type" label="类型" width="100">
          <template #default="scope">
            <el-tag v-if="scope.row.doc_type === 'prd'" type="primary">PRD</el-tag>
            <el-tag v-else-if="scope.row.doc_type === 'api'" type="success">API</el-tag>
            <el-tag v-else-if="scope.row.doc_type === 'standard'" type="warning">规范</el-tag>
            <el-tag v-else>其他</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="片段数" width="100" />
        <el-table-column prop="vector_status" label="向量化状态" width="120">
          <template #default="scope">
            <el-tag v-if="scope.row.vector_status === 'pending'" type="info">待处理</el-tag>
            <el-tag v-else-if="scope.row.vector_status === 'processing'" type="warning">处理中</el-tag>
            <el-tag v-else-if="scope.row.vector_status === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else-if="scope.row.vector_status === 'failed'" type="danger">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_by" label="上传者" width="120" />
        <el-table-column prop="created_at" label="上传时间" width="180">
          <template #default="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <el-button size="small" :icon="View" @click="viewDocument(scope.row)">查看</el-button>
            <el-button
              v-if="scope.row.vector_status === 'failed'"
              size="small"
              type="warning"
              :icon="RefreshRight"
              @click="retryVectorize(scope.row)"
            >
              重试
            </el-button>
            <el-button
              size="small"
              type="danger"
              :icon="Delete"
              @click="deleteDocument(scope.row)"
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
        @size-change="loadDocuments"
        @current-change="loadDocuments"
      />
    </el-card>

    <!-- Upload Dialog -->
    <el-dialog v-model="uploadDialogVisible" title="上传文档" width="600px">
      <el-form :model="uploadForm" label-width="100px">
        <el-form-item label="项目" required>
          <el-select v-model="uploadForm.projectId" placeholder="选择项目" style="width: 100%">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="文档类型" required>
          <el-select v-model="uploadForm.docType" placeholder="选择类型" style="width: 100%">
            <el-option label="PRD" value="prd" />
            <el-option label="接口文档" value="api" />
            <el-option label="测试规范" value="standard" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档" required>
          <el-upload
            class="upload-demo"
            drag
            :auto-upload="false"
            :on-change="handleFileChange"
            :file-list="uploadFileList"
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
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- View Dialog -->
    <el-dialog v-model="viewDialogVisible" title="文档详情" width="800px">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="文档名称">{{ currentDocument.doc_name }}</el-descriptions-item>
        <el-descriptions-item label="文档类型">{{ currentDocument.doc_type }}</el-descriptions-item>
        <el-descriptions-item label="片段数">{{ currentDocument.chunk_count }}</el-descriptions-item>
        <el-descriptions-item label="向量化状态">{{ currentDocument.vector_status }}</el-descriptions-item>
        <el-descriptions-item label="上传者">{{ currentDocument.created_by }}</el-descriptions-item>
        <el-descriptions-item label="上传时间">{{ formatDate(currentDocument.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="内容" :span="2">
          <el-input
            v-model="currentDocument.content"
            type="textarea"
            :rows="10"
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
import { Plus, Search, Refresh, View, Delete, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { aiCaseAPI } from '@/api/ai-case'

const loading = ref(false)
const uploading = ref(false)
const uploadDialogVisible = ref(false)
const viewDialogVisible = ref(false)

const projects = ref([])
const documents = ref([])
const currentDocument = ref({})
const uploadFileList = ref([])

const queryParams = ref({
  projectId: '',
  docType: '',
  vectorStatus: ''
})

const uploadForm = ref({
  projectId: '',
  docType: 'prd',
  file: null
})

const pagination = ref({
  page: 1,
  pageSize: 20,
  total: 0
})

const loadDocuments = async () => {
  loading.value = true
  try {
    // Mock data - replace with actual API
    documents.value = [
      {
        id: '1',
        doc_name: '用户管理模块PRD.docx',
        doc_type: 'prd',
        chunk_count: 15,
        vector_status: 'completed',
        created_by: 'admin',
        created_at: '2026-08-18T10:30:00Z',
        content: '这是PRD文档的内容...'
      },
      {
        id: '2',
        doc_name: '订单接口文档.pdf',
        doc_type: 'api',
        chunk_count: 8,
        vector_status: 'completed',
        created_by: 'dev1',
        created_at: '2026-08-17T15:20:00Z',
        content: '接口文档内容...'
      },
      {
        id: '3',
        doc_name: '测试规范v2.0.md',
        doc_type: 'standard',
        chunk_count: 0,
        vector_status: 'pending',
        created_by: 'qa1',
        created_at: '2026-08-19T09:00:00Z',
        content: ''
      }
    ]
    pagination.value.total = 3
  } catch (error) {
    ElMessage.error('加载文档失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const resetQuery = () => {
  queryParams.value = {
    projectId: '',
    docType: '',
    vectorStatus: ''
  }
  pagination.value.page = 1
  loadDocuments()
}

const showUploadDialog = () => {
  uploadForm.value = {
    projectId: '',
    docType: 'prd',
    file: null
  }
  uploadFileList.value = []
  uploadDialogVisible.value = true
}

const handleFileChange = (file) => {
  uploadForm.value.file = file.raw
  uploadFileList.value = [file]
}

const submitUpload = async () => {
  if (!uploadForm.value.projectId) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!uploadForm.value.file) {
    ElMessage.warning('请选择文件')
    return
  }

  uploading.value = true
  try {
    await aiCaseAPI.uploadDocument(
      uploadForm.value.projectId,
      uploadForm.value.file,
      uploadForm.value.docType
    )
    ElMessage.success('文档上传成功')
    uploadDialogVisible.value = false
    loadDocuments()
  } catch (error) {
    ElMessage.error('文档上传失败: ' + error.message)
  } finally {
    uploading.value = false
  }
}

const viewDocument = (doc) => {
  currentDocument.value = { ...doc }
  viewDialogVisible.value = true
}

const retryVectorize = async (doc) => {
  try {
    await ElMessageBox.confirm(
      `确定要重新向量化文档 "${doc.doc_name}" 吗？`,
      '确认操作',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    ElMessage.info('向量化任务已提交')
    // Call API to retry vectorization
    loadDocuments()
  } catch {
    // User cancelled
  }
}

const deleteDocument = async (doc) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除文档 "${doc.doc_name}" 吗？此操作不可撤销。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    ElMessage.success('文档删除成功')
    loadDocuments()
  } catch {
    // User cancelled
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const loadProjects = async () => {
  // Mock data
  projects.value = [
    { id: '1', name: '项目A' },
    { id: '2', name: '项目B' },
    { id: '3', name: '项目C' }
  ]
}

onMounted(() => {
  loadProjects()
  loadDocuments()
})
</script>

<style scoped>
.knowledge-management {
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
