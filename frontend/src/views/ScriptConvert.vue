<template>
  <div class="script-convert">
    <el-card>
      <h2>用例转自动化脚本</h2>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="form.projectId" placeholder="选择项目" style="width: 200px" @change="onProjectChange">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 统计卡片 (项目选定后显示) -->
    <el-row v-if="form.projectId" :gutter="12" style="margin-top: 16px">
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">总脚本数</div>
          <div class="stat-value">{{ stats.total ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card stat-pass">
          <div class="stat-label">通过</div>
          <div class="stat-value">{{ stats.passed ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card stat-fail">
          <div class="stat-label">失败</div>
          <div class="stat-value">{{ stats.failed ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card stat-never">
          <div class="stat-label">从未运行</div>
          <div class="stat-value">{{ stats.never_run ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card stat-rate">
          <div class="stat-label">通过率</div>
          <div class="stat-value">{{ stats.pass_rate ?? 0 }}%</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 执行失败明细 (AI 诊断入口, #5c) -->
    <div v-if="lastExecFails.length" class="fail-list">
      <div class="fail-title">失败步骤（点击 AI 诊断）</div>
      <div v-for="f in lastExecFails" :key="f.id" class="fail-row">
        <span>第 {{ f.step }} 步 {{ f.action }}：{{ f.error_type }}</span>
        <el-button link type="primary" @click="openExecDiagnose(f)">AI诊断</el-button>
      </div>
    </div>

    <!-- Tab 切换：转脚本 / 脚本库执行 / 快速运行 -->
    <el-tabs v-model="activeTab" style="margin-top: 16px">
      <!-- Tab1: 转脚本 (#4 既有) -->
      <el-tab-pane label="转脚本" name="convert">
        <el-card>
          <el-form inline>
            <el-form-item label="用例">
              <el-select v-model="form.caseIds" multiple filterable placeholder="多选用例" style="width: 360px">
                <el-option v-for="c in finalizedCases" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="AI优化">
              <el-switch v-model="form.aiOptimize" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="converting" @click="handleConvert">批量转脚本</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Tab2: 脚本库执行 (新增) -->
      <el-tab-pane label="脚本库执行" name="library">
        <el-card>
          <div class="lib-toolbar">
            <el-select v-model="filter.category" placeholder="分类筛选" clearable style="width: 160px" @change="loadScripts">
              <el-option label="未分类" value="uncategorized" />
              <el-option label="登录" value="login" />
              <el-option label="冒烟" value="smoke" />
              <el-option label="回归" value="regression" />
            </el-select>
            <el-input v-model="filter.keyword" placeholder="关键词搜索脚本名" clearable style="width: 220px" @change="loadScripts" />
            <el-button @click="loadScripts" :icon="Refresh">刷新</el-button>
            <el-button type="warning" :disabled="!selected.length" :loading="batching" @click="handleBatchRun">
              批量运行 ({{ selected.length }})
            </el-button>
            <span class="run-cfg-label">运行配置：</span>
            <el-checkbox v-model="runConfig.headless">headless</el-checkbox>
            <el-input-number v-model="runConfig.timeout" :min="10" :max="600" controls-position="right" style="width: 110px" />s
            <el-input-number v-model="runConfig.max_failures" :min="1" :max="50" controls-position="right" style="width: 110px" />最大失败
          </div>

          <el-table :data="scripts" border style="margin-top: 12px" @selection-change="onSelectionChange">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="last_status" label="上次结果" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.last_status === 'passed'" type="success" size="small">通过</el-tag>
                <el-tag v-else-if="row.last_status === 'failed'" type="danger" size="small">失败</el-tag>
                <el-tag v-else type="info" size="small">{{ row.last_status || 'never_run' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="run_count" label="运行次数" width="90" />
            <el-table-column prop="locator_source" label="定位来源" width="130" />
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button size="small" type="primary" :loading="runningId === row.id" @click="handleRun(row)">运行</el-button>
                <el-button size="small" @click="viewScript(row)">查看</el-button>
                <el-button size="small" type="success" :disabled="row.status === 'confirmed'" @click="confirmScript(row)">确认入库</el-button>
                <el-button size="small" @click="openDiagnose(row)">调试修复</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- Tab3: 快速运行 (新增) -->
      <el-tab-pane label="快速运行" name="quick">
        <el-card>
          <el-form label-width="100px">
            <el-form-item label="被测URL">
              <el-input v-model="quickForm.targetUrl" placeholder="http://localhost:8080/login" style="width: 420px" />
            </el-form-item>
            <el-form-item label="运行模式">
              <el-radio-group v-model="quickForm.headless">
                <el-radio :value="true">无头</el-radio>
                <el-radio :value="false">有头</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="脚本内容">
              <el-input v-model="quickForm.scriptContent" type="textarea" :rows="12"
                placeholder="粘贴 Playwright 脚本内容..." style="font-family: monospace" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="quickRunning" @click="handleQuickRun">运行</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 文字直播区 (转换/执行共用) -->
    <el-card style="margin-top: 16px">
      <h3>{{ liveTitle }}</h3>
      <el-progress v-if="logs.length" :percentage="Math.round((progress || 0) * 100)"
        :status="progress >= 1.0 ? 'success' : undefined" style="margin-bottom: 8px" />
      <div class="log-box">
        <div v-for="(msg, i) in logs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-card>

    <el-dialog v-model="diagVisible" title="调试修复" width="700px">
      <el-form label-width="100px">
        <el-form-item label="错误类型">
          <el-select v-model="diagForm.error_type" style="width: 200px">
            <el-option label="定位失败" value="locate_failed" />
            <el-option label="超时" value="timeout" />
            <el-option label="断言失败" value="assertion_failed" />
            <el-option label="脚本错误" value="script_error" />
          </el-select>
        </el-form-item>
        <el-form-item label="错误信息">
          <el-input v-model="diagForm.error_msg" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="脚本片段">
          <el-input v-model="diagForm.script_fragment" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="失败步骤">
          <el-input-number v-model="diagForm.failed_step" :min="1" />
        </el-form-item>
        <el-form-item label="截图URL">
          <el-input v-model="diagForm.screenshot_url" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div v-if="diagCard" class="diag-card">
        <p>归因: <strong>{{ diagCard.category }}</strong> | 可改: {{ diagCard.can_fix }}</p>
        <p>理由: {{ diagCard.reason }}</p>
        <p v-if="diagCard.suggestion">建议: {{ diagCard.suggestion }}</p>
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="primary" @click="runDiagnose">诊断</el-button>
      </template>
    </el-dialog>

    <!-- AI 诊断弹窗 (#5c, 与 #4 调试修复弹窗并存) -->
    <el-dialog v-model="aiDiagVisible" title="AI 诊断" width="640px">
      <div v-loading="aiDiagLoading">
        <DiagnosisCard v-if="aiDiagCard" :card="aiDiagCard" :applying="aiApplying" @apply="onAiApply" />
        <el-empty v-else-if="!aiDiagLoading" description="暂无诊断结果" />
      </div>
      <template #footer>
        <el-button @click="aiDiagVisible = false">关闭</el-button>
        <el-button type="success" :disabled="!aiDiagCard || !aiDiagCard.new_locator" @click="rerunHint">
          重跑验证
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { scriptAPI } from '@/api/script'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'
import { diagnosticsAPI } from '@/api/diagnostics'
import DiagnosisCard from '@/components/DiagnosisCard.vue'
import axios from '@/api/axios.js'

const projects = ref([])
const finalizedCases = ref([])
const scripts = ref([])
const logs = ref([])
const progress = ref(0)
const converting = ref(false)
const form = reactive({ projectId: '', caseIds: [], aiOptimize: false })

const activeTab = ref('convert')
const liveTitle = computed(() => {
  if (converting.value) return '转换过程文字直播'
  if (runningId.value || batching.value || quickRunning.value) return '执行过程文字直播'
  return '文字直播'
})

// ---- 统计卡片 ----
const stats = ref({})
const loadStats = async () => {
  if (!form.projectId) { stats.value = {}; return }
  try {
    const resp = await scriptAPI.stats(form.projectId)
    stats.value = resp.data || {}
  } catch { stats.value = {} }
}

// ---- 脚本库执行 ----
const filter = reactive({ category: '', keyword: '' })
const selected = ref([])
const runningId = ref(null)
const batching = ref(false)
const quickRunning = ref(false)
const runConfig = reactive({ headless: true, timeout: 60, max_failures: 8 })

const onSelectionChange = (rows) => { selected.value = rows }

const onProjectChange = () => {
  loadCases()
  loadScripts()
  loadStats()
}

const loadCases = async () => {
  if (!form.projectId) return
  const resp = await testCaseAPI.list({ project_id: form.projectId, is_finalized: true })
  finalizedCases.value = resp.items || resp.data?.items || resp || []
}

const loadScripts = async () => {
  if (!form.projectId) { scripts.value = []; return }
  try {
    const resp = await scriptAPI.list({
      project_id: form.projectId,
      category: filter.category || undefined,
      keyword: filter.keyword || undefined,
    })
    scripts.value = resp.data || []
  } catch (e) { ElMessage.error('脚本列表加载失败'); scripts.value = [] }
}

// SSE 订阅统一处理：progress >= 1.0 判完成 → 刷新统计/列表
let currentES = null
const startSSE = (sessionId, { onDone, onError }) => {
  logs.value = []; progress.value = 0
  const es = scriptAPI.subscribe(sessionId, (msg) => {
    logs.value.push(msg)
    if (typeof msg.progress === 'number') progress.value = msg.progress
    if (msg.progress >= 1.0) {
      es.close(); loadStats(); loadScripts(); onDone?.()
    }
  }, (err) => { onError?.(err) })
  currentES = es
}

const handleConvert = async () => {
  if (!form.projectId || !form.caseIds.length) {
    ElMessage.warning('请选择项目和用例'); return
  }
  converting.value = true
  try {
    const resp = await scriptAPI.convert(form.projectId, form.caseIds, form.aiOptimize)
    startSSE(resp.data.session_id, { onDone: () => { converting.value = false } })
  } catch (e) { ElMessage.error('转换失败'); converting.value = false }
}

const handleRun = async (row) => {
  runningId.value = row.id
  try {
    const resp = await scriptAPI.run(row.id, { ...runConfig })
    execSessionId.value = resp.data.session_id
    lastExecFails.value = []
    startSSE(resp.data.session_id, {
      onDone: async () => {
        runningId.value = null
        await loadExecFails()
      },
    })
  } catch (e) { ElMessage.error('运行失败'); runningId.value = null }
}

const handleBatchRun = async () => {
  if (!selected.value.length) { ElMessage.warning('请勾选脚本'); return }
  batching.value = true
  try {
    const ids = selected.value.map(s => s.id)
    const resp = await scriptAPI.batchRun(ids, { ...runConfig })
    execSessionId.value = resp.data.session_id
    lastExecFails.value = []
    startSSE(resp.data.session_id, {
      onDone: async () => {
        batching.value = false
        await loadExecFails()
      },
    })
  } catch (e) { ElMessage.error('批量运行失败'); batching.value = false }
}

// ---- 快速运行 ----
const quickForm = reactive({ scriptContent: '', targetUrl: '', headless: true })
const handleQuickRun = async () => {
  if (!quickForm.scriptContent || !quickForm.targetUrl) {
    ElMessage.warning('请填写脚本内容和被测URL'); return
  }
  quickRunning.value = true
  try {
    const resp = await scriptAPI.quickRun(quickForm.scriptContent, quickForm.targetUrl, quickForm.headless)
    startSSE(resp.data.session_id, { onDone: () => { quickRunning.value = false } })
  } catch (e) { ElMessage.error('快速运行失败'); quickRunning.value = false }
}

const viewScript = (row) => { window.open(`/api/v1/scripts/${row.id}`, '_blank') }
const confirmScript = async (row) => {
  await scriptAPI.confirm(row.id)
  ElMessage.success('已确认入库'); loadScripts()
}

// ---- 调试修复 (#4 既有) ----
const diagVisible = ref(false)
const diagForm = reactive({ error_type: 'locate_failed', error_msg: '', script_fragment: '', failed_step: 1, screenshot_url: '' })
const diagCard = ref(null)
let currentScriptId = null

const openDiagnose = (row) => {
  currentScriptId = row.id
  diagCard.value = null
  diagVisible.value = true
}
const runDiagnose = async () => {
  const resp = await scriptAPI.diagnose(currentScriptId, { ...diagForm })
  diagCard.value = resp.data.diagnosis_card
  ElMessage.success('诊断完成')
}

// ---- 执行失败明细 + AI 诊断 (#5c) ----
// 注意: #4 既有诊断弹窗已占用 diagVisible/diagCard/diagForm 等变量名, 本区全部用 aiDiag* 前缀
const lastExecFails = ref([])
const execSessionId = ref(null)
// TODO(#5c T7): 后端 run 响应加 exec_id 后改用后端返回值, 删拼接
const execIdFromSession = (sid) => `exec-${sid.slice(0, 8)}`

const loadExecFails = async () => {
  if (!execSessionId.value) return
  try {
    // axios baseURL 已含 /api/v1, url 不能再带 /api/v1 前缀 (否则拼成 /api/v1/api/v1 404)
    const resp = await axios.get(`/reports/records/${execIdFromSession(execSessionId.value)}/details?status=fail`)
    lastExecFails.value = resp.data?.data ?? []
  } catch { lastExecFails.value = [] }
}

const openExecDiagnose = (row) => {
  openAiDiagnose({ ...row, execId: execIdFromSession(execSessionId.value) })
}

// ---- AI 诊断 (#5c): 弹窗状态/分析/应用 (与 #4 diag* 变量隔离) ----
const aiDiagVisible = ref(false)
const aiDiagLoading = ref(false)
const aiApplying = ref(false)
const aiDiagCard = ref(null)
const aiDiagRow = ref(null)

const openAiDiagnose = async (row) => {
  aiDiagRow.value = row
  aiDiagCard.value = null
  aiDiagVisible.value = true
  aiDiagLoading.value = true
  try {
    const resp = await diagnosticsAPI.analyze(row.execId, row.step)
    aiDiagCard.value = resp.data?.card ?? resp.data
    ElMessage.success('诊断完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '诊断失败')
    aiDiagVisible.value = false
  } finally {
    aiDiagLoading.value = false
  }
}

const onAiApply = async () => {
  if (!aiDiagCard.value?.new_locator || !aiDiagRow.value?.script_id) return
  aiApplying.value = true
  try {
    await diagnosticsAPI.apply({
      script_id: aiDiagRow.value.script_id,
      project_id: form.projectId,
      element_name: aiDiagCard.value.element_name ?? aiDiagRow.value.element_name ?? '',
      new_locator: aiDiagCard.value.new_locator,
      confidence: aiDiagCard.value.confidence,
    })
    ElMessage.success('已回写元素库（source=ai_fixed），可重跑验证')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '应用修复失败')
  } finally {
    aiApplying.value = false
  }
}

const rerunHint = () => {
  aiDiagVisible.value = false
  ElMessage.info('请到脚本库或转脚本页重跑该脚本验证修复效果')
}

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
})
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-label { color: #909399; font-size: 13px; }
.stat-value { font-size: 26px; font-weight: 600; margin-top: 6px; }
.stat-pass .stat-value { color: #67c23a; }
.stat-fail .stat-value { color: #f56c6c; }
.stat-never .stat-value { color: #909399; }
.stat-rate .stat-value { color: #409eff; }
.lib-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.run-cfg-label { color: #909399; font-size: 13px; margin-left: 8px; }
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.diag-card { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.fail-list { margin-top: 12px; padding: 8px 12px; background: #fef0f0; border-radius: 4px; }
.fail-title { font-size: 13px; color: #f56c6c; margin-bottom: 6px; }
.fail-row { display: flex; justify-content: space-between; align-items: center; padding: 2px 0; font-size: 13px; }
</style>
