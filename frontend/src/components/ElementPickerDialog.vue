<template>
  <el-dialog v-model="visible" title="选择元素" width="900px" destroy-on-close>
    <div class="picker-layout">
      <!-- 左侧：页面列表 -->
      <div class="picker-left">
        <div v-for="pg in pages" :key="pg.page_id" class="page-item"
          :class="{ active: pg.page_id === currentPageId }" @click="currentPageId = pg.page_id">
          <span class="page-name">{{ pg.page_name }}</span>
          <el-tag size="small" type="info" effect="plain">{{ (pg.elements || []).length }}</el-tag>
        </div>
        <el-empty v-if="!pages.length" description="无页面数据" :image-size="60" />
      </div>
      <!-- 右侧：当前页面元素表 -->
      <div class="picker-right">
        <el-input v-model="query" placeholder="搜索别名/文本" clearable style="margin-bottom: 8px"
          @input="load" />
        <el-table :data="currentElements" size="small" row-key="element_id">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="strategies" v-if="(row.strategies || []).length">
                <div v-for="(s, i) in row.strategies" :key="i" class="strategy-row">
                  <el-tag size="small">{{ s.type }}</el-tag>
                  <span class="strategy-value">{{ s.value }}</span>
                  <span class="strategy-conf">置信度 {{ s.confidence }}</span>
                </div>
              </div>
              <div v-else class="strategy-empty">暂无定位策略</div>
            </template>
          </el-table-column>
          <el-table-column prop="element_name" label="元素名" min-width="130" show-overflow-tooltip />
          <el-table-column label="首选定位" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ bestLocator(row) }}</template>
          </el-table-column>
          <el-table-column prop="confidence" label="置信度" width="80" />
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="onPick(row)">选择</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="该页面无元素" :image-size="60" />
          </template>
        </el-table>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
// 方案V1：元素绑定选择器（重设计：左页面列表 / 右定位详情表，行展开显示全部定位策略）
import { ref, computed, watch } from 'vue'
import axios from '@/api/axios'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['pick'])
const props = defineProps({ projectId: { type: String, required: true } })

const pages = ref([])
const query = ref('')
const currentPageId = ref('')

const currentElements = computed(() => {
  const pg = pages.value.find((p) => p.page_id === currentPageId.value)
  return pg ? pg.elements || [] : []
})

const bestLocator = (row) => {
  const list = row.strategies || []
  if (!list.length) return row.locator || '—'
  return `${list[0].type}:${list[0].value}`
}

async function load() {
  // 后端返回 {code:0, data:{pages}}；axios 拦截器不剥包装，取 response.data.data
  const resp = await axios.get('/elements/picker', {
    params: { project_id: props.projectId, q: query.value || undefined },
  })
  pages.value = resp.data?.data?.pages || []
  // 保持当前选中页面；否则默认第一页
  if (!pages.value.some((p) => p.page_id === currentPageId.value)) {
    currentPageId.value = pages.value[0]?.page_id || ''
  }
}

function onPick(row) {
  emit('pick', row)
  visible.value = false
}

watch(visible, (v) => {
  if (v) load()
})

defineExpose({ load })
</script>

<style scoped>
.picker-layout { display: flex; gap: 12px; min-height: 320px; }
.picker-left {
  width: 220px; flex-shrink: 0; border-right: 1px solid #ebeef5;
  padding-right: 12px; overflow-y: auto; max-height: 460px;
}
.page-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; border-radius: 4px; cursor: pointer; margin-bottom: 2px;
}
.page-item:hover { background: #f5f7fa; }
.page-item.active { background: #ecf5ff; color: #409eff; }
.page-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.picker-right { flex: 1; overflow-y: auto; max-height: 460px; }
.strategies { padding: 4px 12px; }
.strategy-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.strategy-value { font-family: monospace; font-size: 12px; }
.strategy-conf { color: #999; font-size: 12px; margin-left: auto; }
.strategy-empty { color: #999; padding: 4px 12px; }
</style>
