<template>
  <div class="regression-page">
    <!-- 区块1: 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6"><div class="stat"><div class="num">{{ stats.total ?? 0 }}</div><div class="lbl">回归集脚本数</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num pass">{{ stats.passed ?? 0 }}</div><div class="lbl">通过</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num fail">{{ stats.failed ?? 0 }}</div><div class="lbl">失败</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num rate">{{ stats.pass_rate ?? 0 }}%</div><div class="lbl">通过率</div></div></el-col>
    </el-row>

    <!-- 工具行 -->
    <el-row style="margin: 12px 0" align="middle" :gutter="12">
      <el-col :span="6">
        <el-select v-model="projectId" placeholder="选择项目" style="width: 100%" @change="loadAll">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-col>
      <el-col :span="5">
        <el-select v-model="filterCategory" placeholder="分类筛选" clearable style="width: 100%" @change="loadList">
          <el-option v-for="c in categories" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
      </el-col>
      <el-col :span="5">
        <el-input v-model="filterKeyword" placeholder="关键词搜索脚本名" clearable @change="loadList" />
      </el-col>
      <el-col :span="8" style="text-align: right">
        <el-button type="warning" :loading="identifying" @click="reidentify">重算识别</el-button>
        <el-button @click="loadAll">刷新</el-button>
      </el-col>
    </el-row>

    <!-- 区块2: 回归集列表 -->
    <el-table :data="rows" border @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="script.name" label="名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.script.last_status === 'passed'" type="success" size="small">通过</el-tag>
          <el-tag v-else-if="row.script.last_status === 'failed'" type="danger" size="small">失败</el-tag>
          <el-tag v-else type="info" size="small">{{ row.script.last_status || 'never_run' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="AI建议" width="90">
        <template #default="{ row }">
          <el-tooltip v-if="row.ai_reason" :content="row.ai_reason" placement="top">
            <el-tag :type="row.ai_suggested ? 'warning' : 'info'" size="small">{{ row.ai_suggested ? '是' : '否' }}</el-tag>
          </el-tooltip>
          <span v-else>{{ row.ai_suggested ? '是' : '否' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="是否纳入" width="100">
        <template #default="{ row }">
          <el-tag :type="row.included ? 'success' : 'info'" size="small">{{ row.included ? '已纳入' : '未纳入' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="script.run_count" label="运行次数" width="90" />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button link type="primary" :loading="runningId === row.script.id" @click="runOne(row)">运行</el-button>
          <el-button link @click="viewReport(row)">报告</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-row style="margin-top: 12px">
      <el-button :disabled="!selected.length" @click="setMembers('add')">加入回归集</el-button>
      <el-button :disabled="!selected.length" @click="setMembers('remove')">移出回归集</el-button>
      <el-button type="primary" :loading="running" @click="runBatch">批量执行</el-button>
    </el-row>

    <!-- 文字直播区 (SSE) -->
    <el-card v-if="logs.length" style="margin-top: 16px">
      <el-progress :percentage="Math.round((progress || 0) * 100)"
        :status="progress >= 1.0 ? 'success' : undefined" style="margin-bottom: 8px" />
      <div class="log-box">
        <div v-for="(msg, i) in logs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-card>

    <!-- 区块3: 批量执行配置 -->
    <el-card style="margin-top: 16px" header="批量执行配置">
      <el-form inline>
        <el-form-item label="运行模式">
          <el-select v-model="runCfg.headless" style="width: 100px">
            <el-option label="无头" :value="true" /><el-option label="有头" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时"><el-input-number v-model="runCfg.timeout" :min="5" :max="600" /></el-form-item>
        <el-form-item label="最大失败数"><el-input-number v-model="runCfg.max_failures" :min="1" :max="100" /></el-form-item>
        <el-form-item label="失败策略">
          <el-select v-model="failStrategy" style="width: 100px">
            <el-option label="继续" value="continue" /><el-option label="停止" value="stop" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" :loading="running" @click="runBatch">开始批量执行</el-button></el-form-item>
      </el-form>
    </el-card>

    <!-- 区块4: 回归执行报告 -->
    <el-card style="margin-top: 16px" v-if="summary && summary.record">
      <template #header><span>回归执行报告：{{ summary.record.exec_id }}</span></template>
      <el-row :gutter="16">
        <el-col :span="6"><div class="stat"><div class="num">{{ summary.record.total_cases }}</div><div class="lbl">总脚本</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num pass">{{ summary.record.passed_count }}</div><div class="lbl">通过</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num fail">{{ summary.record.fail_count }}</div><div class="lbl">失败</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num rate">{{ summary.record.pass_rate }}%</div><div class="lbl">通过率</div></div></el-col>
      </el-row>
      <div v-if="summary.failed_details && summary.failed_details.length" style="margin-top: 12px" class="fail-list">
        <div class="fail-title">失败步骤（点击 AI 诊断）</div>
        <div v-for="f in summary.failed_details" :key="f.id" class="fail-row">
          <span>第 {{ f.step }} 步 {{ f.action }}：{{ f.error_type }}</span>
          <span>
            <el-image v-if="f.screenshot_url" :src="f.screenshot_url" :preview-src-list="[f.screenshot_url]" style="width: 60px; margin-right: 8px" />
            <el-button link type="primary" @click="diagnose(f)">AI诊断</el-button>
          </span>
        </div>
      </div>
      <div style="margin-top: 12px">
        <el-button @click="exportReport('html')">导出HTML</el-button>
        <el-button @click="exportReport('pdf')">导出PDF</el-button>
        <el-button @click="pushReport">推送报告</el-button>
      </div>
    </el-card>

    <!-- AI 诊断弹窗 (#5c) -->
    <el-dialog v-model="diagVisible" title="AI 诊断" width="640px">
      <div v-loading="diagLoading">
        <DiagnosisCard v-if="diagCard" :card="diagCard" :applying="applying" @apply="onApply" />
        <el-empty v-else-if="!diagLoading" description="暂无诊断结果" />
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { scriptAPI } from '@/api/script.js'
import { regressionAPI } from '@/api/regression.js'
import { diagnosticsAPI } from '@/api/diagnostics.js'
import { projectAPI } from '@/api/project.js'
import DiagnosisCard from '@/components/DiagnosisCard.vue'

const router = useRouter()

const projects = ref([])
const projectId = ref('')
const rows = ref([])
const selected = ref([])
const stats = ref({})
const summary = ref(null)

const filterCategory = ref('')
const filterKeyword = ref('')
const identifying = ref(false)
const running = ref(false)
const runningId = ref(null)

// 分类五枚举 (#8)
const categories = [
  { value: 'uncategorized', label: '未分类' },
  { value: 'ui_smoke', label: 'UI冒烟' },
  { value: 'full_regression', label: '全量回归' },
  { value: 'core_flow', label: '核心流程' },
  { value: 'interface_auto', label: '接口自动化' },
]

const runCfg = reactive({ headless: true, timeout: 60, max_failures: 8 })
const failStrategy = ref('continue')

// SSE 直播
const logs = ref([])
const progress = ref(0)
const execId = ref(null) // runBatch/runOne 响应带回, 供 AI 诊断用

// 1. 项目变化/刷新时全部加载
const loadAll = () => { loadStats(); loadList(); loadSummary() }

const loadStats = async () => {
  if (!projectId.value) { stats.value = {}; return }
  try {
    const resp = await regressionAPI.stats(projectId.value)
    stats.value = resp.data || {}
  } catch { stats.value = {} }
}

const loadList = async () => {
  if (!projectId.value) { rows.value = []; return }
  try {
    const resp = await regressionAPI.list(projectId.value, filterCategory.value, filterKeyword.value)
    rows.value = resp.data || []
  } catch { ElMessage.error('回归集列表加载失败'); rows.value = [] }
}

const loadSummary = async () => {
  if (!projectId.value) { summary.value = null; return }
  try {
    const resp = await regressionAPI.reportSummary(projectId.value)
    summary.value = resp.data || { record: null, failed_details: [] }
  } catch { summary.value = null }
}

const onSelect = (rowsSel) => { selected.value = rowsSel }

// SSE 订阅统一处理：progress >= 1.0 判完成 → 刷新
let currentES = null
const startSSE = (sessionId, { onDone, onError }) => {
  logs.value = []; progress.value = 0
  const es = scriptAPI.subscribe(sessionId, (msg) => {
    logs.value.push(msg)
    if (typeof msg.progress === 'number') progress.value = msg.progress
    if (msg.progress >= 1.0) {
      es.close(); loadAll(); onDone?.()
    }
  }, (err) => { onError?.(err) })
  currentES = es
}

// 2. 批量执行
const runBatch = async () => {
  if (!projectId.value) { ElMessage.warning('请先选择项目'); return }
  running.value = true
  try {
    const resp = await regressionAPI.run(projectId.value, {
      headless: runCfg.headless,
      timeout: runCfg.timeout,
      max_failures: runCfg.max_failures,
      fail_fast: failStrategy.value === 'stop',
    })
    execId.value = resp.data?.exec_id ?? null
    if (resp.data?.session_id) {
      startSSE(resp.data.session_id, { onDone: () => { running.value = false } })
    } else {
      running.value = false
      loadAll()
    }
  } catch (e) { ElMessage.error('批量执行失败'); running.value = false }
}

// 3. 单脚本运行
const runOne = async (row) => {
  runningId.value = row.script.id
  try {
    const resp = await scriptAPI.run(row.script.id, { ...runCfg })
    execId.value = resp.data?.exec_id ?? null
    if (resp.data?.session_id) {
      startSSE(resp.data.session_id, { onDone: () => { runningId.value = null } })
    } else {
      runningId.value = null
      loadAll()
    }
  } catch (e) { ElMessage.error('运行失败'); runningId.value = null }
}

// 4. 加入/移出回归集
const setMembers = async (action) => {
  if (!selected.value.length) return
  try {
    await regressionAPI.setMembers(projectId.value, selected.value.map(r => r.script.id), action)
    ElMessage.success(action === 'add' ? '已加入回归集' : '已移出回归集')
    selected.value = []
    loadList(); loadStats()
  } catch (e) { ElMessage.error('操作失败') }
}

// 5. 重算识别
const reidentify = async () => {
  if (!projectId.value) { ElMessage.warning('请先选择项目'); return }
  identifying.value = true
  try {
    const resp = await regressionAPI.identify(projectId.value)
    const count = resp.data?.suggested_count ?? resp.data?.count ?? ''
    ElMessage.success(`识别完成${count !== '' ? `，建议纳入 ${count} 个脚本` : ''}`)
    loadAll()
  } catch (e) { ElMessage.error('识别失败') } finally { identifying.value = false }
}

// 6. AI 诊断 (#5c detail_id 直取链路)
const diagVisible = ref(false)
const diagLoading = ref(false)
const applying = ref(false)
const diagCard = ref(null)
const diagRow = ref(null)

const diagnose = async (f) => {
  const eid = execId.value || summary.value?.record?.exec_id  // 刷新后兜底: 用最近一次回归记录
  if (!eid) { ElMessage.info('请先执行回归'); return }
  diagRow.value = f
  diagCard.value = null
  diagVisible.value = true
  diagLoading.value = true
  try {
    const resp = await diagnosticsAPI.analyze(eid, f.step, null, f.id)
    diagCard.value = resp.data?.card ?? resp.data
    ElMessage.success('诊断完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '诊断失败')
    diagVisible.value = false
  } finally { diagLoading.value = false }
}

// 7. 应用修复回写
const onApply = async () => {
  if (!diagCard.value?.new_locator || !diagRow.value?.script_id) return
  applying.value = true
  try {
    await diagnosticsAPI.apply({
      script_id: diagRow.value.script_id,
      project_id: projectId.value,
      element_name: diagCard.value.element_name ?? '',
      new_locator: diagCard.value.new_locator,
      confidence: diagCard.value.confidence,
    })
    ElMessage.success('已回写元素库（source=ai_fixed），可重跑验证')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '应用修复失败')
  } finally { applying.value = false }
}

// 8. 查看单脚本报告
const viewReport = async (row) => {
  try {
    const resp = await regressionAPI.latestExecution(row.script.id)
    if (resp.data?.record) {
      router.push(`/reports/${resp.data.record.exec_id}`)
    } else {
      ElMessage.info('该脚本暂无执行记录')
    }
  } catch (e) { ElMessage.info('该脚本暂无执行记录') }
}

// 9. 导出报告 (整页下载走全路径)
const exportReport = (fmt) => {
  if (!summary.value?.record) return
  window.location = `/api/v1/reports/${summary.value.record.exec_id}/export?format=${fmt}`
}

// 10. 推送报告
const pushReport = async () => {
  if (!summary.value?.record) return
  try {
    const res = await regressionAPI.push(summary.value.record.exec_id)
    const d = res.data || res
    if (d.pushed) {
      const ch = Object.entries(d.channels || {}).filter(([, v]) => v === 'ok').map(([k]) => k)
      ElMessage.success(`已推送到：${ch.join('、') || 'webhook'}`)
    } else {
      ElMessage.warning('未配置推送渠道——请在 系统设置 中配置钉钉/企微/飞书 Webhook（category=notify）')
    }
  } catch (e) { ElMessage.error('推送失败: ' + (e.message || e)) }
}

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
  if (projects.value.length && !projectId.value) {
    projectId.value = projects.value[0].id
    loadAll()
  }
})
</script>

<style scoped>
.regression-page { padding: 4px; }
.stats-row { margin-top: 8px; }
.stat { text-align: center; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.stat .num { font-size: 22px; font-weight: 600; } .stat .pass { color: #67c23a; }
.stat .fail { color: #f56c6c; } .stat .rate { color: #409eff; }
.stat .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.fail-list { margin-top: 12px; padding: 8px 12px; background: #fef0f0; border-radius: 4px; }
.fail-title { font-size: 13px; color: #f56c6c; margin-bottom: 6px; }
.fail-row { display: flex; justify-content: space-between; align-items: center; padding: 2px 0; font-size: 13px; }
</style>
