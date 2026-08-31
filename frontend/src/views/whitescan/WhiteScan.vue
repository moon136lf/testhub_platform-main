<template>
  <div class="whitescan" v-loading="loading">
    <el-card>
      <template #header><span>白盒测试</span></template>

      <!-- ① 扫描入口 -->
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable style="width: 220px" @change="loadScans">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库URL">
          <el-input v-model="repoUrl" placeholder="https://git.example/repo.git" style="width: 320px" />
        </el-form-item>
        <el-form-item label="分支">
          <el-input v-model="branch" placeholder="main" style="width: 120px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanning" @click="onScan">开始扫描</el-button>
        </el-form-item>
      </el-form>

      <!-- ② 扫描记录 + 概览 -->
      <el-table :data="scans" border style="margin-bottom: 16px" highlight-current-row
        @current-change="onScanSelect">
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="repo_url" label="仓库" min-width="200" show-overflow-tooltip />
        <el-table-column prop="branch" label="分支" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="{ done: 'success', failed: 'danger' }[row.status] || 'info'">{{ { done: '已完成', failed: '失败', scanning: '扫描中' }[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_issues" label="问题" width="70" />
        <el-table-column label="高/中/低" width="100">
          <template #default="{ row }">{{ row.high_count }}/{{ row.mid_count }}/{{ row.low_count }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onGenerateCases(row)">生成回归用例</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- ③ 问题列表 -->
      <template v-if="currentScan">
        <el-form inline style="margin-bottom: 8px">
          <el-form-item label="等级">
            <el-select v-model="sevFilter" clearable style="width: 110px" @change="loadIssues">
              <el-option label="高危" value="high" /><el-option label="中危" value="mid" /><el-option label="低危" value="low" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="statusFilter" clearable style="width: 110px" @change="loadIssues">
              <el-option label="待处理" value="open" /><el-option label="已修复" value="fixed" /><el-option label="误报" value="false_positive" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-table :data="issues" border>
          <el-table-column label="等级" width="70">
            <template #default="{ row }">
              <el-tag :type="{ high: 'danger', mid: 'warning', low: 'info' }[row.severity]">{{ row.severity }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="文件" min-width="220">
            <template #default="{ row }">{{ row.file_path }}:{{ row.line_no }}</template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">{{ statusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onAiFix(row)">AI修复</el-button>
              <el-button link size="small" @click="onMark(row, 'fixed')">标记已修复</el-button>
              <el-button link size="small" @click="onMark(row, 'false_positive')">误报</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- ④ 产出物下载 -->
      <div style="margin-top: 16px" v-if="currentScan">
        <el-button size="small" @click="onExport('xlsx')">下载BUG清单</el-button>
        <el-button size="small" @click="onExport('md')">下载Markdown清单</el-button>
      </div>
    </el-card>

    <!-- AI 修复弹窗 -->
    <el-dialog v-model="fixDialog" title="AI 修复建议" width="640px">
      <template v-if="fixing">
        <p><b>修复思路：</b>{{ fixing.ai_suggestion?.suggestion }}</p>
        <p><b>原代码：</b></p>
        <pre class="code-block">{{ fixing.ai_suggestion?.original_code }}</pre>
        <p><b>修复后：</b></p>
        <pre class="code-block">{{ fixing.ai_suggestion?.fixed_code }}</pre>
      </template>
      <template #footer>
        <el-button @click="fixDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { whitescanAPI } from '@/api/whitescan.js'
import { projectAPI } from '@/api/project.js'
import axios from '@/api/axios.js'

// 时间格式化: 年月日时分秒
const fmtTime = (v) => {
  if (!v) return '—'
  const d = new Date(v)
  if (isNaN(d.getTime())) return v
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const loading = ref(false)
const scanning = ref(false)
const projects = ref([])
const projectId = ref('')
const repoUrl = ref('')
const branch = ref('main')
const scans = ref([])
const currentScan = ref(null)
const issues = ref([])
const sevFilter = ref('')
const statusFilter = ref('')
const fixDialog = ref(false)
const fixing = ref(null)
let pollTimer = null

const statusLabel = (s) => ({ open: '待处理', fixed: '已修复', false_positive: '误报' }[s] || s)

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = Array.isArray(res) ? res : (res?.items || [])
    if (projects.value.length) { projectId.value = projects.value[0].id; loadScans() }
  } catch (e) { console.error(e) }
}

const loadScans = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await whitescanAPI.listScans(projectId.value)
    const d = res.data || res
    scans.value = d.items || []
  } catch (e) { console.error(e) } finally { loading.value = false }
}

const loadIssues = async () => {
  if (!currentScan.value) return
  try {
    const params = {}
    if (sevFilter.value) params.severity = sevFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await whitescanAPI.listIssues(currentScan.value.id, params)
    issues.value = (res.data || res) || []
  } catch (e) { console.error(e) }
}

const onScanSelect = async (row) => {
  currentScan.value = row
  if (row) await loadIssues()
}

const onScan = async () => {
  if (!projectId.value || !repoUrl.value) { ElMessage.warning('选择项目并填写仓库URL'); return }
  scanning.value = true
  try {
    const res = await whitescanAPI.triggerScan(projectId.value, repoUrl.value, branch.value || 'main')
    ElMessage.success('扫描已提交，异步执行中')
    // poll scan status every 3s until done/failed; clear on unmount to avoid leak
    const sid = (res.data || res).scan_id
    stopPolling()
    pollTimer = setInterval(async () => {
      try {
        const res = await whitescanAPI.getScan(sid)
        const s = res.data || res
        if (s.status !== 'scanning') {
          stopPolling()
          scanning.value = false
          s.status === 'done' ? ElMessage.success(`扫描完成：${s.total_issues} 个问题`) : ElMessage.error('扫描失败')
          loadScans()
        }
      } catch (e) { console.error(e) }
    }, 3000)
  } catch (e) { ElMessage.error('提交失败'); scanning.value = false }
}

const onAiFix = async (row) => {
  loading.value = true
  try {
    const res = await whitescanAPI.aiFix(row.id, projectId.value)
    fixing.value = res.data || res
    fixDialog.value = true
  } catch (e) { ElMessage.error('AI修复失败') } finally { loading.value = false }
}

const onMark = async (row, status) => {
  try {
    await whitescanAPI.updateIssue(row.id, status)
    ElMessage.success('已更新')
    loadIssues()
  } catch (e) { ElMessage.error('更新失败') }
}

const onGenerateCases = async (row) => {
  loading.value = true
  try {
    const res = await whitescanAPI.generateCases(row.id, projectId.value)
    const d = res.data || res
    ElMessage.success(`生成 ${d.generated_count} 条，跳过 ${d.skipped_count} 条`)
  } catch (e) { ElMessage.error('生成失败') } finally { loading.value = false }
}

const onExport = (format) => {
  window.location = axios.defaults.baseURL + whitescanAPI.exportUrl(currentScan.value.id, format)
}

onMounted(loadProjects)
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.whitescan { padding: 20px; }
.code-block { background: #f5f7fa; padding: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow: auto; white-space: pre-wrap; }
</style>
