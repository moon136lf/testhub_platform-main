<template>
  <div class="ai-settings page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>AI 设置</h2>
        <div class="page-subtitle">配置 AI 供应商的 API Key 与接入参数，修改后即时生效</div>
      </div>
    </div>

    <el-card shadow="never">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:16px">
        provider 的 API Key / URL 存数据库，修改后即时生效（无需重启）。联调时在此填入真实 key。
      </el-alert>

      <el-table :data="providerRows" border>
        <el-table-column prop="provider" label="Provider" width="120" />
        <el-table-column label="API Key">
          <template #default="{ row }">
            <el-input v-model="row.apiKey" :type="row.showKey ? 'text' : 'password'" size="small">
              <template #append>
                <el-button @click="row.showKey = !row.showKey">{{ row.showKey ? '隐藏' : '显示' }}</el-button>
              </template>
            </el-input>
          </template>
        </el-table-column>
        <el-table-column label="API URL" width="320">
          <template #default="{ row }">
            <el-input v-model="row.apiUrl" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button type="primary" link @click="save(row)">保存</el-button>
            <el-button type="primary" link :loading="row.testing" @click="testConn(row)">测试连接</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider />
      <el-form label-width="140px">
        <el-form-item label="默认 Provider">
          <el-select v-model="defaultProvider" style="width: 240px">
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button type="primary" style="margin-left: 12px" @click="saveDefault">保存</el-button>
        </el-form-item>
        <el-form-item label="Fallback 链">
          <el-select v-model="fallbackProviders" multiple style="width: 400px">
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button type="primary" style="margin-left: 12px" @click="saveFallback">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'

// provider 名与后端 ai_gateway 注册名严格一致（glm-2.5 注册名，底层模型 glm-5.2）；
// 之前这里写死 'glm-4' 是改名前遗留，导致设置页存的 key 后端不读、fallback 链指向不存在的 provider
const providers = ['glm-2.5', 'qwen', 'deepseek', 'claude', 'moonshot']
const providerRows = ref(providers.map(p => ({ provider: p, apiKey: '', apiUrl: '', showKey: false, testing: false })))
const defaultProvider = ref('glm-2.5')
const fallbackProviders = ref(['glm-2.5', 'qwen', 'deepseek'])

const loadSettings = async () => {
  try {
    const res = await systemAPI.listSettings('ai')
    const rows = res.data || []
    for (const row of rows) {
      if (row.key.endsWith('.api_key')) {
        const p = row.key.split('.')[0]
        const target = providerRows.value.find(r => r.provider === p)
        if (target && row.value && row.value !== '***') target.apiKey = row.value
      } else if (row.key.endsWith('.api_url')) {
        const p = row.key.split('.')[0]
        const target = providerRows.value.find(r => r.provider === p)
        if (target && row.value) target.apiUrl = row.value
      } else if (row.key === 'ai.default_provider' && row.value) {
        defaultProvider.value = row.value
      } else if (row.key === 'ai.fallback_providers' && row.value) {
        try { fallbackProviders.value = JSON.parse(row.value) } catch {}
      }
    }
  } catch (e) { ElMessage.error('加载配置失败') }
}

const save = async (row) => {
  try {
    await systemAPI.updateSetting(`${row.provider}.api_key`, 'ai', {
      value: row.apiKey, value_type: 'string', is_secret: true
    })
    if (row.apiUrl) {
      await systemAPI.updateSetting(`${row.provider}.api_url`, 'ai', {
        value: row.apiUrl, value_type: 'string', is_secret: false
      })
    }
    ElMessage.success(`${row.provider} 已保存`)
  } catch (e) { ElMessage.error('保存失败') }
}

const testConn = async (row) => {
  row.testing = true
  try {
    const res = await systemAPI.testConnection(row.provider)
    const d = res.data || res
    if (d.success) ElMessage.success(`${row.provider} 连接正常`)
    else ElMessage.error(`${row.provider} 连接失败: ${d.message}`)
  } catch (e) { ElMessage.error('测试失败') }
  finally { row.testing = false }
}

const saveDefault = async () => {
  try {
    await systemAPI.updateSetting('ai.default_provider', 'ai', {
      value: defaultProvider.value, value_type: 'string', is_secret: false
    })
    ElMessage.success('默认 provider 已保存')
  } catch (e) { ElMessage.error('保存失败') }
}

const saveFallback = async () => {
  try {
    await systemAPI.updateSetting('ai.fallback_providers', 'ai', {
      value: JSON.stringify(fallbackProviders.value), value_type: 'json', is_secret: false
    })
    ElMessage.success('Fallback 链已保存')
  } catch (e) { ElMessage.error('保存失败') }
}

onMounted(loadSettings)
</script>

<style scoped>
.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}
</style>
