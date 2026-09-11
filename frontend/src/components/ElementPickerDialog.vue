<template>
  <el-dialog v-model="visible" title="选择元素" width="640px" destroy-on-close>
    <el-input v-model="query" placeholder="搜索别名/文本" clearable style="margin-bottom: 12px"
      @input="load" />
    <el-collapse v-model="activePages">
      <el-collapse-item v-for="pg in pages" :key="pg.page_id" :title="pg.page_name" :name="pg.page_id">
        <el-table :data="pg.elements" size="small" highlight-current-row @current-change="onPick">
          <el-table-column prop="element_name" label="别名" min-width="140" />
          <el-table-column prop="locator" label="首选定位" min-width="200" show-overflow-tooltip />
          <el-table-column prop="confidence" label="置信度" width="80" />
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </el-dialog>
</template>

<script setup>
// 方案V1：元素绑定选择器（Cypress Selector Playground 思路：候选可见、可切换）
import { ref } from 'vue'
import axios from '@/api/axios'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['pick'])
const props = defineProps({ projectId: { type: String, required: true } })

const pages = ref([])
const query = ref('')
const activePages = ref([])

async function load() {
  // 后端返回 {code:0, data:{pages}}；axios 拦截器不剥包装，取 response.data.data
  const resp = await axios.get('/elements/picker', {
    params: { project_id: props.projectId, q: query.value || undefined },
  })
  pages.value = resp.data?.data?.pages || []
  activePages.value = pages.value.map((p) => p.page_id)
}

function onPick(row) {
  if (!row) return
  emit('pick', row)
  visible.value = false
}

defineExpose({ load })
</script>
