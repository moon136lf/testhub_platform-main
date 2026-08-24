<template>
  <div class="case-step-editor">
    <div class="editor-header">
      <span class="title">测试步骤</span>
      <el-button type="primary" size="small" :icon="Plus" @click="addStep">添加步骤</el-button>
    </div>

    <el-table :data="steps" border stripe>
      <el-table-column label="序号" width="80" align="center">
        <template #default="{ $index }">
          {{ $index + 1 }}
        </template>
      </el-table-column>

      <el-table-column label="操作步骤" min-width="200">
        <template #default="{ row }">
          <el-input
            v-model="row.action"
            placeholder="请输入操作步骤"
            clearable
            @input="emitChange"
          />
        </template>
      </el-table-column>

      <el-table-column label="操作目标" min-width="160">
        <template #default="{ row }">
          <el-input
            v-model="row.target"
            placeholder="目标元素（可选）"
            clearable
            @input="emitChange"
          />
        </template>
      </el-table-column>

      <el-table-column label="测试数据" min-width="150">
        <template #default="{ row }">
          <el-input
            v-model="row.data"
            placeholder="测试数据（可选）"
            clearable
            @input="emitChange"
          />
        </template>
      </el-table-column>

      <el-table-column label="预期结果" min-width="200">
        <template #default="{ row }">
          <el-input
            v-model="row.expected"
            placeholder="请输入预期结果"
            clearable
            @input="emitChange"
          />
        </template>
      </el-table-column>

      <el-table-column label="操作" width="180" align="center" fixed="right">
        <template #default="{ $index }">
          <el-button
            type="primary"
            link
            :icon="ArrowUp"
            :disabled="$index === 0"
            @click="moveUp($index)"
          >
            上移
          </el-button>
          <el-button
            type="primary"
            link
            :icon="ArrowDown"
            :disabled="$index === steps.length - 1"
            @click="moveDown($index)"
          >
            下移
          </el-button>
          <el-button
            type="danger"
            link
            :icon="Delete"
            @click="deleteStep($index)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="steps.length === 0" description="暂无测试步骤，请点击上方按钮添加" :image-size="100" />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Plus, ArrowUp, ArrowDown, Delete } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue'])

const steps = ref([...props.modelValue])

watch(() => props.modelValue, (newVal) => {
  steps.value = [...newVal]
}, { deep: true })

const emitChange = () => {
  // W2: step 字段统一为 step（非 step_number），每次变更重排序号
  steps.value.forEach((s, idx) => {
    s.step = idx + 1
  })
  emit('update:modelValue', steps.value)
}

const addStep = () => {
  steps.value.push({
    step: steps.value.length + 1,
    action: '',
    target: '',
    data: '',
    expected: ''
  })
  emitChange()
}

const deleteStep = (index) => {
  steps.value.splice(index, 1)
  emitChange()
}

const moveUp = (index) => {
  if (index === 0) return
  const temp = steps.value[index]
  steps.value[index] = steps.value[index - 1]
  steps.value[index - 1] = temp
  emitChange()
}

const moveDown = (index) => {
  if (index === steps.value.length - 1) return
  const temp = steps.value[index]
  steps.value[index] = steps.value[index + 1]
  steps.value[index + 1] = temp
  emitChange()
}
</script>

<style scoped>
.case-step-editor {
  width: 100%;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.editor-header .title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}
</style>
