<template>
  <div class="exec-list">
    <el-card>
      <template #header><span>执行记录与报告</span></template>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable @change="load" style="width: 240px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="execType" clearable style="width: 160px" @change="load">
            <el-option label="UI回归" value="ui_regression" />
            <el-option label="接口" value="api" />
            <el-option label="白盒" value="whitebox" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间">
          <el-select v-model="days" style="width: 120px" @change="load">
            <el-option label="近7天" :value="7" />
            <el-option label="近30天" :value="30" />
            <el-option label="近90天" :value="90" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-card shadow="never" style="margin-bottom: 16px" v-loading="trendLoading">
        <template #header><span>通过率趋势（近{{ days }}天）</span></template>
        <div ref="trendChart" style="height: 200px" />
      </el-card>

      <el-table :data="records" v-loading="loading" border>
        <el-table-column prop="exec_id" label="执行ID" width="200" />
        <el-table-column prop="exec_type" label="类型" width="100" />
        <el-table-column prop="pass_rate" label="通过率" width="100">
          <template #default="{ row }">{{ row.pass_rate }}%</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="执行时间" width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" link @click="goDetail(row)">查看报告</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
        layout="total, prev, pager, next" @current-change="load" style="margin-top: 16px" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { reportAPI } from '@/api/report.js'
import { projectAPI } from '@/api/project.js'

const router = useRouter()
const projects = ref([])
const projectId = ref('')
const execType = ref('')
const days = ref(7)
const records = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const trendLoading = ref(false)
const trendChart = ref(null)
let chart = null

const loadProjects = async () => {
  const res = await projectAPI.list()
  projects.value = res.items || res || []
  if (projects.value.length) { projectId.value = projects.value[0].id; load() }
}
const load = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await reportAPI.listRecords({ project_id: projectId.value, exec_type: execType.value, days: days.value, page: page.value, page_size: pageSize.value })
    const d = res.data || res
    records.value = d.items || []
    total.value = d.total || 0
    loadTrend()
  } catch (e) { console.error(e) } finally { loading.value = false }
}
const loadTrend = async () => {
  trendLoading.value = true
  try {
    const res = await reportAPI.getTrend(projectId.value, days.value)
    const items = (res.data || res) || []
    await nextTick()
    if (trendChart.value) {
      if (chart) chart.dispose()
      chart = echarts.init(trendChart.value)
      chart.setOption({
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: items.map(i => i.date) },
        yAxis: { type: 'value', max: 100 },
        series: [{ type: 'line', smooth: true, data: items.map(i => i.pass_rate), areaStyle: {} }]
      })
    }
  } finally { trendLoading.value = false }
}
const goDetail = (row) => router.push(`/reports/${row.exec_id}`)
onMounted(loadProjects)
onBeforeUnmount(() => { if (chart) chart.dispose() })
</script>
<style scoped>.exec-list { padding: 20px; }</style>
