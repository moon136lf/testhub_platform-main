<template>
  <div class="review-center page-container" v-loading="loading">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>用例评审与 E2E 精修</h2>
        <div class="page-subtitle">评审定稿用例，触发 AI 精修并应用建议</div>
      </div>
    </div>

    <el-card shadow="never">

      <!-- ① 筛选 -->
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable style="width: 220px" @change="loadAll">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审状态">
          <!-- 后端 CaseFilterParams 无 review_status 筛选，前端 computed 过滤 -->
          <el-select v-model="reviewFilter" clearable style="width: 140px">
            <el-option label="待评审" value="pending" />
            <el-option label="已通过" value="passed" />
            <el-option label="需修改" value="needs_revision" />
          </el-select>
        </el-form-item>
      </el-form>

      <!-- ② 汇总统计 -->
      <el-row :gutter="16" style="margin-bottom: 16px" v-if="stats">
        <el-col :span="5"><div class="stat"><div class="num">{{ stats.total_cases }}</div><div class="lbl">总用例</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num">{{ stats.review_status.pending || 0 }}</div><div class="lbl">待评审</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num pass">{{ stats.review_status.passed || 0 }}</div><div class="lbl">已通过</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num fail">{{ stats.review_status.needs_revision || 0 }}</div><div class="lbl">需修改</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="num rate">{{ stats.automation_rate }}%</div><div class="lbl">可自动化率</div></div></el-col>
      </el-row>
      <el-progress v-if="stats" :percentage="stats.automation_rate" :stroke-width="8"
        :format="() => `可自动化 ${stats.automation_rate}%`" style="margin-bottom: 16px" />

      <!-- ③ 用例列表 + 批量 -->
      <div style="margin-bottom: 12px">
        <el-button type="primary" size="small" :disabled="!selected.length" :loading="refining"
          @click="onBatchRefine">批量精修（{{ selected.length }}）</el-button>
        <el-button size="small" :disabled="!selected.length" @click="reviewDialog = true">批量评审</el-button>
      </div>
      <el-table :data="filteredCases" border @selection-change="s => selected = s">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="用例名" min-width="180" show-overflow-tooltip />
        <el-table-column label="评审状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.review_status)">{{ statusLabel(row.review_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可行性" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.feasibility_level" size="small">{{ row.feasibility_level }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="精修评分" width="90">
          <template #default="{ row }">{{ row.refinement_report?.score ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="onRefine(row)">精修</el-button>
            <el-button link @click="onApply(row)">应用建议</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- ④ 项目级精修报告 -->
      <el-card shadow="never" style="margin-top: 16px" v-if="report && report.suggestions.length">
        <template #header>
          <div style="display:flex;justify-content:space-between">
            <span>E2E精修报告（{{ report.case_count }} 个用例已精修<template v-if="report.refined_at">，{{ report.refined_at }}</template>）</span>
            <el-button type="primary" size="small" @click="onApplyAll">应用全部建议</el-button>
          </div>
        </template>
        <el-table :data="report.suggestions" border>
          <el-table-column prop="case_name" label="用例" width="160" show-overflow-tooltip />
          <el-table-column prop="dimension" label="维度" width="120" />
          <el-table-column prop="issue" label="问题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="suggestion" label="建议" min-width="180" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" link type="primary"
                @click="onApplyOne(row)">确认</el-button>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-card>

    <!-- 批量评审弹窗 -->
    <el-dialog v-model="reviewDialog" title="批量评审" width="420px">
      <el-form label-width="80px">
        <el-form-item label="评审状态">
          <el-select v-model="batchStatus" style="width: 100%">
            <el-option label="通过" value="passed" />
            <el-option label="需修改" value="needs_revision" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审意见">
          <el-input v-model="batchComment" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" @click="onBatchReview">应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { reviewAPI } from '@/api/review.js'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const refining = ref(false)
const projects = ref([])
const projectId = ref('')
const reviewFilter = ref('')
const stats = ref(null)
const report = ref(null)
const cases = ref([])
const selected = ref([])
const reviewDialog = ref(false)
const batchStatus = ref('passed')
const batchComment = ref('')

const statusTag = (s) => ({ passed: 'success', needs_revision: 'danger', pending: 'info' }[s] || 'info')
const statusLabel = (s) => ({ passed: '已通过', needs_revision: '需修改', pending: '待评审' }[s] || s || '待评审')

// 评审状态筛选在前端做（后端列表接口无 review_status 筛选参数）
const filteredCases = computed(() =>
  cases.value.filter(c => !reviewFilter.value || c.review_status === reviewFilter.value)
)

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = Array.isArray(res) ? res : (res?.items || [])
    if (projects.value.length) { projectId.value = projects.value[0].id; loadAll() }
  } catch (e) { console.error(e) }
}

const loadAll = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [s, rp] = await Promise.all([
      reviewAPI.getStats(projectId.value),
      reviewAPI.getRefinementReport(projectId.value),
    ])
    stats.value = s
    report.value = rp
    await loadCases()
  } catch (e) { console.error(e) } finally { loading.value = false }
}

// 列表复用 #3 用例列表 + api 层补齐评审字段（list items 为 CaseResponse 摘要，
// 不含 review_status/feasibility_level/refinement_report，detail 才有）
const loadCases = async () => {
  if (!projectId.value) return
  try {
    cases.value = await reviewAPI.listCasesWithReview(projectId.value)
  } catch (e) { console.error(e) }
}

const onRefine = async (row) => {
  loading.value = true
  try {
    await reviewAPI.refineCase(row.id)
    ElMessage.success('精修完成')
    await loadAll()
  } catch (e) { ElMessage.error('精修失败') } finally { loading.value = false }
}

const onBatchRefine = async () => {
  refining.value = true
  try {
    const results = await reviewAPI.batchRefine(projectId.value, selected.value.map(c => c.id))
    const ok = results.filter(r => !r.error).length
    ElMessage.success(`批量精修完成：${ok}/${results.length} 成功`)
    await loadAll()
  } catch (e) { ElMessage.error('批量精修失败') } finally { refining.value = false }
}

const onBatchReview = async () => {
  try {
    const r = await reviewAPI.batchReview(projectId.value, selected.value.map(c => c.id),
      batchStatus.value, batchComment.value || undefined)
    ElMessage.success(`批量评审：${r.success_count} 成功`)
    reviewDialog.value = false
    await loadAll()
  } catch (e) { ElMessage.error('批量评审失败') }
}

const onApply = async (row) => {
  try {
    await reviewAPI.applySuggestions(row.id)
    ElMessage.success('建议已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') }
}

const onApplyOne = async (row) => {
  try {
    await reviewAPI.applySuggestions(row.case_id, [row.id])
    ElMessage.success('已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') }
}

const onApplyAll = async () => {
  loading.value = true
  try {
    const caseIds = [...new Set(report.value.suggestions.map(s => s.case_id))]
    for (const cid of caseIds) {
      await reviewAPI.applySuggestions(cid)
    }
    ElMessage.success('全部建议已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') } finally { loading.value = false }
}

onMounted(loadProjects)
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}
.stat { text-align: center; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.stat .num { font-size: 22px; font-weight: 600; }
.stat .pass { color: #67c23a; } .stat .fail { color: #f56c6c; } .stat .rate { color: #409eff; }
.stat .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
