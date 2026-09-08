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
      <div class="head-hint">选择已定稿用例批量转换为 Playwright 脚本；脚本管理与执行请到「UI自动化测试」页。</div>
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

    <!-- Tab：转脚本（脚本库/快速运行已迁移至 UI自动化测试页） -->
    <el-tabs v-model="activeTab" style="margin-top: 16px">
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

          <!-- 页面树 + 用例勾选列表（阶段2：按页面分组勾选） -->
          <div class="case-picker" v-if="form.projectId">
            <div class="case-tree">
              <div class="case-tree-title">页面 / 测试点</div>
              <div class="tree-node" :class="{ active: treeGroup === '' }" @click="treeGroup = ''">
                全部用例 ({{ allCases.length }})
              </div>
              <div v-for="g in caseGroups" :key="g.name" class="tree-node"
                :class="{ active: treeGroup === g.name }" @click="treeGroup = g.name">
                {{ g.name }} ({{ g.cases.length }})
              </div>
            </div>
            <div class="case-list">
              <el-checkbox-group v-model="form.caseIds">
                <div v-for="c in filteredCases" :key="c.id" class="case-item">
                  <el-checkbox :value="c.id">
                    <span>{{ c.name }}</span>
                    <el-tag v-if="c.feasibility_level === 'full'" type="success" size="small" style="margin-left: 6px">可自动化</el-tag>
                    <el-tag v-else-if="c.feasibility_level === 'partial'" type="warning" size="small" style="margin-left: 6px">部分可自动化</el-tag>
                    <el-tag v-else-if="c.feasibility_level === 'manual'" type="info" size="small" style="margin-left: 6px">仅手工</el-tag>
                  </el-checkbox>
                </div>
                <el-empty v-if="!filteredCases.length" description="无用例" :image-size="60" />
              </el-checkbox-group>
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 文字直播区 (转换) -->
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

    <!-- 转换结果弹窗：列出本次转换生成的脚本，可查看代码/编辑/存测试集 -->
    <el-dialog v-model="resultVisible" title="转换结果（脚本库）" width="820px">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
        title="脚本管理（运行/AI诊断/编辑）请到 UI自动化测试页" />
      <el-table :data="resultScripts" border size="small">
        <el-table-column prop="name" label="脚本名" min-width="220" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'generated' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_status" label="上次结果" width="100" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button type="primary" link @click="viewResultCode(row)">看代码</el-button>
            <el-button type="primary" link @click="openStepEditor(row)">编辑脚本</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="success" @click="handleSaveAsTestSet">存为测试集</el-button>
        <el-button @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 步骤化编辑弹窗（StepEditor，阶段2核心件）；key 强制重开时重建组件（重置 rows） -->
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
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { scriptAPI } from '@/api/script'
import { testSetAPI } from '@/api/testSet'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'
import { aiCaseAPI } from '@/api/ai-case'
import { toEditorRows } from '@/utils/scriptMapping'
import StepEditor from '@/components/StepEditor.vue'
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

const onProjectChange = () => {
  loadCases()
  loadScripts()
  loadStats()
  loadPointsAndCases()
  treeGroup.value = ''
}

// ---- 页面树 + 用例勾选（阶段2）----
const allCases = ref([])        // aiCaseAPI.getTestCases 全量（含 point_id/feasibility_level）
const pointsById = ref({})      // point_id → page_name（分组用）
const treeGroup = ref('')       // 当前选中的树节点（''=全部）

const caseGroups = computed(() => {
  const byName = new Map()
  for (const c of allCases.value) {
    const name = (c.point_id && pointsById.value[c.point_id]) || (c.name || '').split('-')[0].split('_')[0] || '未分组'
    if (!byName.has(name)) byName.set(name, [])
    byName.get(name).push(c)
  }
  return [...byName.entries()].map(([name, cases]) => ({ name, cases }))
})

const filteredCases = computed(() => {
  if (!treeGroup.value) return allCases.value
  return caseGroups.value.find(g => g.name === treeGroup.value)?.cases || []
})

const loadPointsAndCases = async () => {
  if (!form.projectId) { allCases.value = []; return }
  try {
    const tcResp = await aiCaseAPI.getTestCases(form.projectId, 0, 1000)
    // 仅展示已定稿用例（与原 loadCases is_finalized 过滤一致；该端点无服务端过滤参数，前端过滤）
    allCases.value = (tcResp.data || []).filter(c => c.is_finalized)
  } catch { allCases.value = [] }
  // 测试点 page_name 用于树分组（点可能已删，容错）
  try {
    const tpResp = await aiCaseAPI.getTestPoints(form.projectId, 0, 1000)
    const map = {}
    for (const p of (tpResp.data || [])) map[p.id] = p.page_name
    pointsById.value = map
  } catch { pointsById.value = {} }
}

const loadCases = async () => {
  if (!form.projectId) return
  const resp = await testCaseAPI.list({ project_id: form.projectId, is_finalized: true })
  finalizedCases.value = resp.items || resp.data?.items || resp || []
}

const loadScripts = async () => {
  if (!form.projectId) { scripts.value = []; return }
  try {
    const resp = await scriptAPI.list({ project_id: form.projectId, include_regression: true })
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
    startSSE(resp.data.session_id, {
      onDone: () => {
        converting.value = false
        ElMessage.success('转换完成，脚本已入脚本库')
        openResultDialog()
      },
      onError: () => { converting.value = false; ElMessage.warning('直播连接中断，结果请到「UI自动化测试」页脚本库查看') }
    })
  } catch (e) { ElMessage.error('转换失败'); converting.value = false }
}

// 转换结果查看弹窗（转换完成后可看每个脚本代码）
const resultVisible = ref(false)
const resultScripts = ref([])

const openResultDialog = async () => {
  await loadScripts()
  // 展示本次转换产生的脚本（按来源批次/最新排序取前 N——转换后脚本名带时间戳，取最新 created）
  const sorted = [...scripts.value].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
  resultScripts.value = sorted.slice(0, Math.max(form.caseIds.length, 1) + 5)
  resultVisible.value = true
}

const resultContent = ref('')
const resultName = ref('')
const viewResultCode = async (row) => {
  try {
    const resp = await axios.get(`/scripts/${row.id}`)
    const d = resp.data?.data || resp.data || {}
    resultName.value = d.name || row.name
    resultContent.value = d.content || ''
  } catch { ElMessage.error('脚本内容加载失败'); return }
  resultVisible.value = false
  codeVisible.value = true
}

const codeVisible = ref(false)

// ---- 步骤化编辑（阶段2 StepEditor；映射逻辑在 utils/scriptMapping.js）----
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

// ---- 存为测试集（阶段2）----
const handleSaveAsTestSet = async () => {
  if (!form.caseIds.length) {
    ElMessage.warning('请先勾选用例（转换时选择的用例）'); return
  }
  try {
    const { value } = await ElMessageBox.prompt('输入测试集名称', '存为测试集', {
      confirmButtonText: '保存', cancelButtonText: '取消', inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    })
    await testSetAPI.createSet(form.projectId, value.trim(), form.caseIds, 'convert_page')
    ElMessage.success('已存为测试集，可在 UI自动化测试页执行')
  } catch (e) {
    if (e === 'cancel' || e?.action === 'cancel') return
    ElMessage.error(e?.response?.data?.detail || '保存测试集失败')
  }
}

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
})
</script>

<style scoped>
.head-hint { color: #909399; font-size: 13px; }
.stat-card { text-align: center; }
.stat-label { color: #909399; font-size: 13px; }
.stat-value { font-size: 26px; font-weight: 600; margin-top: 6px; }
.stat-pass .stat-value { color: #67c23a; }
.stat-fail .stat-value { color: #f56c6c; }
.stat-never .stat-value { color: #909399; }
.stat-rate .stat-value { color: #409eff; }
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.code-box { max-height: 480px; overflow: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; white-space: pre; }
.log-line { margin-bottom: 4px; }
.case-picker { display: flex; gap: 12px; margin-top: 16px; }
.case-tree { width: 220px; flex-shrink: 0; border: 1px solid #ebeef5; border-radius: 4px; padding: 8px; }
.case-tree-title { font-size: 13px; color: #909399; margin-bottom: 8px; }
.tree-node { padding: 5px 8px; border-radius: 4px; font-size: 13px; cursor: pointer; margin-bottom: 2px; }
.tree-node:hover { background: #f5f7fa; }
.tree-node.active { background: #ecf5ff; color: #409eff; }
.case-list { flex: 1; border: 1px solid #ebeef5; border-radius: 4px; padding: 8px; max-height: 420px; overflow-y: auto; }
.case-item { padding: 3px 4px; }
</style>
