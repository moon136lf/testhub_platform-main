<template>
  <div class="script-convert">
    <el-card>
      <h2>用例转自动化脚本</h2>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="form.projectId" placeholder="选择项目" style="width: 200px" @change="loadCases">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例">
          <el-select v-model="form.caseIds" multiple filterable placeholder="多选用例" style="width: 360px">
            <el-option v-for="c in finalizedCases" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="AI优化">
          <el-switch v-model="form.aiOptimize" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="converting" @click="handleConvert">批量转脚本</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="margin-top: 16px">
      <h3>转换过程文字直播</h3>
      <div class="log-box">
        <div v-for="(msg, i) in logs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-card>

    <el-card style="margin-top: 16px">
      <h3>脚本列表</h3>
      <el-table :data="scripts" border>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="locator_source" label="定位来源" width="140" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="viewScript(row)">查看</el-button>
            <el-button size="small" type="success" :disabled="row.status==='confirmed'"
                       @click="confirmScript(row)">确认入库</el-button>
            <el-button size="small" @click="openDiagnose(row)">调试修复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="diagVisible" title="调试修复" width="700px">
      <el-form label-width="100px">
        <el-form-item label="错误类型">
          <el-select v-model="diagForm.error_type" style="width: 200px">
            <el-option label="定位失败" value="locate_failed" />
            <el-option label="超时" value="timeout" />
            <el-option label="断言失败" value="assertion_failed" />
            <el-option label="脚本错误" value="script_error" />
          </el-select>
        </el-form-item>
        <el-form-item label="错误信息">
          <el-input v-model="diagForm.error_msg" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="脚本片段">
          <el-input v-model="diagForm.script_fragment" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="失败步骤">
          <el-input-number v-model="diagForm.failed_step" :min="1" />
        </el-form-item>
        <el-form-item label="截图URL">
          <el-input v-model="diagForm.screenshot_url" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div v-if="diagCard" class="diag-card">
        <p>归因: <strong>{{ diagCard.category }}</strong> | 可改: {{ diagCard.can_fix }}</p>
        <p>理由: {{ diagCard.reason }}</p>
        <p v-if="diagCard.suggestion">建议: {{ diagCard.suggestion }}</p>
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="primary" @click="runDiagnose">诊断</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scriptAPI } from '@/api/script'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'

const projects = ref([])
const finalizedCases = ref([])
const scripts = ref([])
const logs = ref([])
const converting = ref(false)
const form = reactive({ projectId: '', caseIds: [], aiOptimize: false })

const diagVisible = ref(false)
const diagForm = reactive({ error_type: 'locate_failed', error_msg: '', script_fragment: '', failed_step: 1, screenshot_url: '' })
const diagCard = ref(null)
let currentScriptId = null

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.items || presp.data || presp || []
})

const loadCases = async () => {
  if (!form.projectId) return
  const resp = await testCaseAPI.list({ project_id: form.projectId, is_finalized: true })
  finalizedCases.value = resp.items || resp.data?.items || resp || []
}
const handleConvert = async () => {
  if (!form.projectId || !form.caseIds.length) {
    ElMessage.warning('请选择项目和用例'); return
  }
  converting.value = true; logs.value = []
  try {
    const resp = await scriptAPI.convert(form.projectId, form.caseIds, form.aiOptimize)
    const es = scriptAPI.subscribe(resp.data.session_id, (msg) => {
      logs.value.push(msg)
      if (msg.progress >= 1.0) {
        es.close(); loadScripts(); converting.value = false
      }
    })
  } catch (e) { ElMessage.error('转换失败'); converting.value = false }
}
const loadScripts = async () => {
  const resp = await scriptAPI.list({ project_id: form.projectId })
  scripts.value = resp.data || []
}
const viewScript = (row) => { window.open(`/api/v1/scripts/${row.id}`, '_blank') }
const confirmScript = async (row) => {
  await scriptAPI.confirm(row.id)
  ElMessage.success('已确认入库'); loadScripts()
}
const openDiagnose = (row) => {
  currentScriptId = row.id
  diagCard.value = null
  diagVisible.value = true
}
const runDiagnose = async () => {
  const resp = await scriptAPI.diagnose(currentScriptId, { ...diagForm })
  diagCard.value = resp.data.diagnosis_card
  ElMessage.success('诊断完成')
}
</script>

<style scoped>
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.diag-card { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
</style>
