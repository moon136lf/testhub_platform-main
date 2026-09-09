<template>
  <el-form ref="formRef" :model="formData" :rules="rules" label-width="120px" class="case-form">
    <el-form-item label="用例名称" prop="name">
      <el-input
        v-model="formData.name"
        placeholder="请输入用例名称"
        maxlength="100"
        show-word-limit
        clearable
      />
    </el-form-item>

    <el-form-item label="所属项目" prop="project_id">
      <el-select
        v-model="formData.project_id"
        placeholder="请选择项目"
        filterable
        clearable
        style="width: 100%"
      >
        <el-option
          v-for="project in projects"
          :key="project.id"
          :label="project.name"
          :value="project.id"
        />
      </el-select>
    </el-form-item>

    <el-form-item label="用例描述" prop="description">
      <el-input
        v-model="formData.description"
        type="textarea"
        placeholder="请输入用例描述（可选）"
        maxlength="1000"
        show-word-limit
        :rows="3"
      />
    </el-form-item>

    <el-form-item label="优先级" prop="priority">
      <el-select v-model="formData.priority" placeholder="请选择优先级">
        <el-option label="P0 - 最高" value="P0" />
        <el-option label="P1 - 高" value="P1" />
        <el-option label="P2 - 中" value="P2" />
        <el-option label="P3 - 低" value="P3" />
      </el-select>
    </el-form-item>

    <el-form-item label="用例类型" prop="case_type">
      <el-select v-model="formData.case_type" placeholder="请选择用例类型">
        <el-option label="功能用例" value="functional" />
        <el-option label="接口用例" value="interface_case" />
      </el-select>
    </el-form-item>

    <el-form-item label="自动化状态" prop="automation_status">
      <el-select v-model="formData.automation_status" placeholder="请选择自动化状态">
        <el-option label="未转化" value="pending" />
        <el-option label="已转脚本" value="converted" />
        <el-option label="部分自动化" value="partial_automated" />
        <el-option label="已自动化" value="automated" />
      </el-select>
    </el-form-item>

    <el-form-item label="前置条件" prop="precondition">
      <el-input
        v-model="formData.precondition"
        type="textarea"
        placeholder="请输入前置条件（可选）"
        maxlength="500"
        show-word-limit
        :rows="2"
      />
    </el-form-item>

    <el-form-item label="预期结果" prop="expected_result">
      <el-input
        v-model="formData.expected_result"
        type="textarea"
        placeholder="请输入最终预期结果（须可断言：URL/文本/状态）"
        maxlength="200"
        show-word-limit
        :rows="2"
      />
    </el-form-item>

    <el-form-item label="标签" prop="tags">
      <el-select
        v-model="formData.tags"
        multiple
        filterable
        allow-create
        placeholder="请输入标签，按回车添加"
        style="width: 100%"
      >
        <el-option
          v-for="tag in commonTags"
          :key="tag"
          :label="tag"
          :value="tag"
        />
      </el-select>
    </el-form-item>

    <el-form-item label="测试步骤" prop="steps" required>
      <CaseStepEditor v-model="formData.steps" />
    </el-form-item>

    <el-form-item>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
      <el-button @click="handleCancel">取消</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import CaseStepEditor from './CaseStepEditor.vue'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({})
  },
  isEdit: {
    type: Boolean,
    default: false
  },
  projects: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['submit', 'cancel', 'update:modelValue'])

const formRef = ref(null)
const submitting = ref(false)
const commonTags = ref(['冒烟测试', '回归测试', '验收测试', '核心流程', '边界测试'])

const formData = ref({
  name: '',
  project_id: '',
  description: '',
  priority: 'P2',
  case_type: 'functional',
  automation_status: 'pending',
  precondition: '',
  tags: [],
  steps: [],
  expected_result: ''
})

const rules = {
  name: [
    { required: true, message: '请输入用例名称', trigger: 'blur' },
    { min: 2, max: 100, message: '长度在 2 到 100 个字符', trigger: 'blur' }
  ],
  project_id: [
    { required: true, message: '请选择项目', trigger: 'change' }
  ],
  priority: [
    { required: true, message: '请选择优先级', trigger: 'change' }
  ],
  case_type: [
    { required: true, message: '请选择用例类型', trigger: 'change' }
  ],
  expected_result: [
    { required: true, message: '请输入预期结果', trigger: 'blur' },
    { max: 200, message: '不超过 200 个字符', trigger: 'blur' }
  ],
  steps: [
    {
      validator: (rule, value, callback) => {
        if (!value || value.length === 0) {
          callback(new Error('请至少添加一个测试步骤'))
        } else {
          const hasEmptyStep = value.some(step => !step.action || !step.expected)
          if (hasEmptyStep) {
            callback(new Error('请完善所有测试步骤的操作和预期结果'))
          } else {
            callback()
          }
        }
      },
      trigger: 'change'
    }
  ]
}

let syncingFromProps = false

watch(() => props.modelValue, (newVal) => {
  if (newVal && Object.keys(newVal).length > 0) {
    syncingFromProps = true
    try {
      formData.value = {
        ...formData.value,
        ...newVal,
        steps: newVal.steps || []
      }
    } finally {
      syncingFromProps = false
    }
  }
}, { immediate: true, deep: true })

watch(formData, (newVal) => {
  // 防递归：由 props 同步引起的变更不再回传，避免 modelValue/formData 两个 deep watch 互相触发死循环
  if (syncingFromProps) return
  emit('update:modelValue', newVal)
}, { deep: true })

const handleSubmit = async () => {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
    submitting.value = true
    emit('submit', formData.value)
  } catch (error) {
    ElMessage.warning('请完善表单信息')
  } finally {
    submitting.value = false
  }
}

const handleCancel = () => {
  emit('cancel')
}

const resetForm = () => {
  formRef.value?.resetFields()
  formData.value = {
    name: '',
    project_id: '',
    description: '',
    priority: 'P2',
    case_type: 'functional',
    automation_status: 'pending',
    precondition: '',
    tags: [],
    steps: [],
    expected_result: ''
  }
}

defineExpose({
  resetForm,
  validate: () => formRef.value?.validate()
})
</script>

<style scoped>
.case-form {
  max-width: 100%;
}

.case-form :deep(.el-form-item__content) {
  /* 测试步骤编辑器占满表单剩余宽度，避免表格被 800px 上限压窄出现横向滚动 */
  flex: 1;
  min-width: 0;
}
</style>
