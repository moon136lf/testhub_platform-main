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
      <!-- ============ Tab1 测试集 ============ -->
      <el-tab-pane label="测试集" name="sets">
        <el-card>
          <div class="toolbar">
            <el-select v-model="form.projectId" placeholder="选择项目" style="width: 220px" @change="onProjectChange">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-button :icon="Refresh" @click="loadSets">刷新</el-button>
          </div>

          <div class="sets-layout" v-if="form.projectId">
            <!-- 左：测试集列表 -->
            <div class="set-list">
              <div class="set-list-title">测试集 ({{ sets.length }})</div>
              <div v-for="s in sets" :key="s.id" class="set-item"
                :class="{ active: currentSet?.id === s.id }" @click="selectSet(s)">
                <div class="set-item-name">{{ s.name }}</div>
                <div class="set-item-meta">
                  <el-tag size="small" :type="s.source === 'convert_page' ? 'success' : 'info'">
                    {{ s.source === 'convert_page' ? '转换页' : (s.source || 'manual') }}
                  </el-tag>
                  <span class="meta-text">{{ (s.case_ids || []).length }} 用例</span>
                  <span class="meta-text" v-if="s.pass_rate != null">通过率 {{ s.pass_rate }}%</span>
                </div>
              </div>
              <el-empty v-if="!sets.length" description="暂无测试集" :image-size="60" />
            </div>

            <!-- 右：详情 -->
            <div class="set-detail">
              <el-empty v-if="!currentSet" description="选择左侧测试集查看详情" :image-size="80" />
              <template v-else>
                <div class="detail-head">
                  <h3 class="detail-name">
                    {{ currentSet.name }}
                    <el-tag :type="statusTagType(currentSet.status)" size="small" style="margin-left: 8px">
                      {{ currentSet.status || 'pending' }}
                    </el-tag>
                  </h3>
                  <div class="detail-desc" v-if="currentSet.description">{{ currentSet.description }}</div>
                  <div class="detail-actions">
                    <el-button type="primary" :loading="running" :disabled="currentSet.status === 'running'"
                      @click="runDialogVisible = true">▶ 执行测试集</el-button>
                  </div>
                </div>

                <!-- 用例表 -->
                <el-table :data="setCases" border size="small" style="margin-top: 12px">
                  <el-table-column type="index" label="#" width="55" />
                  <el-table-column prop="name" label="用例名" min-width="240" show-overflow-tooltip />
                  <el-table-column prop="priority" label="优先级" width="90" />
                  <el-table-column label="操作" width="90">
                    <template #default="{ row }">
                      <el-button type="danger" link :loading="removingCaseId === row.id"
                        @click="handleRemoveCase(row)">移除</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <!-- SSE 直播区（执行中显示） -->
                <el-card v-if="execLogs.length || running" style="margin-top: 16px">
                  <h3>执行直播</h3>
                  <el-progress v-if="execLogs.length" :percentage="Math.round((execProgress || 0) * 100)"
                    :status="execProgress >= 1 ? 'success' : undefined" style="margin-bottom: 8px" />
                  <div class="log-box">
                    <div v-for="(msg, i) in execLogs" :key="i" class="log-line">
                      [{{ msg.timestamp }}] {{ msg.content }}
                    </div>
                  </div>
                </el-card>

                <!-- 报告区 -->
                <el-card v-if="report" style="margin-top: 16px">
                  <h3>执行报告</h3>
                  <div class="report-summary">
                    <div class="badge badge-rate">通过率 {{ report.pass_rate ?? 0 }}%</div>
                    <div class="badge">总数 {{ report.record?.total_cases ?? 0 }}</div>
                    <div class="badge badge-pass">通过 {{ report.record?.passed ?? 0 }}</div>
                    <div class="badge badge-fail">失败 {{ report.record?.failed ?? 0 }}</div>
                    <div class="badge">耗时 {{ ((report.record?.duration_ms ?? 0) / 1000).toFixed(1) }}s</div>
                  </div>
                  <el-table :data="report.details || []" border size="small" style="margin-top: 12px">
                    <el-table-column type="index" label="序号" width="55" />
                    <el-table-column label="结果" width="90">
                      <template #default="{ row }">
                        <el-tag :type="row.status === 'pass' ? 'success' : 'danger'" size="small">
                          {{ row.status === 'pass' ? '✅ 通过' : '❌ 失败' }}
                        </el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column label="错误类型" width="120">
                      <template #default="{ row }">{{ errorTypeLabel(row.error_type) }}</template>
                    </el-table-column>
                    <el-table-column label="耗时" width="90">
                      <template #default="{ row }">{{ ((row.duration_ms ?? 0) / 1000).toFixed(1) }}s</template>
                    </el-table-column>
                    <el-table-column label="失败截图" width="140">
                      <template #default="{ row }">
                        <el-image v-if="row.screenshot_url" :src="row.screenshot_url"
                          :preview-src-list="[row.screenshot_url]" fit="cover"
                          style="width: 110px; height: 62px; border-radius: 4px" hide-on-click-modal>
                          <template #error>
                            <div class="img-error">截图加载失败</div>
                          </template>
                        </el-image>
                        <span v-else>-</span>
                      </template>
                    </el-table-column>
                    <el-table-column type="expand" width="40">
                      <template #default="{ row }">
                        <div v-if="row.error_message" class="error-msg-box">{{ row.error_message }}</div>
                        <div v-else style="padding: 8px; color: #909399">无错误信息</div>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-card>
                <el-empty v-else-if="reportLoaded" description="该测试集从未执行" :image-size="60" style="margin-top: 16px" />
              </template>
            </div>
          </div>
          <el-empty v-else description="请先选择项目" :image-size="80" />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab2 脚本库 ============ -->
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
            <span class="run-cfg-label">运行配置：</span>
            <el-checkbox v-model="runConfig.headless">headless</el-checkbox>
            <el-input-number v-model="runConfig.timeout" :min="10" :max="600" controls-position="right" style="width: 110px" />s
            <el-input-number v-model="runConfig.max_failures" :min="1" :max="100" controls-position="right" style="width: 110px" />最大失败
          </div>

          <el-table :data="scripts" border style="margin-top: 12px" @selection-change="onSelectionChange">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="batch_name" label="来源批次" min-width="200" show-overflow-tooltip />
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="last_status" label="上次结果" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.last_status === 'passed'" type="success" size="small">通过</el-tag>
                <el-tag v-else-if="row.last_status === 'failed'" type="danger" size="small">失败</el-tag>
                <el-tag v-else type="info" size="small">{{ row.last_status || 'never_run' }}</el-tag>
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
            <el-table-column prop="locator_source" label="定位来源" width="130" />
            <el-table-column label="操作" width="320">
              <template #default="{ row }">
                <el-button type="primary" link :loading="runningId === row.id" @click="handleRun(row)">运行</el-button>
                <el-button type="primary" link @click="viewScript(row)">查看</el-button>
                <el-button type="primary" link @click="openStepEditor(row)">编辑脚本</el-button>
                <el-button type="success" link :disabled="row.status === 'confirmed'" @click="confirmScript(row)">确认入库</el-button>
                <el-button type="warning" link @click="openDiagnose(row)">调试修复</el-button>
              </template>
            </el-table-column>
          </el-table>
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
      <StepEditor :key="editingScript?.id || 'none'" :initial-steps="toEditorRows(editingScript?.step_mapping)" @save="handleSaveSteps" />
    </el-dialog>

    <!-- 脚本代码弹窗 -->
    <el-dialog v-model="codeVisible" :title="resultName" width="820px">
      <pre class="code-box">{{ resultContent }}</pre>
      <template #footer>
        <el-button @click="codeVisible = false">关闭</el-button>
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { scriptAPI } from '@/api/script'
import { testSetAPI } from '@/api/testSet'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'
import { diagnosticsAPI } from '@/api/diagnostics'
import { toEditorRows } from '@/utils/scriptMapping'
import DiagnosisCard from '@/components/DiagnosisCard.vue'
import StepEditor from '@/components/StepEditor.vue'
import axios from '@/api/axios.js'

const projects = ref([])
const form = reactive({ projectId: '' })

const ERROR_TYPE_MAP = {
  locate_failed: '定位失败',
  timeout: '超时',
  assertion_failed: '断言失败',
  script_error: '脚本错误',
}
const errorTypeLabel = (t) => ERROR_TYPE_MAP[t] || t || '-'
const statusTagType = (s) => ({ pending: 'info', running: 'warning', done: 'success' }[s] || 'info')

// ================= Tab1 测试集 =================
const sets = ref([])
const currentSet = ref(null)
const setCases = ref([])
const report = ref(null)
const reportLoaded = ref(false)
const removingCaseId = ref(null)
const running = ref(false)
const runDialogVisible = ref(false)
const runOpts = reactive({ headless: true, fail_fast: false, timeout: 60 })
const execLogs = ref([])
const execProgress = ref(0)

const loadSets = async () => {
  if (!form.projectId) { sets.value = []; return }
  try {
    const resp = await testSetAPI.listSets(form.projectId)
    sets.value = resp.data || []
  } catch { ElMessage.error('测试集列表加载失败'); sets.value = [] }
}

const loadReport = async (setId) => {
  report.value = null
  reportLoaded.value = false
  try {
    const resp = await testSetAPI.getReport(setId)
    // data 为 null 表示从未执行
    report.value = resp.data || null
  } catch { report.value = null }
  reportLoaded.value = true
}

const loadSetCases = async (setId) => {
  setCases.value = []
  const ids = currentSet.value?.case_ids || []
  if (!ids.length) return
  // testCaseAPI 无批量接口，逐个拉
  const results = await Promise.allSettled(ids.map(id => testCaseAPI.get(id)))
  setCases.value = results
    .filter(r => r.status === 'fulfilled' && r.value)
    .map(r => r.value.data || r.value)
}

const selectSet = async (s) => {
  currentSet.value = s
  report.value = null
  await Promise.all([loadSetCases(s.id), loadReport(s.id)])
}

const handleRemoveCase = async (row) => {
  removingCaseId.value = row.id
  try {
    await testSetAPI.removeCase(currentSet.value.id, row.id)
    ElMessage.success('已移除')
    currentSet.value = { ...currentSet.value, case_ids: (currentSet.value.case_ids || []).filter(id => id !== row.id) }
    await loadSetCases(currentSet.value.id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移除失败')
  } finally { removingCaseId.value = null }
}

// 测试集执行：SSE 直播 + 完成后加载报告
let execES = null
const handleRunSet = async () => {
  if (!currentSet.value) return
  running.value = true
  runDialogVisible.value = false
  try {
    const resp = await testSetAPI.runSet(currentSet.value.id, {
      headless: runOpts.headless, failFast: runOpts.fail_fast, timeout: runOpts.timeout,
    })
    const sessionId = resp.data?.session_id
    if (!sessionId) { ElMessage.error('执行启动失败：无 session_id'); running.value = false; return }
    currentSet.value = { ...currentSet.value, status: 'running' }
    execLogs.value = []
    execProgress.value = 0
    if (execES) execES.close()
    execES = scriptAPI.subscribe(sessionId, (msg) => {
      execLogs.value.push(msg)
      if (typeof msg.progress === 'number') execProgress.value = msg.progress
      if (msg.progress >= 1) {
        execES.close()
        running.value = false
        currentSet.value = { ...currentSet.value, status: 'done' }
        loadSets()
        loadReport(currentSet.value.id)
      }
    }, () => {
      running.value = false
      ElMessage.warning('直播连接中断，请稍后刷新查看报告')
      loadSets()
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '执行启动失败')
    running.value = false
  }
}

const onProjectChange = () => {
  currentSet.value = null
  setCases.value = []
  report.value = null
  reportLoaded.value = false
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
    })
    scripts.value = resp.data || []
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

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
})
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; }
.sets-layout { display: flex; gap: 16px; margin-top: 16px; align-items: flex-start; }
.set-list { width: 300px; flex-shrink: 0; border: 1px solid #ebeef5; border-radius: 4px; padding: 8px; max-height: 640px; overflow-y: auto; }
.set-list-title { font-size: 13px; color: #909399; margin-bottom: 8px; }
.set-item { padding: 8px 10px; border-radius: 4px; cursor: pointer; margin-bottom: 4px; border: 1px solid transparent; }
.set-item:hover { background: #f5f7fa; }
.set-item.active { background: #ecf5ff; border-color: #b3d8ff; }
.set-item-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; }
.set-item-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.meta-text { font-size: 12px; color: #909399; }
.set-detail { flex: 1; min-width: 0; }
.detail-head { padding-bottom: 8px; border-bottom: 1px solid #ebeef5; }
.detail-name { margin: 0 0 6px; font-size: 17px; }
.detail-desc { color: #606266; font-size: 13px; margin-bottom: 10px; }
.detail-actions { margin-top: 6px; }
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.code-box { max-height: 480px; overflow: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; white-space: pre; }
.report-summary { display: flex; gap: 12px; flex-wrap: wrap; }
.badge { padding: 6px 14px; background: #f5f7fa; border-radius: 4px; font-size: 13px; color: #606266; }
.badge-rate { background: #ecf5ff; color: #409eff; font-weight: 600; }
.badge-pass { background: #f0f9eb; color: #67c23a; }
.badge-fail { background: #fef0f0; color: #f56c6c; }
.img-error { width: 110px; height: 62px; display: flex; align-items: center; justify-content: center; background: #f5f7fa; color: #c0c4cc; font-size: 12px; border-radius: 4px; }
.error-msg-box { padding: 10px 14px; background: #fef0f0; color: #c45656; font-size: 13px; border-radius: 4px; white-space: pre-wrap; }
.diag-card { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.lib-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.run-cfg-label { color: #909399; font-size: 13px; margin-left: 8px; }
</style>
