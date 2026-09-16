<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>测试集详情</h2>
        <div class="page-subtitle">{{ set?.name || '' }} · 执行与记录</div>
      </div>
      <div class="header-actions">
        <el-button link type="primary" @click="$router.back()">← 返回</el-button>
      </div>
    </div>
    <!-- 信息卡 -->
    <el-card v-if="set" style="margin-top: 12px">
      <el-descriptions :column="4">
        <el-descriptions-item label="名称">{{ set.name }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ SOURCE_CN[set.source] || set.source }}</el-descriptions-item>
        <el-descriptions-item label="用例数">{{ (set.case_ids || []).length }}</el-descriptions-item>
        <el-descriptions-item label="最近通过率">{{ set.last_pass_rate != null ? set.last_pass_rate + '%' : (set.pass_rate != null ? set.pass_rate + '%' : '—') }}</el-descriptions-item>
      </el-descriptions>
      <el-button type="primary" style="margin-top: 12px" :loading="running" @click="runSet">执行测试集</el-button>
    </el-card>
    <!-- 迷你趋势（最近10次通过率） -->
    <el-card v-if="trend.length" style="margin-top: 12px">
      <div class="trend-title">最近 {{ trend.length }} 次通过率</div>
      <div class="trend-bar">
        <div v-for="(t, i) in trend" :key="i" class="trend-col"
             :title="`${formatTime(t.started_at)} ${t.status} ${t.pass_rate}%`">
          <div class="trend-fill" :class="t.status === 'done' && t.pass_rate >= 100 ? 'ok' : 'bad'"
               :style="{ height: Math.max(t.pass_rate, 4) + '%' }" />
        </div>
      </div>
    </el-card>
    <el-tabs v-model="tab" style="margin-top: 12px">
      <el-tab-pane label="成员用例" name="cases">
        <el-table :data="caseRows" stripe>
          <el-table-column type="index" label="#" width="55" />
          <el-table-column prop="name" label="用例名" min-width="240" show-overflow-tooltip />
          <el-table-column prop="priority" label="优先级" width="90" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeCase(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="测试记录" name="records">
        <el-radio-group v-model="recordFilter" size="small" @change="onFilterChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="success">成功</el-radio-button>
          <el-radio-button value="failed">有失败</el-radio-button>
        </el-radio-group>
        <el-table :data="records" style="margin-top: 12px" stripe>
          <el-table-column label="触发时间" width="170">
            <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="recTagType(row)" size="small">{{ recCn(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通过率" min-width="160">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.pass_rate) || 0" :stroke-width="12"
                           :color="recCn(row) === '成功' ? '#67c23a' : '#e6a23c'" />
            </template>
          </el-table-column>
          <el-table-column prop="fail_count" label="失败" width="70" />
          <el-table-column label="未执行" width="90">
            <template #default="{ row }">
              <span v-if="unexecutedCount(row) > 0" style="color:#e6a23c;cursor:pointer"
                    @click="showUnexecReason(row)">{{ unexecutedCount(row) }} 条 ▸</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="viewReport(row)">查看报告</el-button>
              <el-button link type="primary" @click="rerun(row)">再跑一次</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination style="margin-top: 12px; justify-content: flex-end" v-model:current-page="recPage" :page-size="recPageSize"
                       :total="recTotal" layout="total, prev, pager, next" @current-change="loadRecords" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatTime } from '@/utils/formatTime'
import { testSetAPI } from '@/api/testSet'
import { testCaseAPI } from '@/api/testCase'

const route = useRoute()
const router = useRouter()
const setId = route.params.id

const SOURCE_CN = {
  manual: '手工',
  ai_suggest: 'AI建议',
  convert_page: '页面转换',
  ai_regression: 'AI识别回归',
  manual_regression: '手工回归',
}

const set = ref(null)
const trend = ref([])
const tab = ref('cases')
const caseRows = ref([])
const records = ref([])
const recordFilter = ref('all')
const recPage = ref(1)
const recPageSize = 20
const recTotal = ref(0)
const running = ref(false)

// ExecutionRecord.status 实际值域：running/done；成败由 fail_count 表达
const recCn = (row) => {
  if (row.status === 'running') return '执行中'
  if (row.status === 'done' && (row.fail_count || 0) === 0) return '成功'
  if (row.status === 'done' && (row.fail_count || 0) > 0) return '部分失败'
  return '失败'
}
const recTagType = (row) => {
  const cn = recCn(row)
  return { 执行中: 'warning', 成功: 'success', 部分失败: 'warning', 失败: 'danger' }[cn] || 'info'
}

const unexecutedCount = (row) =>
  Math.max((row.total_cases || 0) - (row.passed_count || 0) - (row.fail_count || 0), 0)

const fmtDuration = (ms) => ms == null ? '—' : (ms / 1000).toFixed(1) + 's'

const loadSet = async () => {
  try {
    const resp = await testSetAPI.getSet(setId)
    set.value = resp.data || null
  } catch { ElMessage.error('测试集加载失败') }
}

const loadTrend = async () => {
  try {
    const resp = await testSetAPI.getTrend(setId)
    trend.value = resp.data || []
  } catch { trend.value = [] }
}

const loadRecords = async () => {
  try {
    const resp = await testSetAPI.getRecords(setId, {
      page: recPage.value, pageSize: recPageSize, result: recordFilter.value,
    })
    records.value = resp.data?.items || []
    recTotal.value = resp.data?.total || 0
  } catch { ElMessage.error('执行记录加载失败') }
}

const onFilterChange = () => { recPage.value = 1; loadRecords() }

// 成员用例：照 AutoUITest setCases 批量查法（testCaseAPI 无批量接口，逐个拉）
const loadCases = async () => {
  caseRows.value = []
  const ids = set.value?.case_ids || []
  if (!ids.length) return
  const results = await Promise.allSettled(ids.map(id => testCaseAPI.get(id)))
  caseRows.value = results
    .filter(r => r.status === 'fulfilled' && r.value)
    .map(r => r.value.data || r.value)
}

const removeCase = async (row) => {
  try {
    await testSetAPI.removeCase(setId, row.id)
    ElMessage.success('已移除')
    set.value = { ...set.value, case_ids: (set.value.case_ids || []).filter(id => id !== row.id) }
    await loadCases()
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '移除失败') }
}

const showUnexecReason = (row) => {
  ElMessageBox.alert(
    `上次执行因失败策略中断，${unexecutedCount(row)} 条用例未执行。`,
    '未执行说明', { type: 'warning' })
}

const viewReport = (row) => {
  if (!row.exec_id) { ElMessage.warning('该记录无报告'); return }
  router.push({ path: `/reports/${row.exec_id}`, query: { from: `/auto/ui/set/${setId}`, fromTitle: '测试集详情' } })
}

// 执行：调现有 run API（后端透传 test_set_id 到 ExecutionRecord），直播仍在 AutoUITest 页
const runSet = async () => {
  running.value = true
  try {
    await testSetAPI.runSet(setId)
    ElMessage.success('执行已启动，可到测试记录查看结果')
    tab.value = 'records'
    setTimeout(() => { loadRecords(); loadTrend(); loadSet() }, 1500)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '执行启动失败')
  } finally { running.value = false }
}

const rerun = async (row) => {
  try {
    await testSetAPI.runSet(setId)
    ElMessage.success('执行已启动')
    tab.value = 'records'
    setTimeout(() => { loadRecords(); loadTrend() }, 1500)
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '执行启动失败') }
}

onMounted(async () => {
  await loadSet()
  loadTrend()
  loadCases()
  loadRecords()
})
</script>

<style scoped>
.trend-title { font-size: 13px; color: var(--mt-text-secondary); margin-bottom: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-subtitle { font-size: 13px; color: var(--mt-text-secondary); margin-top: 4px; }
.trend-bar { display: flex; align-items: flex-end; gap: 6px; height: 80px; }
.trend-col { width: 28px; height: 100%; display: flex; align-items: flex-end; background: var(--el-fill-color-lighter, #f5f7fa); border-radius: 3px 3px 0 0; overflow: hidden; }
.trend-fill { width: 100%; border-radius: 3px 3px 0 0; }
.trend-fill.ok { background: #67c23a; }
.trend-fill.bad { background: #e6a23c; }
</style>
