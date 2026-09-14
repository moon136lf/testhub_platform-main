<template>
  <div class="script-convert">
    <el-card>
      <h2>用例转自动化脚本</h2>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="form.projectId" placeholder="选择项目" style="width: 200px" @change="loadCases">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="head-hint">列出已定稿用例，单条转换为 Playwright 脚本；脚本管理与执行请到「UI自动化测试」页。</div>
    </el-card>

    <!-- 定稿用例列表 -->
    <el-card style="margin-top: 16px">
      <el-table :data="cases" v-loading="loading">
        <el-table-column prop="name" label="用例名" min-width="240" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="90" />
        <el-table-column label="转换状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.automation_status)" size="small">{{ statusCn(row.automation_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="170" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="converting" @click="convertOne(row)">转脚本</el-button>
            <el-button link @click="showDetail(row)">详情</el-button>
            <el-button v-if="row.automation_status === 'converted'" link type="success" @click="gotoScript(row)">查看脚本</el-button>
            <el-button link type="danger" @click="delCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top: 12px" v-model:current-page="page" :page-size="pageSize"
        :total="total" layout="total, prev, pager, next" @current-change="loadCases" />
    </el-card>

    <!-- 转换直播抽屉 -->
    <el-drawer v-model="liveVisible" title="转换直播" size="45%">
      <el-progress v-if="logs.length" :percentage="Math.round((progress || 0) * 100)"
        :status="progress >= 1.0 ? 'success' : undefined" style="margin-bottom: 8px" />
      <div ref="logBox" class="log-box">
        <div v-for="(msg, i) in logs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-drawer>

    <!-- 用例详情抽屉 -->
    <el-drawer v-model="detailVisible" title="用例详情" size="55%">
      <template v-if="detailCase">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="用例名">{{ detailCase.name }}</el-descriptions-item>
          <el-descriptions-item label="优先级">{{ detailCase.priority }}</el-descriptions-item>
          <el-descriptions-item label="前置条件" :span="2">{{ detailCase.precondition || '—' }}</el-descriptions-item>
          <el-descriptions-item label="预期结果" :span="2">{{ detailCase.expected_result || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="detailSteps" border size="small" style="margin-top: 12px">
          <el-table-column type="index" label="#" width="55" />
          <el-table-column prop="action" label="操作" min-width="120" />
          <el-table-column prop="target" label="目标" min-width="140" />
          <el-table-column prop="test_data" label="测试数据" min-width="120" />
          <el-table-column prop="expected" label="预期结果" min-width="160" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { scriptAPI } from '@/api/script'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'

const router = useRouter()

// automation_status 实际枚举（backend/app/schemas/test_case.py AUTOMATION_STATUSES）：
// pending / converted / automated / partial_automated；失败/中断仍是 pending（脚本任务失败不改状态）
const STATUS_CN = {
  pending: '未转换',
  converted: '已转换',
  automated: '已自动化',
  partial_automated: '部分自动化',
}
const STATUS_TAG = { pending: 'info', converted: 'success', automated: 'success', partial_automated: 'warning' }
const statusCn = (s) => STATUS_CN[s] || s || '未转换'
const statusTagType = (s) => STATUS_TAG[s] || 'info'

const projects = ref([])
const cases = ref([])
const loading = ref(false)
const converting = ref(false)
const form = reactive({ projectId: '' })
const page = ref(1)
const pageSize = 20
const total = ref(0)

const loadCases = async () => {
  if (!form.projectId) return
  loading.value = true
  try {
    const resp = await testCaseAPI.list({
      project_id: form.projectId, is_finalized: true,
      page: page.value, page_size: pageSize,
    })
    cases.value = resp.items || []
    total.value = resp.total || 0
  } catch { ElMessage.error('用例列表加载失败') }
  loading.value = false
}

// ---- 单条转换 + SSE 直播（复用现有订阅逻辑，触发方式改为行内按钮）----
const liveVisible = ref(false)
const logs = ref([])
const progress = ref(0)

const startSSE = (sessionId, { onDone, onError }) => {
  logs.value = []; progress.value = 0
  const es = scriptAPI.subscribe(sessionId, (msg) => {
    logs.value.push(msg)
    if (typeof msg.progress === 'number') progress.value = msg.progress
    if (msg.progress >= 1.0) {
      es.close(); onDone?.()
    }
  }, (err) => { onError?.(err) })
}

const convertOne = async (row) => {
  if (!form.projectId) return
  converting.value = true
  liveVisible.value = true
  try {
    const resp = await scriptAPI.convert(form.projectId, [row.id], true)
    startSSE(resp.data.session_id, {
      onDone: () => {
        converting.value = false
        ElMessage.success('转换完成，脚本已入脚本库')
        loadCases()
      },
      onError: () => {
        converting.value = false
        ElMessage.warning('直播连接中断，结果请到「UI自动化测试」页脚本库查看')
        loadCases()
      },
    })
  } catch { ElMessage.error('转换失败'); converting.value = false }
}

const gotoScript = (row) => {
  router.push({ path: '/auto/ui', query: { caseId: row.id } })
}

const delCase = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除用例「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await testCaseAPI.delete(row.id)
    ElMessage.success('已删除')
    loadCases()
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

// ---- 用例详情抽屉 ----
const detailVisible = ref(false)
const detailCase = ref(null)
const detailSteps = computed(() => {
  const s = detailCase.value?.steps
  if (Array.isArray(s)) return s
  if (typeof s === 'string') { try { return JSON.parse(s) } catch { return [] } }
  return []
})

const showDetail = async (row) => {
  try {
    const resp = await testCaseAPI.get(row.id)
    detailCase.value = resp.data || resp
    detailVisible.value = true
  } catch { ElMessage.error('用例详情加载失败') }
}

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
  if (projects.value.length) {
    form.projectId = projects.value[0].id
    loadCases()
  }
})
</script>

<style scoped>
.head-hint { color: #909399; font-size: 13px; }
.log-box { max-height: 100%; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
</style>
