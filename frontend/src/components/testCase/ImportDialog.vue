<template>
  <!-- 智能导入弹框：模板说明 + 下载模板 + 文件选择 + AI优化 + 预览确认 -->
  <div>
    <el-dialog v-model="visible" title="导入用例" width="680px" @close="resetDialog">
      <!-- 格式说明 -->
      <el-alert type="info" :closable="false" style="margin-bottom: 14px">
        <template #title>
          支持两种格式（自动识别）：
        </template>
        <div style="font-size:12px;line-height:1.9">
          <div>① <b>平台模板</b>（9 列）：用例名 / 优先级(P0-P3) / 类型 / 步骤 / 动作 / 目标 / 数据 / 预期(步) / 预期结果。同一条用例的多个步骤写在多行，用例名只在首行填。</div>
          <div>② <b>自由文本表</b>：含「标题」和「操作步骤」列即可（如 用例编号/模块/标题/操作步骤/预期结果/优先级）。步骤段落按 <code>1. 2. 3.</code> 拆分，<code>断言：xxx</code> 作为该步骤预期；缺失的预期标记为 <span class="pending-mark">待补</span>，导入后可手动补充。</div>
        </div>
      </el-alert>

      <el-form label-width="90px">
        <el-form-item label="项目">
          <el-select v-model="projectId" placeholder="选择项目" style="width: 100%" filterable>
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例文件">
          <input type="file" accept=".xlsx,.csv,.md" @change="onFileChange"
                 style="font-size:13px" />
          <div v-if="file" class="file-info">已选择：{{ file.name }}（{{ (file.size / 1024).toFixed(1) }} KB）</div>
        </el-form-item>
        <el-form-item label="AI优化">
          <el-checkbox v-model="aiOptimize">AI 标准化步骤（每条用例经大模型重写为标准四元组，消耗 Token）</el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="downloadTemplate">下载模板</el-button>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="parsing" :disabled="!file || !projectId" @click="doPreview">
          解析预览
        </el-button>
      </template>
    </el-dialog>

    <!-- 预览确认弹框 -->
    <el-dialog v-model="previewVisible" title="导入预览（确认后入库）" width="85%" top="4vh">
      <el-alert v-if="warnings.length" type="warning" :closable="false" style="margin-bottom: 10px">
        <div v-for="(w, i) in warnings" :key="i">{{ w }}</div>
      </el-alert>
      <div class="preview-toolbar">
        <span>共 {{ cases.length }} 条用例 · 格式：{{ formatLabel }}</span>
        <el-checkbox v-model="aiOptimize">AI 标准化步骤（入库时执行）</el-checkbox>
      </div>
      <el-table :data="cases" border size="small" max-height="55vh" row-key="__idx">
        <el-table-column type="expand">
          <template #default="{ row }">
            <el-table :data="row.steps" size="small" border style="margin: 8px 16px">
              <el-table-column prop="step" label="#" width="50" />
              <el-table-column prop="action" label="动作" min-width="200" show-overflow-tooltip />
              <el-table-column prop="target" label="目标" width="160" show-overflow-tooltip />
              <el-table-column prop="data" label="数据" width="140" show-overflow-tooltip />
              <el-table-column label="预期(步)" width="220">
                <template #default="{ row: s }">
                  <el-input v-model="s.expected" size="small" :class="{ 'pending-input': s.expected === '待补' }" />
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-table-column>
        <el-table-column label="用例名" min-width="220">
          <template #default="{ row }">
            <el-input v-model="row.name" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="100">
          <template #default="{ row }">
            <el-select v-model="row.priority" size="small">
              <el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="预期结果" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.expected_result" size="small" :class="{ 'pending-input': row.expected_result === '待补' }" />
          </template>
        </el-table-column>
        <el-table-column label="步骤数" width="70">
          <template #default="{ row }">{{ row.steps.length }}</template>
        </el-table-column>
        <el-table-column label="操作" width="60">
          <template #default="{ $index }">
            <el-button type="danger" link size="small" @click="cases.splice($index, 1)">删</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="previewVisible = false">上一步</el-button>
        <el-button type="primary" :loading="importing" @click="doConfirm">
          确认导入（{{ cases.length }} 条）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { testCaseAPI } from '@/api/testCase.js'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  defaultProjectId: { type: String, default: '' },
})
const emit = defineEmits(['imported'])

const visible = ref(false)
const previewVisible = ref(false)
const file = ref(null)
const aiOptimize = ref(false)
const parsing = ref(false)
const importing = ref(false)
const projectId = ref(props.defaultProjectId || '')
const cases = ref([])
const warnings = ref([])
const importFormat = ref('xlsx')

watch(() => props.defaultProjectId, (v) => { if (v && !projectId.value) projectId.value = v })

const formatLabel = computed(() => (importFormat.value === 'freetext' ? '自由文本表（自动转换）' : '平台模板'))

const open = () => {
  visible.value = true
}
defineExpose({ open })

const resetDialog = () => {
  // 只重置文件选择；cases 保留——关导入弹框会触发 close，此时预览数据正在用
  file.value = null
  warnings.value = []
}

const onFileChange = (e) => {
  file.value = e.target.files[0] || null
}

const downloadTemplate = async () => {
  try {
    const resp = await testCaseAPI.importTemplate()
    const blob = new Blob([resp.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'case_import_template.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error('下载模板失败: ' + (error.message || error))
  }
}

const doPreview = async () => {
  parsing.value = true
  try {
    const ext = (file.value.name.split('.').pop() || 'xlsx').toLowerCase()
    const res = await testCaseAPI.importPreview(file.value, ext)
    // importPreview 返回 {code, data:{format, cases, warnings}}（axios 已剥一层 data）
    const data = res?.data?.cases ? res.data : (res || {})
    // 行 key 供 el-table row-key 使用
    cases.value = (data.cases || []).map((c, i) => ({ ...c, __idx: i }))
    warnings.value = data.warnings || []
    importFormat.value = data.format || 'template'
    if (!cases.value.length) {
      ElMessage.warning('未解析到用例数据')
      return
    }
    visible.value = false
    previewVisible.value = true
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error('解析失败: ' + (typeof detail === 'string' ? detail : (error.message || error)))
  } finally {
    parsing.value = false
  }
}

const doConfirm = async () => {
  if (!cases.value.length) return
  importing.value = true
  try {
    const payload = cases.value.map(({ __idx, ...c }) => c)
    const res = await testCaseAPI.importConfirm(projectId.value, payload, aiOptimize.value)
    const data = res?.data?.imported != null ? res.data : (res || {})
    previewVisible.value = false
    visible.value = false
    if (data.failed > 0 && Array.isArray(data.errors) && data.errors.length) {
      const lines = data.errors.map(err => `「${err.name}」：${err.reason}`)
      ElMessageBox.alert(
        `<div style="max-height:300px;overflow:auto;font-size:13px;line-height:1.8">${lines.map(l => `<div>${l}</div>`).join('')}</div>`,
        `导入完成：成功 ${data.imported} 条，失败 ${data.failed} 条${data.ai_ok_count ? `，AI优化 ${data.ai_ok_count} 条` : ''}`,
        { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' }
      ).catch(() => {})
    } else {
      ElMessage.success(`导入成功 ${data.imported} 条${data.ai_ok_count ? `，AI优化 ${data.ai_ok_count} 条` : ''}`)
    }
    emit('imported')
  } catch (error) {
    ElMessage.error('导入失败: ' + (error.message || error))
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.file-info {
  font-size: 12px;
  color: var(--mt-text-secondary, #909399);
  margin-top: 4px;
}
.preview-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--mt-text-secondary, #909399);
}
:deep(.pending-input .el-input__inner) {
  color: #E6A23C;
  font-weight: 600;
}
.pending-mark {
  color: #E6A23C;
  font-weight: 600;
}
</style>
