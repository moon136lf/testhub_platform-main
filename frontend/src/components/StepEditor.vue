<template>
  <div class="step-editor">
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      每行一个动作：选操作类型 → 填元素定位/参数 → 保存后自动生成 Playwright 脚本。
      「期望值」可选：填了则该步执行后断言文本；「数据库断言」填 SQL（可多行）+ 期望值（DB 比对）。
    </el-alert>

    <el-table :data="rows" border size="small">
      <el-table-column label="#" width="50" align="center">
        <template #default="{ $index }">{{ $index + 1 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-select v-model="row.action" size="small">
            <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="元素（目标）" min-width="220">
        <template #default="{ row }">
          <span v-if="row.action === 'navigate'" class="hint">—</span>
          <template v-else>
            <!-- 绑定态：显示别名+定位；未绑定：红色待选择 tag；点击均可弹选择器 -->
            <el-tag v-if="!row.element_id" type="danger" effect="light" style="cursor:pointer"
              @click="openPicker(row)">待选择</el-tag>
            <div v-else style="cursor:pointer" @click="openPicker(row)">
              <div>{{ row.element_name }}</div>
              <div class="loc-text">{{ row.target }}</div>
            </div>
            <!-- 手填兜底：保留直接改定位的能力 -->
            <el-input v-model="row.target" size="small" style="margin-top:4px"
              placeholder="手动输入定位（可选覆盖）" />
          </template>
        </template>
      </el-table-column>
      <el-table-column v-if="hasCaptcha" label="辅元素" min-width="160">
        <template #default="{ row }">
          <template v-if="row.action === 'input_captcha'">
            <el-tag v-if="!row.extra_element_id" type="danger" effect="light" style="cursor:pointer"
              @click="openPicker(row, true)">待选择</el-tag>
            <div v-else style="cursor:pointer" @click="openPicker(row, true)">
              <div>{{ row.extra_element_name || '辅元素' }}</div>
              <div class="loc-text">{{ row.extra_target }}</div>
            </div>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="值 / SQL（测试数据）" min-width="240">
        <template #default="{ row }">
          <el-input v-if="row.action !== 'assert_db'" v-model="row.value" size="small"
            :placeholder="valuePlaceholder(row.action)" />
          <el-input v-else v-model="row.value" type="textarea" :rows="3" size="small"
            placeholder="SQL，如 SELECT count(*) FROM test_case" />
        </template>
      </el-table-column>
      <el-table-column label="期望值（预期结果）" width="170">
        <template #default="{ row }">
          <!-- 断言期望：所有动作行均可填（非空时执行完该步断言文本）；assert_db 为 DB 比对 -->
          <el-input v-model="row.expected" size="small" placeholder="预期结果" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" align="center">
        <template #default="{ $index }">
          <el-button size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
          <el-button size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
          <el-button size="small" type="danger" link @click="rows.splice($index, 1)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <ElementPickerDialog v-model="pickerVisible" :project-id="projectId" @pick="onPicked" />

    <div style="margin-top: 10px; display: flex; gap: 8px">
      <el-button size="small" @click="addRow">+ 添加步骤</el-button>
      <el-button size="small" type="primary" :disabled="!rows.length" @click="$emit('save', serialize())">
        保存脚本
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import ElementPickerDialog from './ElementPickerDialog.vue'

const props = defineProps({
  title: { type: String, default: '' },
  initialSteps: { type: Array, default: () => [] },  // 从 script.step_mapping 还原
  projectId: { type: String, default: '' },          // 元素选择器数据源项目
})
const emit = defineEmits(['save'])

// 与后端 step_codegen.SUPPORTED_ACTIONS 对齐
const ACTIONS = [
  { value: 'navigate', label: '打开页面' },
  { value: 'click', label: '点击' },
  { value: 'input', label: '输入' },
  { value: 'input_captcha', label: '输入验证码' },
  { value: 'captcha_recognize', label: '识别验证码' },
  { value: 'select', label: '下拉选择' },
  { value: 'wait', label: '等待(秒)' },
  { value: 'assert_text', label: '断言文本' },
  { value: 'assert_visible', label: '断言可见' },
  { value: 'assert_db', label: '数据库断言' },
]

const rows = ref([])

// 元素绑定选择器（方案V1阶段9）
const pickerVisible = ref(false)
const pickerRow = ref(null)
const pickerIsExtra = ref(false)
const hasCaptcha = computed(() => rows.value.some((r) => r.action === 'input_captcha'))
const openPicker = (row, isExtra = false) => {
  pickerRow.value = row
  pickerIsExtra.value = isExtra
  pickerVisible.value = true
}
const onPicked = (el) => {
  if (!pickerRow.value) return
  if (pickerIsExtra.value) {
    Object.assign(pickerRow.value, {
      extra_element_id: el.element_id,
      extra_element_name: el.element_name,
      extra_target: el.locator,
    })
  } else {
    Object.assign(pickerRow.value, {
      element_id: el.element_id,
      element_name: el.element_name,
      target: el.locator,
    })
  }
}

// 还原：initialSteps 兼容 {seq,action,target,value,element_name,expected} 行式结构
watch(() => props.initialSteps, (v) => {
  rows.value = (v || []).map((s, i) => ({
    seq: s.seq || i + 1,
    action: s.action || 'click',
    target: s.target || '',
    value: s.value || '',
    element_name: s.element_name || '',
    expected: s.expected || '',
    // 方案V1绑定溯源字段（保存链路 rows 透传，随 PUT content 带回）
    element_id: s.element_id || '',
    match_level: s.match_level || '',
    match_score: s.match_score ?? null,
    case_step_no: s.case_step_no || null,
    case_target_text: s.case_target_text || '',
    extra_element_id: s.extra_element_id || '',
    extra_element_name: s.extra_element_name || '',
    extra_target: s.extra_target || '',
  }))
}, { immediate: true })

const addRow = () => {
  rows.value.push({ seq: rows.value.length + 1, action: 'click', target: '', value: '', element_name: '', expected: '' })
}

const move = (idx, dir) => {
  const j = idx + dir
  if (j < 0 || j >= rows.value.length) return
  ;[rows.value[idx], rows.value[j]] = [rows.value[j], rows.value[idx]]
  rows.value = rows.value.map((r, i) => ({ ...r, seq: i + 1 }))
}

const valuePlaceholder = (action) => ({
  navigate: 'URL，如 https://x.com/login',
  input: '输入内容',
  select: '选项值',
  wait: '秒数，如 2',
  assert_text: '期望文本',
  assert_visible: '—',
  assert_db: '',
}[action] || '')

const serialize = () => rows.value.map((r, i) => ({ ...r, seq: i + 1 }))
</script>

<style scoped>
.loc-text { color: var(--mt-text-tertiary, #999); font-size: 12px; }
.hint { color: var(--mt-text-tertiary, #999); }
</style>
