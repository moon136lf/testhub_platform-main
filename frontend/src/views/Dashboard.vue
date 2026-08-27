<template>
  <div class="dashboard" v-loading="loading">
    <el-card class="filter-card">
      <el-row :gutter="20">
        <el-col :span="6">
          <el-select v-model="selectedProject" placeholder="选择项目" style="width: 100%">
            <el-option label="全部项目" value="" />
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-select v-model="timeRange" placeholder="时间范围" style="width: 100%">
            <el-option label="近7天" value="7" />
            <el-option label="近30天" value="30" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-button type="primary" :icon="Refresh" @click="refreshData">刷新</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon element">
              <el-icon><Grid /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-label">入库元素数</div>
              <div class="stat-value">{{ stats.elementCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon case">
              <el-icon><Document /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-label">测试用例数</div>
              <div class="stat-value">{{ stats.caseCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon automated">
              <el-icon><Check /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-label">已自动化数</div>
              <div class="stat-value">{{ stats.automatedCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon point">
              <el-icon><CircleCheck /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-label">测试点数</div>
              <div class="stat-value">{{ stats.pointCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="token-card">
      <template #header>
        <span>Token消耗统计</span>
      </template>
      <el-row :gutter="20">
        <el-col :span="12">
          <div class="token-stat">
            <span class="token-label">今日AI调用次数：</span>
            <span class="token-value">{{ stats.todayAICalls }}</span>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="token-stat">
            <span class="token-label">今日Token消耗：</span>
            <span class="token-value">{{ stats.todayTokens }}</span>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-row :gutter="20" class="chart-row">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>元素类型分布</span>
          </template>
          <div ref="elementChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>用例类型分布</span>
          </template>
          <div ref="caseChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-card>
      <template #header>
        <span>AI调用趋势</span>
      </template>
      <div ref="trendChartRef" class="trend-chart"></div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { dashboardAPI } from '@/api/dashboard.js'
import { projectAPI } from '@/api/project.js'

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

const elementChartRef = ref(null)
const caseChartRef = ref(null)
const trendChartRef = ref(null)

let elementChart = null
let caseChart = null
let trendChart = null

const initCharts = () => {
  elementChart?.dispose()
  caseChart?.dispose()
  trendChart?.dispose()

  if (elementChartRef.value) {
    elementChart = echarts.init(elementChartRef.value)
    elementChart.setOption({
      tooltip: {
        trigger: 'item'
      },
      legend: {
        orient: 'vertical',
        left: 'left'
      },
      series: [
        {
          type: 'pie',
          radius: '50%',
          data: elementDist.value.map(i => ({ value: i.count, name: i.type }))
        }
      ]
    })
  }

  if (caseChartRef.value) {
    caseChart = echarts.init(caseChartRef.value)
    caseChart.setOption({
      tooltip: {
        trigger: 'item'
      },
      legend: {
        orient: 'vertical',
        left: 'left'
      },
      series: [
        {
          type: 'pie',
          radius: '50%',
          data: caseDist.value.map(i => ({ value: i.count, name: i.type }))
        }
      ]
    })
  }

  if (trendChartRef.value) {
    trendChart = echarts.init(trendChartRef.value)
    trendChart.setOption({
      tooltip: {
        trigger: 'axis'
      },
      legend: {
        data: ['调用次数', 'Token消耗']
      },
      xAxis: {
        type: 'category',
        data: aiTrend.value.map(i => i.date)
      },
      yAxis: {
        type: 'value'
      },
      series: [
        {
          name: '调用次数',
          type: 'line',
          data: aiTrend.value.map(i => i.call_count)
        },
        {
          name: 'Token消耗',
          type: 'line',
          data: aiTrend.value.map(i => i.tokens)
        }
      ]
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
  padding: 20px;
}

.filter-card {
  margin-bottom: 20px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  cursor: pointer;
  transition: all 0.3s;
}

.stat-card:hover {
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.2);
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 20px;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  color: white;
}

.stat-icon.element {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.stat-icon.case {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
}

.stat-icon.automated {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.stat-icon.point {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
}

.stat-info {
  flex: 1;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.token-card {
  margin-bottom: 20px;
}

.token-stat {
  padding: 10px 0;
}

.token-label {
  font-size: 14px;
  color: #606266;
  margin-right: 10px;
}

.token-value {
  font-size: 20px;
  font-weight: bold;
  color: #409eff;
}

.chart-row {
  margin-bottom: 20px;
}

.chart-container {
  width: 100%;
  height: 300px;
}

.trend-chart {
  width: 100%;
  height: 400px;
}
</style>
