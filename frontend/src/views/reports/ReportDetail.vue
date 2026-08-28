<template>
  <div class="report-detail" v-loading="loading">
    <el-card v-if="detail">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>报告详情：{{ detail.record.exec_id }}</span>
          <div>
            <el-button type="primary" size="small" :loading="generating" @click="generate(false)">生成报告</el-button>
            <el-button size="small" @click="generate(true)">重新生成</el-button>
            <el-button size="small" @click="exportReport('html')">导出HTML</el-button>
            <el-button size="small" @click="exportReport('pdf')">导出PDF</el-button>
          </div>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="5"><div class="stat"><div class="num">{{ detail.record.total_cases }}</div><div class="lbl">总用例</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num pass">{{ detail.record.passed_count }}</div><div class="lbl">通过</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num fail">{{ detail.record.fail_count }}</div><div class="lbl">失败</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num rate">{{ detail.record.pass_rate }}%</div><div class="lbl">通过率</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="num">{{ detail.record.tokens_used }}</div><div class="lbl">Token</div></div></el-col>
      </el-row>
      <el-descriptions :column="2" border style="margin-top: 16px">
        <el-descriptions-item label="类型">{{ detail.record.exec_type }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.record.status }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ detail.record.duration_ms }}ms</el-descriptions-item>
        <el-descriptions-item label="失败步骤数">{{ detail.fail_step_count }}</el-descriptions-item>
        <el-descriptions-item label="执行时间">{{ detail.record.started_at }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ detail.record.finished_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top: 16px" v-if="detail && detail.details.length">
      <template #header><span>失败步骤明细</span></template>
      <el-table :data="detail.details" border>
        <el-table-column prop="step" label="步骤" width="80" />
        <el-table-column prop="action" label="动作" width="120" />
        <el-table-column prop="error_type" label="错误类型" width="150">
          <template #default="{ row }"><el-tag type="danger" size="small">{{ row.error_type }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="error_msg" label="错误信息" min-width="200" show-overflow-tooltip />
        <el-table-column label="截图" width="120">
          <template #default="{ row }">
            <el-image v-if="row.screenshot_url" :src="row.screenshot_url" :preview-src-list="[row.screenshot_url]" style="width: 80px" />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="堆栈" width="100">
          <template #default="{ row }">
            <el-popover v-if="row.stack_trace" trigger="click" width="600">
              <pre style="max-height: 300px; overflow: auto">{{ row.stack_trace }}</pre>
              <template #reference><el-button link>查看</el-button></template>
            </el-popover>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="诊断" width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDiagnose(row)">AI诊断</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="diagVisible" title="AI 诊断" width="640px">
      <div v-loading="diagLoading">
        <DiagnosisCard v-if="diagCard" :card="diagCard" :applying="applying" @apply="onApply" />
        <el-empty v-else-if="!diagLoading" description="暂无诊断结果" />
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="success" :disabled="!diagCard || !diagCard.new_locator" @click="rerunHint">
          重跑验证
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reportAPI } from '@/api/report.js'
import { diagnosticsAPI } from '@/api/diagnostics.js'
import DiagnosisCard from '@/components/DiagnosisCard.vue'
import axios from '@/api/axios.js'

const route = useRoute()
const loading = ref(false)
const generating = ref(false)
const detail = ref(null)

const load = async () => {
  loading.value = true
  try {
    const res = await reportAPI.getDetail(route.params.execId)
    detail.value = res.data || res
  } catch (e) { ElMessage.error('加载失败') } finally { loading.value = false }
}
const generate = async (force) => {
  generating.value = true
  try {
    await reportAPI.generateReport(route.params.execId, force)
    ElMessage.success(force ? '已重新生成' : '已生成')
    load()
  } catch (e) { ElMessage.error('生成失败') } finally { generating.value = false }
}
const exportReport = (format) => {
  window.location = axios.defaults.baseURL + reportAPI.exportUrl(route.params.execId, format)
}

// ---- AI 诊断 (#5c) ----
const diagVisible = ref(false)
const diagLoading = ref(false)
const applying = ref(false)
const diagCard = ref(null)
const diagRow = ref(null)

const openDiagnose = async (row) => {
  diagRow.value = row
  diagCard.value = null
  diagVisible.value = true
  diagLoading.value = true
  try {
    const resp = await diagnosticsAPI.analyze(route.params.execId, row.step, null, row.id)
    diagCard.value = resp.data?.card ?? resp.data
    ElMessage.success('诊断完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '诊断失败')
    diagVisible.value = false
  } finally {
    diagLoading.value = false
  }
}

const onApply = async () => {
  if (!diagCard.value?.new_locator || !diagRow.value?.script_id) return
  applying.value = true
  try {
    await diagnosticsAPI.apply({
      script_id: diagRow.value.script_id,
      project_id: detail.value?.record?.project_id,
      element_name: diagCard.value.element_name ?? diagRow.value.element_name ?? '',
      new_locator: diagCard.value.new_locator,
      confidence: diagCard.value.confidence,
    })
    ElMessage.success('已回写元素库（source=ai_fixed），可重跑验证')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '应用修复失败')
  } finally {
    applying.value = false
  }
}

const rerunHint = () => {
  diagVisible.value = false
  window.open('/reports', '_blank')  // 重跑走脚本库页（SCRIPT-03 入口）
  ElMessage.info('请到脚本库或转脚本页重跑该脚本验证修复效果')
}
onMounted(load)
</script>
<style scoped>
.report-detail { padding: 20px; }
.stat { text-align: center; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.stat .num { font-size: 22px; font-weight: 600; } .stat .pass { color: #67c23a; }
.stat .fail { color: #f56c6c; } .stat .rate { color: #409eff; }
.stat .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
