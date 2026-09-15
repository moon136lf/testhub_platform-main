<template>
  <div class="page-container">
    <el-card class="header-card">
      <div class="page-header">
        <div>
          <h2 class="page-title">UI自动化测试</h2>
          <div class="page-subtitle">测试集规划与执行 · 失败截图自动留存</div>
        </div>
      </div>
    </el-card>

    <el-tabs v-model="activeTab" style="margin-top: 16px">
      <!-- ============ Tab1 脚本库 ============ -->
      <el-tab-pane label="脚本库" name="library">
        <el-card>
          <div class="lib-toolbar">
            <el-select v-model="filter.category" placeholder="分类筛选" clearable style="width: 160px" @change="loadScripts">
              <el-option v-for="c in CATEGORIES" :key="c.value" :label="c.label" :value="c.value" />
            </el-select>
            <el-input v-model="filter.keyword" placeholder="关键词搜索脚本名" clearable style="width: 220px" @change="loadScripts" />
            <el-button @click="loadScripts" :icon="Refresh">刷新</el-button>
            <el-button type="warning" :disabled="!selected.length" :loading="batching" @click="handleBatchRun">
              批量运行 ({{ selected.length }})
            </el-button>
            <el-button type="success" @click="quickVisible = true">⚡ 快速运行</el-button>
            <span class="run-cfg-label">运行配置：</span>
            <el-checkbox v-model="runConfig.headless">headless</el-checkbox>
            <el-input-number v-model="runConfig.timeout" :min="10" :max="600" controls-position="right" style="width: 110px" />s
            <el-input-number v-model="runConfig.max_failures" :min="1" :max="100" controls-position="right" style="width: 110px" />最大失败
          </div>

          <el-table :data="scripts" stripe style="margin-top: 12px" @selection-change="onSelectionChange">
            <el-table-column type="selection" width="45" />
            <el-table-column label="名称" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span :title="row.name">{{ row.bound_case || row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="来源批次" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.batch_name || '—' }}</template>
            </el-table-column>
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">{{ SCRIPT_STATUS_CN[row.status] || row.status }}</template>
            </el-table-column>
            <el-table-column prop="last_status" label="上次结果" width="100">
              <template #default="{ row }">
                <el-tag :type="LAST_STATUS_TAG[row.last_status] || 'info'" size="small">
                  {{ LAST_STATUS_CN[row.last_status] || row.last_status || '未运行' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="AI建议" width="90">
              <template #default="{ row }">
                <el-tooltip v-if="row.ai_reason" :content="row.ai_reason">
                  <el-tag :type="row.ai_suggested ? 'warning' : 'info'" size="small">{{ row.ai_suggested ? '是' : '否' }}</el-tag>
                </el-tooltip>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="是否纳入" width="100">
              <template #default="{ row }">
                <el-tag :type="row.actual_included ? 'success' : 'info'" size="small">{{ row.actual_included ? '已纳入' : '未纳入' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="run_count" label="运行次数" width="90" />
            <el-table-column prop="locator_source" label="定位来源" width="110">
              <template #default="{ row }">{{ LOCATOR_SOURCE_CN[row.locator_source] || row.locator_source }}</template>
            </el-table-column>
            <el-table-column label="绑定用例" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.bound_case || '—' }}</template>
            </el-table-column>
            <el-table-column label="被引用" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.test_set_refs" type="warning" size="small">{{ row.test_set_refs }} 个测试集</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="320">
              <template #default="{ row }">
                <el-button type="primary" link :loading="runningId === row.id" @click="handleRun(row)">运行</el-button>
                <el-button type="primary" link @click="viewScript(row)">查看</el-button>
                <el-button type="primary" link @click="openStepEditor(row)">编辑脚本</el-button>
                <el-button type="primary" link :disabled="row.status === 'confirmed'" @click="confirmScript(row)">确认入库</el-button>
                <el-button type="primary" link @click="openDiagnose(row)">调试修复</el-button>
                <el-button v-if="row.last_status === 'failed'" type="primary" link
                  :loading="diagLoadingId === row.id" @click="handleAiDiagnose(row)">诊断</el-button>
                <el-button type="danger" link @click="delScript(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination style="margin-top: 12px" v-model:current-page="scriptPage" :page-size="scriptPageSize"
            :total="scriptTotal" layout="total, prev, pager, next" @current-change="loadScripts" />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab2 测试集 ============ -->
      <el-tab-pane label="测试集" name="sets">
        <el-card>
          <div class="toolbar">
            <el-select v-model="form.projectId" placeholder="选择项目" style="width: 220px" @change="onProjectChange">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-input v-model="setFilter" placeholder="测试集名称" clearable style="width: 200px" @input="loadSets" />
            <el-button :icon="Refresh" @click="loadSets">刷新</el-button>
            <el-button type="warning" :loading="identifying" @click="handleIdentify">AI识别回归</el-button>
          </div>

          <el-table v-if="form.projectId" :data="filteredSets" v-loading="loadingSets" stripe style="margin-top: 12px">
            <el-table-column prop="name" label="测试集名称" min-width="220" show-overflow-tooltip />
            <el-table-column label="来源" width="120">
              <template #default="{ row }"><el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="用例数" width="90">
              <template #default="{ row }">{{ (row.case_ids || []).length }}</template>
            </el-table-column>
            <el-table-column label="最近通过率" width="110">
              <template #default="{ row }">{{ row.pass_rate != null ? row.pass_rate + '%' : '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" :type="statusTagType(row.status)">{{ statusCn(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" :disabled="row.status === 'running'" @click="openRunDialog(row)">执行</el-button>
                <el-button link type="primary" size="small" @click="$router.push('/auto/ui/set/' + row.id)">详情</el-button>
                <el-button link type="danger" size="small" @click="delSet(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="请先选择项目" :image-size="80" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 文字直播区（脚本库运行共用） -->
    <el-card v-if="libLogs.length || runningId || batching" style="margin-top: 16px">
      <h3>执行过程文字直播</h3>
      <el-progress v-if="libLogs.length" :percentage="Math.round((libProgress || 0) * 100)"
        :status="libProgress >= 1 ? 'success' : undefined" style="margin-bottom: 8px" />
      <div class="log-box">
        <div v-for="(msg, i) in libLogs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-card>

    <!-- 执行配置弹窗 -->
    <el-dialog v-model="runDialogVisible" title="执行配置" width="440px">
      <el-form label-width="100px">
        <el-form-item label="无头模式">
          <el-checkbox v-model="runOpts.headless">headless（默认开启）</el-checkbox>
        </el-form-item>
        <el-form-item label="失败即停">
          <el-checkbox v-model="runOpts.fail_fast" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="runOpts.timeout" :min="10" :max="600" controls-position="right" style="width: 160px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="running" @click="handleRunSet">开始执行</el-button>
      </template>
    </el-dialog>

    <!-- 步骤化编辑弹窗（StepEditor）；key 强制重开时重建组件（重置 rows） -->
    <el-dialog v-model="stepEditorVisible" :title="`编辑脚本：${editingScript?.name || ''}`" width="900px">
      <StepEditor :key="editingScript?.id || 'none'" :initial-steps="toEditorRows(editingScript?.step_mapping)" :project-id="form.projectId" @save="handleSaveSteps" />
    </el-dialog>

    <!-- 脚本代码弹窗 -->
    <el-dialog v-model="codeVisible" :title="resultName" width="820px">
      <pre class="code-box">{{ resultContent }}</pre>
      <template #footer>
        <el-button @click="codeVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 快速运行弹窗 -->
    <el-dialog v-model="quickVisible" title="⚡ 快速运行" width="760px">
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
      </el-form>
      <template #footer>
        <el-button @click="quickVisible = false">关闭</el-button>
        <el-button type="primary" :loading="quickRunning" @click="handleQuickRun">运行</el-button>
      </template>
    </el-dialog>

    <!-- 调试修复弹窗 -->
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

    <!-- AI 诊断弹窗 -->
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
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { scriptAPI } from '@/api/script'
import { testSetAPI } from '@/api/testSet'
import { projectAPI } from '@/api/project'
import { diagnosticsAPI } from '@/api/diagnostics'
import { toEditorRows } from '@/utils/scriptMapping'
import DiagnosisCard from '@/components/DiagnosisCard.vue'
import StepEditor from '@/components/StepEditor.vue'
import axios from '@/api/axios.js'

const projects = ref([])
const form = reactive({ projectId: '' })

const statusTagType = (s) => ({ pending: 'info', running: 'warning', done: 'success' }[s] || 'info')
const statusCn = (s) => ({ pending: '待执行', running: '执行中', done: '已完成' }[s] || s || '待执行')

// 脚本库枚举中文映射（实际值域：last_status=never_run/passed/failed/affected；
// locator_source=element_library/ai_generated/mixed/none_draft；status=generated/confirmed）
const LAST_STATUS_CN = { never_run: '未运行', passed: '成功', failed: '失败', affected: '受影响' }
const LAST_STATUS_TAG = { never_run: 'info', passed: 'success', failed: 'danger', affected: 'warning' }
const LOCATOR_SOURCE_CN = { element_library: '元素库', ai_generated: 'AI生成', mixed: '混合', none_draft: '草稿' }
const SCRIPT_STATUS_CN = { generated: '已生成', confirmed: '已入库' }

const SOURCE_LABELS = {
  manual: '手工',
  ai_suggest: 'AI建议',
  convert_page: '转换页',
  ai_regression: 'AI识别回归',
  manual_regression: '手工回归',
}
const sourceLabel = (s) => SOURCE_LABELS[s] || s || '手工'
const sourceTagType = (s) => ({ convert_page: 'success', ai_regression: 'warning', manual_regression: 'warning' }[s] || 'info')

// ================= Tab2 测试集 =================
const sets = ref([])
const setFilter = ref('')
const loadingSets = ref(false)
const pendingRunSet = ref(null)
const running = ref(false)
const runDialogVisible = ref(false)
const runOpts = reactive({ headless: true, fail_fast: false, timeout: 60 })

const filteredSets = computed(() => {
  const kw = (setFilter.value || '').trim().toLowerCase()
  if (!kw) return sets.value
  return sets.value.filter(s => (s.name || '').toLowerCase().includes(kw))
})

const loadSets = async () => {
  if (!form.projectId) { sets.value = []; return }
  loadingSets.value = true
  try {
    const resp = await testSetAPI.listSets(form.projectId)
    sets.value = resp.data || []
  } catch { ElMessage.error('测试集列表加载失败'); sets.value = [] }
  finally { loadingSets.value = false }
}

const delSet = async (s) => {
  try {
    await ElMessageBox.confirm(`确定删除测试集「${s.name}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await testSetAPI.deleteSet(s.id)
    ElMessage.success('已删除')
    loadSets()
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

// 行内执行：弹执行配置，确认后启动并提示到详情页看记录
const openRunDialog = (row) => {
  pendingRunSet.value = row
  runDialogVisible.value = true
}

const handleRunSet = async () => {
  if (!pendingRunSet.value) return
  running.value = true
  try {
    await testSetAPI.runSet(pendingRunSet.value.id, {
      headless: runOpts.headless, failFast: runOpts.fail_fast, timeout: runOpts.timeout,
    })
    runDialogVisible.value = false
    ElMessage.success('执行已启动，请到详情页查看记录')
    pendingRunSet.value = { ...pendingRunSet.value, status: 'running' }
    loadSets()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '执行启动失败')
  } finally { running.value = false }
}

const onProjectChange = () => {
  loadSets()
  loadScripts()
}

// ================= Tab2 脚本库 =================
const CATEGORIES = [
  { value: 'uncategorized', label: '未分类' },
  { value: 'ui_smoke', label: 'UI冒烟' },
  { value: 'full_regression', label: '全量回归' },
  { value: 'core_flow', label: '核心流程' },
  { value: 'interface_auto', label: '接口自动化' },
]
const filter = reactive({ category: '', keyword: '' })
const scripts = ref([])
const scriptPage = ref(1)
const scriptPageSize = 20
const scriptTotal = ref(0)
const selected = ref([])
const runningId = ref(null)
const batching = ref(false)
const runConfig = reactive({ headless: true, timeout: 60, max_failures: 8 })
const libLogs = ref([])
const libProgress = ref(0)

const onSelectionChange = (rows) => { selected.value = rows }

const loadScripts = async () => {
  if (!form.projectId) { scripts.value = []; return }
  try {
    const resp = await scriptAPI.list({
      project_id: form.projectId,
      category: filter.category || undefined,
      keyword: filter.keyword || undefined,
      include_regression: true,
      page: scriptPage.value,
      page_size: scriptPageSize,
    })
    scripts.value = resp.data || []
    scriptTotal.value = resp.total ?? (resp.data || []).length
  } catch (e) { ElMessage.error('脚本列表加载失败'); scripts.value = [] }
}

// 脚本库 SSE：单脚本运行 / 批量运行共用
let libES = null
const startLibSSE = (sessionId, { onDone }) => {
  libLogs.value = []
  libProgress.value = 0
  if (libES) libES.close()
  libES = scriptAPI.subscribe(sessionId, (msg) => {
    libLogs.value.push(msg)
    if (typeof msg.progress === 'number') libProgress.value = msg.progress
    if (msg.progress >= 1) {
      libES.close()
      loadScripts()
      onDone?.()
    }
  }, () => {
    runningId.value = null
    batching.value = false
    ElMessage.warning('直播连接中断，结果请刷新列表查看')
  })
}

const handleRun = async (row) => {
  runningId.value = row.id
  try {
    const resp = await scriptAPI.run(row.id, { ...runConfig })
    startLibSSE(resp.data.session_id, { onDone: () => { runningId.value = null } })
  } catch (e) { ElMessage.error('运行失败'); runningId.value = null }
}

const handleBatchRun = async () => {
  if (!selected.value.length) { ElMessage.warning('请勾选脚本'); return }
  batching.value = true
  try {
    const ids = selected.value.map(s => s.id)
    const resp = await scriptAPI.batchRun(ids, { ...runConfig })
    startLibSSE(resp.data.session_id, { onDone: () => { batching.value = false } })
  } catch (e) { ElMessage.error('批量运行失败'); batching.value = false }
}

const viewScript = (row) => { window.open(`/api/v1/scripts/${row.id}`, '_blank') }

const delScript = async (row) => {
  const displayName = row.bound_case || row.name
  const refHint = row.test_set_refs ? `该脚本被 ${row.test_set_refs} 个测试集引用，删除后引用将失效。` : ''
  try {
    await ElMessageBox.confirm(`确定删除脚本「${displayName}」？${refHint}`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await axios.delete(`/scripts/${row.id}`)
    ElMessage.success('已删除')
    loadScripts()
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

const confirmScript = async (row) => {
  await scriptAPI.confirm(row.id)
  ElMessage.success('已确认入库'); loadScripts()
}

// ---- 步骤化编辑（StepEditor）----
const stepEditorVisible = ref(false)
const editingScript = ref(null)

const openStepEditor = (row) => {
  editingScript.value = row
  stepEditorVisible.value = true
}

const handleSaveSteps = async (steps) => {
  try {
    await scriptAPI.saveScriptSteps(editingScript.value.id, editingScript.value.name, steps)
    ElMessage.success('脚本已保存（Playwright 代码已重新生成）')
    stepEditorVisible.value = false
    loadScripts()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
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

// ---- AI 诊断 (#5c) ----
const aiDiagVisible = ref(false)
const aiDiagLoading = ref(false)
const aiApplying = ref(false)
const aiDiagCard = ref(null)
const aiDiagRow = ref(null)

// ---- 快速运行（从 ScriptConvert 迁移）----
const quickVisible = ref(false)
const quickRunning = ref(false)
const quickForm = reactive({ scriptContent: '', targetUrl: '', headless: true })

const handleQuickRun = async () => {
  if (!quickForm.scriptContent || !quickForm.targetUrl) {
    ElMessage.warning('请填写脚本内容和被测URL'); return
  }
  quickRunning.value = true
  try {
    const resp = await scriptAPI.quickRun(quickForm.scriptContent, quickForm.targetUrl, quickForm.headless)
    startLibSSE(resp.data.session_id, { onDone: () => { quickRunning.value = false } })
  } catch (e) { ElMessage.error('快速运行失败'); quickRunning.value = false }
}

// ---- AI 诊断入口（#5c）：last_status=failed 的行可诊断 ----
// 链路：GET /regression/latest-execution?script_id= 反查最近一次执行（exec_id + 失败步骤）→ diagnosticsAPI.analyze
const diagLoadingId = ref(null)

const handleAiDiagnose = async (row) => {
  diagLoadingId.value = row.id
  try {
    const resp = await axios.get('/regression/latest-execution', { params: { script_id: row.id } })
    const data = resp.data?.data || {}
    const record = data.record || {}
    const detail = data.detail || {}
    // latest-execution 只回 step=0 的汇总 detail，失败步骤号从 fail 明细列表第一条取
    let step = detail.step || 0
    let detailId = detail.id || null
    if (record.exec_id) {
      try {
        const dresp = await axios.get(`/reports/records/${record.exec_id}/details?status=fail`)
        const fails = dresp.data?.data || []
        const matched = fails.find(f => f.script_id === row.id) || fails[0]
        if (matched) { step = matched.step || step; detailId = matched.id || detailId }
      } catch { /* 明细拉取失败则退回汇总 detail */ }
    }
    if (!record.exec_id) {
      ElMessage.warning('暂无失败执行记录'); return
    }
    await openAiDiagnose({ execId: record.exec_id, step, id: detailId, script_id: row.id, element_name: row.name })
  } catch (e) {
    if (e?.response?.status === 404) ElMessage.warning('暂无失败执行记录')
    else ElMessage.error(e?.response?.data?.detail || '获取最近执行记录失败')
  } finally {
    diagLoadingId.value = null
  }
}

const openAiDiagnose = async (row) => {
  aiDiagRow.value = row
  aiDiagCard.value = null
  aiDiagVisible.value = true
  aiDiagLoading.value = true
  try {
    const resp = await diagnosticsAPI.analyze(row.execId, row.step, null, row.id)
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
  ElMessage.info('请到脚本库重跑该脚本验证修复效果')
}

// ---- AI识别回归（自 Regression.vue 迁移，阶段10）----
const identifying = ref(false)
const handleIdentify = async () => {
  if (!form.projectId) { ElMessage.warning('请先选择项目'); return }
  identifying.value = true
  try {
    const resp = await axios.post('/regression/identify', { project_id: form.projectId })
    const count = resp.data?.data?.suggested_count ?? resp.data?.data?.count ?? ''
    ElMessage.success(`识别完成${count !== '' ? `，建议纳入 ${count} 个脚本` : ''}`)
    loadScripts()
  } catch (e) { ElMessage.error('识别失败') } finally { identifying.value = false }
}

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
  if (projects.value.length) form.projectId = projects.value[0].id
  // 转脚本页跳转定位：/auto/ui?caseId=xx → 脚本库按用例过滤
  const route = useRoute()
  const router = useRouter()
  const caseId = route.query.caseId
  if (caseId && projects.value.length) {
    activeTab.value = 'library'
    loadScripts()
    try {
      const resp = await scriptAPI.list({ project_id: form.projectId, case_id: caseId, include_regression: true })
      scripts.value = resp.data || []
      scriptTotal.value = resp.total ?? (resp.data || []).length
    } catch { ElMessage.error('脚本定位失败') }
    // 定位完成后清理 query，避免刷新/切换时残留过滤
    router.replace({ query: {} })
  } else if (form.projectId) {
    loadSets(); loadScripts()
  }
})
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; }
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.code-box { max-height: 480px; overflow: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; white-space: pre; }
.diag-card { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.lib-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.run-cfg-label { color: #909399; font-size: 13px; margin-left: 8px; }
</style>
