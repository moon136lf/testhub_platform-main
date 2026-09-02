<template>
  <div class="case-filter">
    <el-form :model="filterForm" inline>
      <el-form-item label="项目">
        <el-select
          v-model="filterForm.project_id"
          placeholder="全部项目"
          clearable
          filterable
          style="width: 200px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="project in projects"
            :key="project.id"
            :label="project.name"
            :value="project.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="测试点">
        <el-select
          v-model="filterForm.test_point_id"
          placeholder="全部测试点"
          clearable
          filterable
          style="width: 200px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="point in testPoints"
            :key="point.id"
            :label="point.name"
            :value="point.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="优先级">
        <el-select
          v-model="filterForm.priority"
          placeholder="全部优先级"
          clearable
          style="width: 150px"
          @change="handleFilterChange"
        >
          <el-option label="P0 - 最高" value="P0" />
          <el-option label="P1 - 高" value="P1" />
          <el-option label="P2 - 中" value="P2" />
          <el-option label="P3 - 低" value="P3" />
        </el-select>
      </el-form-item>

      <el-form-item label="用例类型">
        <el-select
          v-model="filterForm.case_type"
          placeholder="全部类型"
          clearable
          style="width: 150px"
          @change="handleFilterChange"
        >
          <el-option label="功能用例" value="functional" />
          <el-option label="接口用例" value="interface_case" />
        </el-select>
      </el-form-item>

      <el-form-item label="自动化状态">
        <el-select
          v-model="filterForm.automation_status"
          placeholder="全部状态"
          clearable
          style="width: 150px"
          @change="handleFilterChange"
        >
          <el-option label="未转化" value="pending" />
          <el-option label="已转脚本" value="converted" />
          <el-option label="部分自动化" value="partial_automated" />
          <el-option label="已自动化" value="automated" />
        </el-select>
      </el-form-item>

      <el-form-item label="定稿状态">
        <el-select
          v-model="filterForm.finalized"
          placeholder="全部状态"
          clearable
          style="width: 150px"
          @change="handleFilterChange"
        >
          <el-option label="草稿" value="false" />
          <el-option label="已定稿" value="true" />
        </el-select>
      </el-form-item>

      <el-form-item label="幻觉状态">
        <el-select
          v-model="filterForm.has_hallucination"
          placeholder="全部状态"
          clearable
          style="width: 150px"
          @change="handleFilterChange"
        >
          <el-option label="正常" value="false" />
          <el-option label="存在幻觉" value="true" />
        </el-select>
      </el-form-item>

      <el-form-item label="标签">
        <el-select
          v-model="filterForm.tags"
          placeholder="选择标签"
          multiple
          filterable
          clearable
          style="width: 200px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="tag in commonTags"
            :key="tag"
            :label="tag"
            :value="tag"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="关键词">
        <el-input
          v-model="filterForm.keyword"
          placeholder="搜索用例名称或描述"
          clearable
          style="width: 250px"
          @input="handleKeywordChange"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button :icon="Refresh" @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'

const props = defineProps({
  projects: {
    type: Array,
    default: () => []
  },
  testPoints: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['filter-change'])

const filterForm = ref({
  project_id: '',
  test_point_id: '',
  priority: '',
  case_type: '',
  automation_status: '',
  finalized: '',
  has_hallucination: '',
  tags: [],
  keyword: ''
})

const commonTags = ref(['冒烟测试', '回归测试', '验收测试', '核心流程', '边界测试'])

let keywordTimer = null

const handleFilterChange = () => {
  emitFilters()
}

const handleKeywordChange = () => {
  if (keywordTimer) {
    clearTimeout(keywordTimer)
  }
  keywordTimer = setTimeout(() => {
    emitFilters()
  }, 500)
}

const handleSearch = () => {
  emitFilters()
}

const handleReset = () => {
  filterForm.value = {
    project_id: '',
    test_point_id: '',
    priority: '',
    case_type: '',
    automation_status: '',
    finalized: '',
    has_hallucination: '',
    tags: [],
    keyword: ''
  }
  emitFilters()
}

const emitFilters = () => {
  const filters = {}

  Object.keys(filterForm.value).forEach(key => {
    const value = filterForm.value[key]
    if (value !== '' && value !== null && value !== undefined) {
      if (Array.isArray(value) && value.length === 0) {
        return
      }
      if (key === 'finalized' || key === 'has_hallucination') {
        filters[key] = value === 'true'
      } else {
        filters[key] = value
      }
    }
  })

  emit('filter-change', filters)
}

defineExpose({
  reset: handleReset
})
</script>

<style scoped>
.case-filter {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 4px;
  margin-bottom: 16px;
}

/* 网格布局：每个字段占一列、列宽一致 —— 跨行/跨列的标签才真正对齐
   （flex 换行时各行累计宽度不同，标签 x 位置会随上一列控件宽度漂移） */
.case-filter :deep(.el-form) {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 20px;
  margin-bottom: 0;
}

.case-filter :deep(.el-form-item) {
  margin-right: 0;
  margin-bottom: 0;
  width: 100%;
}

/* 控件填满所在列：标签 84px 固定（theme.css），其余空间归输入框 */
.case-filter :deep(.el-select),
.case-filter :deep(.el-input) {
  width: 100%;
}
</style>
