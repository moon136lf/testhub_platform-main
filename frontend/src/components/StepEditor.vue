<template>
  <div class="step-editor">
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      每行一个动作：选操作类型 → 填元素定位/参数 → 保存后自动生成 Playwright 脚本。
      「数据库断言」填 SQL（可多行）+ 期望值（文本比对）。
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
      <el-table-column label="元素定位 / 参数" min-width="220">
        <template #default="{ row }">
          <el-input v-if="row.action !== 'navigate'" v-model="row.target" size="small"
            placeholder="元素定位，如 #btn / .title（可从元素管理复制）" />
          <span v-else class="hint">—</span>
        </template>
      </el-table-column>
      <el-table-column label="值 / SQL" min-width="240">
        <template #default="{ row }">
          <el-input v-if="row.action !== 'assert_db'" v-model="row.value" size="small"
            :placeholder="valuePlaceholder(row.action)" />
          <el-input v-else v-model="row.value" type="textarea" :rows="3" size="small"
            placeholder="SQL，如 SELECT count(*) FROM test_case" />
        </template>
      </el-table-column>
      <el-table-column label="期望值" width="160">
        <template #default="{ row }">
          <el-input v-if="row.action === 'assert_db' || row.action === 'assert_text'"
            v-model="row.expected" size="small" placeholder="期望文本" />
          <span v-else class="hint">—</span>
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

    <div style="margin-top: 10px; display: flex; gap: 8px">
      <el-button size="small" @click="addRow">+ 添加步骤</el-button>
      <el-button size="small" type="primary" :disabled="!rows.length" @click="$emit('save', serialize())">
        保存脚本
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  initialSteps: { type: Array, default: () => [] },  // 从 script.step_mapping 还原
})
const emit = defineEmits(['save'])

// 与后端 step_codegen.SUPPORTED_ACTIONS 对齐
const ACTIONS = [
  { value: 'navigate', label: '打开页面' },
  { value: 'click', label: '点击' },
  { value: 'input', label: '输入' },
  { value: 'select', label: '下拉选择' },
  { value: 'wait', label: '等待(秒)' },
  { value: 'assert_text', label: '断言文本' },
  { value: 'assert_visible', label: '断言可见' },
  { value: 'assert_db', label: '数据库断言' },
]

const rows = ref([])

// 还原：initialSteps 兼容 {seq,action,target,value,element_name,expected} 行式结构
watch(() => props.initialSteps, (v) => {
  rows.value = (v || []).map((s, i) => ({
    seq: s.seq || i + 1,
    action: s.action || 'click',
    target: s.target || '',
    value: s.value || '',
    element_name: s.element_name || '',
    expected: s.expected || '',
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
.hint { color: var(--mt-text-tertiary, #999); }
</style>
