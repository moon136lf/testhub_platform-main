<template>
  <div class="token-dashboard">
    <el-card style="margin-bottom: 16px">
      <template #header><span>Token 成本管理</span></template>
      <el-row :gutter="20" v-loading="loading">
        <el-col :span="12">
          <div class="stat">
            <div class="stat-label">配额使用</div>
            <el-progress :percentage="status.percentage || 0" :color="progressColor" :stroke-width="20" />
            <div class="stat-detail">
              已用 {{ status.used }} / 总额 {{ status.total_quota }}（剩余 {{ status.remaining }}）
            </div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-label">日均消耗</div>
            <div class="stat-value">{{ status.recent_daily_avg }}</div>
            <div class="stat-sub">预估剩余可用 {{ status.estimated_days_remaining ?? '∞' }} 天</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="stat">
            <div class="stat-label">预警阈值</div>
            <div class="stat-value">{{ status.warning_threshold }}%</div>
            <el-tag :type="status.is_warning ? 'danger' : 'success'">
              {{ status.is_warning ? '已触发预警' : '正常' }}
            </el-tag>
          </div>
        </el-col>
      </el-row>

      <el-divider />
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" @change="load" filterable style="width: 240px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="总额度">
          <el-input-number v-model="quotaForm.total_quota" :min="0" />
        </el-form-item>
        <el-form-item label="预警阈值(%)">
          <el-input-number v-model="quotaForm.alert_threshold" :min="0" :max="100" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveQuota">保存配额</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card><template #header><span>按 stage 用量</span></template>
          <div ref="stageChart" style="height: 280px" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card><template #header><span>按 model 用量</span></template>
          <div ref="modelChart" style="height: 280px" />
        </el-card>
      </el-col>
    </el-row>
    <el-card style="margin-top: 16px">
      <template #header><span>按天趋势（近7日）</span></template>
      <div ref="dailyChart" style="height: 300px" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const projects = ref([])
const projectId = ref('')
const status = ref({})
const quotaForm = ref({ total_quota: 100000, alert_threshold: 10 })
const usage = ref({ by_stage: [], by_model: [], daily: [] })
const stageChart = ref(null)
const modelChart = ref(null)
const dailyChart = ref(null)
let charts = {}

const progressColor = (percentage) => {
  if (percentage >= 90) return '#f56c6c'
  if (percentage >= 70) return '#e6a23c'
  return '#67c23a'
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = res.items || res || []
    if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].id
      load()
    }
  } catch (e) {}
}

const load = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [statusRes, quotaRes, usageRes] = await Promise.all([
      systemAPI.tokenStatus(projectId.value),
      systemAPI.getQuota(projectId.value),
      systemAPI.tokenUsage(projectId.value, 7)
    ])
    status.value = statusRes.data || statusRes
    const q = quotaRes.data || quotaRes
    quotaForm.value = { total_quota: q.total_quota, alert_threshold: q.alert_threshold }
    usage.value = usageRes.data || usageRes
    await nextTick()
    renderCharts()
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const renderCharts = () => {
  if (stageChart.value) {
    charts.stage = echarts.init(stageChart.value)
    charts.stage.setOption({
      tooltip: {},
      series: [{ type: 'pie', radius: ['40%', '70%'],
        data: usage.value.by_stage.map(s => ({ name: s.label, value: s.tokens })) }]
    })
  }
  if (modelChart.value) {
    charts.model = echarts.init(modelChart.value)
    charts.model.setOption({
      tooltip: {},
      xAxis: { type: 'category', data: usage.value.by_model.map(m => m.label) },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: usage.value.by_model.map(m => m.tokens) }]
    })
  }
  if (dailyChart.value) {
    charts.daily = echarts.init(dailyChart.value)
    charts.daily.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: usage.value.daily.map(d => d.date) },
      yAxis: { type: 'value' },
      series: [{ type: 'line', smooth: true, data: usage.value.daily.map(d => d.tokens) }]
    })
  }
}

const saveQuota = async () => {
  try {
    await systemAPI.updateQuota(projectId.value, quotaForm.value)
    ElMessage.success('配额已保存')
    load()
  } catch (e) { ElMessage.error('保存失败') }
}

onMounted(loadProjects)
</script>

<style scoped>
.token-dashboard { padding: 20px; }
.stat { text-align: center; }
.stat-label { color: #909399; font-size: 13px; margin-bottom: 8px; }
.stat-value { font-size: 24px; font-weight: 600; color: #303133; }
.stat-detail { margin-top: 8px; color: #606266; font-size: 13px; }
.stat-sub { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
