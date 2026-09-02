<template>
  <div class="generation-history page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>生成历史</h2>
        <div class="page-subtitle">AI 用例生成会话记录与结果回看</div>
      </div>
      <el-button type="primary" :icon="Refresh" @click="loadSessions">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-form :inline="true" :model="queryParams">
        <el-form-item label="项目">
          <el-select v-model="queryParams.projectId" placeholder="选择项目" style="width: 200px" @change="loadSessions">
            <el-option label="全部" value="" />
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="queryParams.status" placeholder="选择状态" style="width: 150px" @change="loadSessions">
            <el-option label="全部" value="" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="queryParams.dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 240px"
            @change="loadSessions"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="loadSessions">查询</el-button>
          <el-button :icon="Refresh" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="sessions" border v-loading="loading">
        <el-table-column prop="session_id" label="会话ID" width="180">
          <template #default="scope">
            <el-link type="primary" @click="viewSession(scope.row)">
              {{ scope.row.session_id.substring(0, 16) }}...
            </el-link>
          </template>
        </el-table-column>
        <el-table-column prop="project_name" label="项目" width="150" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="scope">
            <el-tag v-if="scope.row.status === 'in_progress'" type="warning">进行中</el-tag>
            <el-tag v-else-if="scope.row.status === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else-if="scope.row.status === 'failed'" type="danger">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="test_points_count" label="测试点数" width="100" />
        <el-table-column prop="test_cases_count" label="用例数" width="100" />
        <el-table-column prop="total_tokens" label="Token消耗" width="120">
          <template #default="scope">
            {{ scope.row.total_tokens || 0 }}
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时" width="100">
          <template #default="scope">
            {{ formatDuration(scope.row.start_time, scope.row.end_time) }}
          </template>
        </el-table-column>
        <el-table-column prop="current_step" label="进度" width="80"><template #default="scope">{{ scope.row.current_step }}/7</template></el-table-column>
        <el-table-column prop="start_time" label="开始时间" width="180">
          <template #default="scope">
            {{ formatDate(scope.row.start_time) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="scope">
            <el-button type="primary" link :icon="View" @click="viewSession(scope.row)">详情</el-button>
            <el-button type="danger" link :icon="Delete" @click="deleteSession(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="loadSessions"
        @current-change="loadSessions"
      />
    </el-card>

    <!-- Session Detail Dialog -->
    <el-dialog v-model="detailDialogVisible" title="生成历史详情" width="900px">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="会话ID">{{ currentSession.session_id }}</el-descriptions-item>
        <el-descriptions-item label="项目">{{ currentSession.project_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="currentSession.status === 'in_progress'" type="warning">进行中</el-tag>
          <el-tag v-else-if="currentSession.status === 'completed'" type="success">已完成</el-tag>
          <el-tag v-else-if="currentSession.status === 'failed'" type="danger">失败</el-tag>
        </el-descriptions-item>
        
        <el-descriptions-item label="开始时间">{{ formatDate(currentSession.start_time) }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ formatDate(currentSession.end_time) }}</el-descriptions-item>
        <el-descriptions-item label="耗时">
          {{ formatDuration(currentSession.start_time, currentSession.end_time) }}
        </el-descriptions-item>
        <el-descriptions-item label="Token消耗">{{ currentSession.total_tokens || 0 }}</el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <el-tabs v-model="activeTab">
        <el-tab-pane label="测试点" name="testPoints">
          <el-table :data="currentSession.test_points" border max-height="400">
            <el-table-column prop="name" label="测试点名称" />
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
            <el-table-column prop="type_label" label="类型" width="100" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="测试用例" name="testCases">
          <el-table :data="currentSession.test_cases" border max-height="400">
            <el-table-column prop="name" label="用例名称" />
            <el-table-column prop="priority" label="优先级" width="80" />
            <el-table-column prop="is_finalized" label="定稿" width="80">
              <template #default="scope">
                <el-tag :type="scope.row.is_finalized ? 'success' : 'info'" size="small">{{ scope.row.is_finalized ? '已定稿' : '草稿' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="配置信息" name="config">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="生成模式">{{ currentSession.generation_mode }}</el-descriptions-item>
            <el-descriptions-item label="幻觉检测">
              {{ currentSession.enable_hallucination_check ? '已启用' : '未启用' }}
            </el-descriptions-item>
            <el-descriptions-item label="使用规则">
              <el-tag v-for="rule in currentSession.rules" :key="rule" style="margin-right: 8px">
                {{ rule }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="知识库文档">
              <el-tag v-for="doc in currentSession.knowledge_docs" :key="doc" style="margin-right: 8px">
                {{ doc }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="detailDialogVisible = false">关闭</el-button>
        <el-button type="primary" :icon="Download" @click="exportSession">导出报告</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, View, Delete, Download } from '@element-plus/icons-vue'
import { aiCaseAPI } from '@/api/ai-case'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const detailDialogVisible = ref(false)
const activeTab = ref('testPoints')

const projects = ref([])
const sessions = ref([])
const currentSession = ref({
  test_points: [],
  test_cases: [],
  rules: [],
  knowledge_docs: []
})

const queryParams = ref({
  projectId: '',
  status: '',
  dateRange: null
})

const pagination = ref({
  page: 1,
  pageSize: 20,
  total: 0
})

const loadSessions = async () => {
  loading.value = true
  try {
    const res = await aiCaseAPI.listSessions(
      queryParams.value.projectId,
      queryParams.value.status,
      (pagination.value.page - 1) * pagination.value.pageSize,
      pagination.value.pageSize
    )
    const list = Array.isArray(res?.data) ? res.data : []
    sessions.value = list
    pagination.value.total = list.length
  } catch (error) {
    ElMessage.error('加载生成历史失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const resetQuery = () => {
  queryParams.value = {
    projectId: '',
    status: '',
    dateRange: null
  }
  pagination.value.page = 1
  loadSessions()
}

const viewSession = async (session) => {
  try {
    const res = await aiCaseAPI.getSessionDetail(session.session_id)
    const result = res.data || res

    currentSession.value = {
      ...session,
      test_points: result.test_points || [],
      test_cases: result.test_cases || [],
      rules: result.selected_rules ? Object.keys(result.selected_rules).filter(k => result.selected_rules[k]) : [],
      knowledge_docs: [],
      generation_mode: result.generation_mode || 'comprehensive',
      enable_hallucination_check: result.hallucination_strategy !== 'permissive'
    }

    detailDialogVisible.value = true
  } catch (error) {
    ElMessage.error('加载会话详情失败: ' + (error.response?.data?.detail || error.message))
  }
}

const deleteSession = async (session) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 "${session.session_id}" 吗？此操作不可撤销。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await aiCaseAPI.deleteSession(session.session_id)
    ElMessage.success('会话删除成功')
    loadSessions()
  } catch {
    // User cancelled
  }
}

const exportSession = () => {
  ElMessage.info('导出功能开发中')
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const formatDuration = (startStr, endStr) => {
  if (!startStr || !endStr) return '-'
  const start = new Date(startStr)
  const end = new Date(endStr)
  const seconds = Math.floor((end - start) / 1000)

  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = seconds % 60
  return `${minutes}分${remainSeconds}秒`
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list({ skip: 0, limit: 100 })
    const list = Array.isArray(res) ? res : (res?.items || res?.data || [])
    projects.value = list.map(p => ({ id: p.id, name: p.name }))
  } catch (e) {
    console.error('加载项目失败', e)
  }
}

onMounted(() => {
  loadProjects()
  loadSessions()
})
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}

.el-pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.el-divider {
  margin: 20px 0;
}
</style>
