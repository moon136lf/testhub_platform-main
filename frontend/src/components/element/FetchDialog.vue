<template>
  <el-dialog
    :model-value="modelValue"
    title="一次性抓取页面元素"
    width="720px"
    :close-on-click-modal="false"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <el-form :model="form" label-width="100px">
      <!-- 基础信息 -->
      <el-form-item label="项目" required>
        <el-select v-model="form.project_id" placeholder="选择项目" style="width: 100%" @change="loadLoginState">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="页面URL" required>
        <el-input v-model="form.url" placeholder="请输入目标页面地址，如 http://localhost:3000/" />
      </el-form-item>
      <el-form-item label="用户名">
        <el-input v-model="form.username" placeholder="留空则跳过登录" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" type="password" show-password placeholder="留空则跳过登录" />
      </el-form-item>

      <el-divider content-position="left">过滤配置</el-divider>

      <el-form-item label="文本过滤">
        <el-input
          v-model="form.textFilter"
          placeholder="如: +,X,删除,新增（逗号分隔，元素文本含任一词即保留，留空不过滤）"
        />
      </el-form-item>
      <el-form-item label="类型过滤">
        <el-select v-model="form.typeFilter" multiple placeholder="留空不过滤" style="width: 100%">
          <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
      <el-form-item label="调试模式">
        <el-switch v-model="form.debug_mode" />
        <span class="hint-text">调试模式不过滤，返回全部元素及诊断信息</span>
      </el-form-item>

      <el-divider content-position="left">登录态</el-divider>

      <div class="login-state-card">
        <span v-if="loginStateLoading" class="state-text state-gray">加载登录态中...</span>
        <span v-else-if="!form.project_id" class="state-text state-gray">请先选择项目</span>
        <template v-else>
          <span v-if="loginStatus === 'not_configured'" class="state-text state-gray">
            未配置登录态，可在下方填写账密自动登录
          </span>
          <span v-else-if="loginStatus === 'active'" class="state-text state-green">
            登录态有效 · {{ loginStateInfo.cookie_count || 0 }} Cookie + {{ loginStateInfo.localstorage_count || 0 }} localStorage 项
          </span>
          <span v-else class="state-text state-gray">未配置登录态，可在下方填写账密自动登录</span>
        </template>
      </div>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleStart">抓取元素</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { elementAPI } from '@/api/element'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'start'])

const typeOptions = ['button', 'input', 'select', 'link', 'textarea', 'span']

const form = reactive({
  project_id: '',
  url: '',
  username: '',
  password: '',
  textFilter: '',
  typeFilter: [],
  debug_mode: false
})

const loginStateLoading = ref(false)
const loginStateInfo = ref({})
const loginStatus = ref('not_configured')

const loadLoginState = async () => {
  if (!form.project_id) {
    loginStatus.value = 'not_configured'
    loginStateInfo.value = {}
    return
  }
  loginStateLoading.value = true
  try {
    const res = await elementAPI.loginState(form.project_id)
    loginStateInfo.value = res
    loginStatus.value = res.status || 'not_configured'
  } catch (err) {
    console.error('Failed to load login state:', err)
    loginStateInfo.value = {}
    loginStatus.value = 'not_configured'
  } finally {
    loginStateLoading.value = false
  }
}

// 弹窗打开时预选第一个项目并加载登录态
watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      if (!form.project_id && props.projects.length > 0) {
        form.project_id = props.projects[0].id
      }
      loadLoginState()
    }
  }
)

// 项目切换时重新加载登录态（@change 已绑定，watch 兜底）
watch(() => form.project_id, loadLoginState)

const handleStart = () => {
  if (!form.project_id) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!form.url) {
    ElMessage.warning('请输入页面URL')
    return
  }
  emit('start', {
    project_id: form.project_id,
    url: form.url,
    username: form.username,
    password: form.password,
    text_filter: form.textFilter,
    type_filter: form.typeFilter.join(','),
    debug_mode: form.debug_mode
  })
}
</script>

<style scoped>
.hint-text {
  margin-left: 10px;
  font-size: 12px;
  color: var(--mt-text-secondary, #909399);
}

.login-state-card {
  margin: 0 0 8px 100px;
  padding: 10px 14px;
  border: 1px solid var(--el-color-primary-light-7, #c6e2ff);
  background: var(--el-color-primary-light-9, #ecf5ff);
  border-radius: 6px;
}

.state-text {
  font-size: 13px;
}

.state-gray {
  color: var(--mt-text-secondary, #909399);
}

.state-green {
  color: var(--el-color-success, #67c23a);
}
</style>
