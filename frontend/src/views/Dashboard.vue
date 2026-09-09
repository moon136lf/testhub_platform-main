<template>
  <div class="dashboard page-container" v-loading="loading">
    <!-- 页头：欢迎语 + 筛选 -->
    <div class="page-header">
      <div>
        <h2>{{ greeting }}，管理员 👋</h2>
        <div class="page-subtitle">{{ today }}</div>
      </div>
      <div class="header-filters">
        <el-select v-model="selectedProject" placeholder="选择项目" clearable
          style="width: 200px" @change="refreshData">
          <el-option label="全部项目" value="" />
          <el-option v-for="project in projects" :key="project.id"
            :label="project.name" :value="project.id" />
        </el-select>
        <el-select v-model="timeRange" style="width: 120px" @change="refreshData">
          <el-option label="近7天" value="7" />
          <el-option label="近30天" value="30" />
        </el-select>
        <el-button type="primary" :icon="Refresh" @click="refreshData">刷新</el-button>
      </div>
    </div>

    <!-- 6 统计卡：4 核心 + 今日 AI/Token -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="4" v-for="card in statCards" :key="card.label">
        <el-card class="stat-card" shadow="never">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: card.bg, color: card.color }">
              <el-icon><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ card.value }}</div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表行：两个环形图 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">元素类型分布</span></template>
          <div ref="elementChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">用例类型分布</span></template>
          <div ref="caseChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 趋势折线 -->
    <el-card shadow="never">
      <template #header><span class="card-title">AI 调用趋势</span></template>
      <div ref="trendChartRef" class="trend-chart"></div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Refresh, Grid, Document, Check, CircleCheck, DataLine, Coin } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { dashboardAPI } from '@/api/dashboard.js'
import { projectAPI } from '@/api/project.js'
import { CHART_COLORS, CHART_TEXT, CHART_LINE, TOOLTIP_STYLE, AXIS_STYLE, donutPiece, smoothArea } from '@/styles/charts.js'

const selectedProject = ref('')
const timeRange = ref('7')
const projects = ref([])
const loading = ref(false)

const stats = ref({
  elementCount: 0,
  caseCount: 0,
  automatedCount: 0,
  pointCount: 0,
  todayAICalls: 0,
  todayTokens: 0
})

const elementDist = ref([])
const caseDist = ref([])
const aiTrend = ref([])

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '上午好'
  if (h < 18) return '下午好'
  return '晚上好'
})
const today = computed(() => new Date().toLocaleDateString('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
}))

const statCards = computed(() => [
  { label: '入库元素数', value: stats.value.elementCount, icon: Grid, bg: '#EEF2FF', color: '#6366F1' },
  { label: '测试用例数', value: stats.value.caseCount, icon: Document, bg: '#E0F2FE', color: '#0EA5E9' },
  { label: '已自动化数', value: stats.value.automatedCount, icon: Check, bg: '#D1FAE5', color: '#10B981' },
  { label: '测试点数', value: stats.value.pointCount, icon: CircleCheck, bg: '#FEF3C7', color: '#F59E0B' },
  { label: '今日AI调用', value: stats.value.todayAICalls, icon: DataLine, bg: '#F3E8FF', color: '#8B5CF6' },
  { label: '今日Token消耗', value: stats.value.todayTokens, icon: Coin, bg: '#FFE4E6', color: '#EF4444' },
])

const elementChartRef = ref(null)
const caseChartRef = ref(null)
const trendChartRef = ref(null)

let elementChart = null
let caseChart = null
let trendChart = null

// 分布类型英→中映射（元素类型 button/input/link/select/other；用例类型 functional/api）
const TYPE_LABELS = {
  button: '按钮', input: '输入框', link: '链接', select: '下拉框', other: '其他',
  functional: '功能用例', api: '接口用例', unknown: '未知',
}
const distLabel = (t) => TYPE_LABELS[t] || t

const donutOption = (data) => ({
  tooltip: { trigger: 'item', ...TOOLTIP_STYLE,
    formatter: (p) => `${p.name}：${p.value}（${p.percent}%）` },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8,
    textStyle: { color: CHART_TEXT, fontSize: 12 } },
  color: CHART_COLORS,
  series: [donutPiece('dist', data.map(i => ({ value: i.count, name: distLabel(i.type) })),
    String(data.reduce((s, i) => s + i.count, 0)))],
})

const initCharts = () => {
  elementChart?.dispose()
  caseChart?.dispose()
  trendChart?.dispose()

  if (elementChartRef.value) {
    elementChart = echarts.init(elementChartRef.value)
    elementChart.setOption(donutOption(elementDist.value))
  }

  if (caseChartRef.value) {
    caseChart = echarts.init(caseChartRef.value)
    caseChart.setOption(donutOption(caseDist.value))
  }

  if (trendChartRef.value) {
    trendChart = echarts.init(trendChartRef.value)
    trendChart.setOption({
      tooltip: { trigger: 'axis', ...TOOLTIP_STYLE },
      legend: { data: ['调用次数', 'Token消耗'], bottom: 0, icon: 'circle',
        itemWidth: 8, itemHeight: 8, textStyle: { color: CHART_TEXT, fontSize: 12 } },
      grid: { left: 48, right: 56, top: 24, bottom: 48 },
      xAxis: { type: 'category', data: aiTrend.value.map(i => i.date), ...AXIS_STYLE },
      // 双 Y 轴：调用次数与 Token 消耗量级差大（次数几百 vs Token 几十万），
      // 共轴会压成一条横线；左轴次数/右轴 Token 各自缩放
      yAxis: [
        { type: 'value', name: '调用次数', ...AXIS_STYLE,
          nameTextStyle: { color: CHART_TEXT, fontSize: 11, padding: [0, 0, 0, -30] },
          axisLabel: { color: CHART_TEXT, fontSize: 12, width: 44, overflow: 'truncate', hideOverlap: true } },
        { type: 'value', name: 'Token消耗', ...AXIS_STYLE,
          nameTextStyle: { color: CHART_TEXT, fontSize: 11, padding: [0, -30, 0, 0] },
          splitLine: { show: false } },
      ],
      series: [
        smoothArea('调用次数', aiTrend.value.map(i => i.call_count), CHART_COLORS[0], { yAxisIndex: 0 }),
        smoothArea('Token消耗', aiTrend.value.map(i => i.tokens), CHART_COLORS[1], { yAxisIndex: 1 }),
      ],
    })
  }
}

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = Array.isArray(res) ? res : (res?.items || [])
  } catch (e) {
    console.error('load projects failed:', e)
  }
}

const refreshData = async () => {
  loading.value = true
  try {
    const d = await dashboardAPI.getOverview({
      project_id: selectedProject.value || undefined,
      days: Number(timeRange.value) || 7
    })
    stats.value = {
      elementCount: d.stats.element_count,
      caseCount: d.stats.case_count,
      automatedCount: d.stats.automated_count,
      pointCount: d.stats.point_count,
      todayAICalls: d.today.ai_calls,
      todayTokens: d.today.tokens_used
    }
    elementDist.value = d.element_distribution || []
    caseDist.value = d.case_distribution || []
    aiTrend.value = d.ai_trend || []
    await nextTick()
    initCharts()
  } catch (e) {
    console.error('refresh dashboard failed:', e)
  } finally {
    loading.value = false
  }
}

const handleResize = () => {
  elementChart?.resize()
  caseChart?.resize()
  trendChart?.resize()
}

onMounted(async () => {
  await loadProjects()
  await refreshData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  elementChart?.dispose()
  caseChart?.dispose()
  trendChart?.dispose()
})
</script>

<style scoped>
.dashboard {
  padding: 24px;
}

.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}

.header-filters {
  display: flex;
  gap: 12px;
  align-items: center;
}

.stats-row {
  margin-bottom: 16px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  flex-shrink: 0;
}

.stat-info {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--mt-text);
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--mt-text-secondary);
  margin-top: 2px;
}

.chart-row {
  margin-bottom: 16px;
}

.card-title {
  font-weight: 600;
  font-size: 15px;
}

.chart-container {
  width: 100%;
  height: 280px;
}

.trend-chart {
  width: 100%;
  height: 300px;
}
</style>
