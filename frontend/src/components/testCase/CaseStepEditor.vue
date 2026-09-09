<template>
  <div class="case-step-editor">
    <div class="editor-header">
      <span class="title">测试步骤</span>
      <el-button type="primary" size="small" :icon="Plus" @click="addStep">添加步骤</el-button>
    </div>

    <el-table :data="steps" border stripe style="width: 100%">
      <el-table-column label="序号" width="60" align="center">
        <template #default="{ $index }">
          {{ $index + 1 }}
        </template>
      </el-table-column>

      <el-table-column label="操作步骤" min-width="180">
        <template #default="{ row }">
          <el-select
            v-model="row.action"
            placeholder="选择或输入动作"
            filterable
            allow-create
            default-first-option
            size="default"
            style="width: 100%"
            @change="emitChange"
          >
            <el-option v-for="a in ACTION_OPTIONS" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </template>
      </el-table-column>

      <el-table-column label="操作目标" min-width="160">
        <template #default="{ row }">
          <el-input
            v-model="row.target"
            :placeholder="targetPlaceholder(row.action)"
            clearable
            @input="emitChange"
          />
        </template>
      </el-table-column>

      <el-table-column label="测试数据" min-width="150">
        <template #default="{ row }">
          <el-input
            v-model="row.data"
            :placeholder="dataPlaceholder(row.action)"
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

      <el-table-column label="操作" width="220" align="center" fixed="right">
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

// 标准动作词表（与后端转脚本/执行引擎约定一致；识别验证码为 OCR 复合动作）
const ACTION_OPTIONS = [
  { label: '点击', value: '点击' },
  { label: '输入', value: '输入' },
  { label: '选择', value: '选择' },
  { label: '勾选', value: '勾选' },
  { label: '打开', value: '打开' },
  { label: '进入', value: '进入' },
  { label: '等待', value: '等待' },
  { label: '断言', value: '断言' },
  { label: '识别验证码', value: '识别验证码' },
]

const targetPlaceholder = (action) => {
  if (action === '识别验证码') return '验证码图片元素（如：图形验证码图片）'
  return '目标元素（可选）'
}

const dataPlaceholder = (action) => {
  if (action === '识别验证码') return '验证码输入框（识别结果填入处）'
  return '测试数据（可选）'
}

let syncingFromProps = false

const steps = ref([...props.modelValue])

watch(() => props.modelValue, (newVal) => {
  // 防递归：父组件回传 update:modelValue 后 props 变化会再次触发本 watch，
  // 同步时打标，避免 steps.value 重新赋值 → emitChange → 父组件更新 → 再次同步的死循环
  if (syncingFromProps) return
  syncingFromProps = true
  try {
    steps.value = [...newVal]
  } finally {
    syncingFromProps = false
  }
}, { deep: true })

const emitChange = () => {
  if (syncingFromProps) return
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
  if (index <= 0) return
  // 原地交换而非整体重赋值：整体替换会重建行对象导致 el-table 重新渲染闪烁，
  // 且在 deep watch 链路上易触发递归更新
  const arr = steps.value
  ;[arr[index - 1], arr[index]] = [arr[index], arr[index - 1]]
  emitChange()
}

const moveDown = (index) => {
  if (index >= steps.value.length - 1) return
  const arr = steps.value
  ;[arr[index + 1], arr[index]] = [arr[index], arr[index + 1]]
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
