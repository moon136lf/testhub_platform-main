<template>
  <div class="runtime-config">
    <el-card>
      <template #header><span>运行配置</span></template>
      <el-form :model="form" label-width="200px" v-loading="loading">
        <el-card shadow="never" style="margin-bottom:16px">
          <template #header><span>自愈引擎</span></template>
          <el-form-item label="自愈策略">
            <el-select v-model="form.heal_strategy" style="width: 280px">
              <el-option label="SMART（默认，CI）" value="SMART" />
              <el-option label="HEURISTIC_ONLY（仅启发式）" value="HEURISTIC_ONLY" />
              <el-option label="DOM_ONLY（DOM模糊）" value="DOM_ONLY" />
              <el-option label="VISUAL_ONLY（视觉模型）" value="VISUAL_ONLY" />
              <el-option label="FULL（全链含视觉）" value="FULL" />
              <el-option label="PARALLEL（并行）" value="PARALLEL" />
            </el-select>
          </el-form-item>
          <el-form-item label="置信度阈值">
            <el-input-number v-model="form.heal_confidence_threshold" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="缓存TTL-成功(天)">
            <el-input-number v-model="form.heal_cache_ttl_success" :min="1" :max="90" />
          </el-form-item>
          <el-form-item label="缓存TTL-失败(小时)">
            <el-input-number v-model="form.heal_cache_ttl_fail" :min="1" :max="72" />
          </el-form-item>
        </el-card>

        <el-card shadow="never" style="margin-bottom:16px">
          <template #header><span>执行</span></template>
          <el-form-item label="执行超时(秒)">
            <el-input-number v-model="form.execution_timeout" :min="10" :max="3600" />
          </el-form-item>
          <el-form-item label="最大重试次数">
            <el-input-number v-model="form.max_retry_count" :min="0" :max="10" />
          </el-form-item>
          <el-form-item label="SSE 超时(秒)">
            <el-input-number v-model="form.sse_timeout" :min="60" :max="7200" />
          </el-form-item>
        </el-card>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveAll">保存全部</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemAPI } from '@/api/system.js'

const loading = ref(false)
const saving = ref(false)
const form = ref({
  heal_strategy: 'SMART', heal_confidence_threshold: 3,
  heal_cache_ttl_success: 30, heal_cache_ttl_fail: 1,
  execution_timeout: 600, max_retry_count: 3, sse_timeout: 1800
})

const FIELD_MAP = {
  heal_strategy: { key: 'heal.strategy', type: 'string' },
  heal_confidence_threshold: { key: 'heal.confidence_threshold', type: 'int' },
  heal_cache_ttl_success: { key: 'heal.cache_ttl_success', type: 'int' },
  heal_cache_ttl_fail: { key: 'heal.cache_ttl_fail', type: 'int' },
  execution_timeout: { key: 'execution.timeout', type: 'int' },
  max_retry_count: { key: 'execution.max_retry', type: 'int' },
  sse_timeout: { key: 'sse.timeout', type: 'int' }
}

const load = async () => {
  loading.value = true
  try {
    const res = await systemAPI.getRuntimeConfig()
    const d = res.data || res
    Object.assign(form.value, d)
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const saveAll = async () => {
  saving.value = true
  try {
    for (const [field, meta] of Object.entries(FIELD_MAP)) {
      await systemAPI.updateSetting(meta.key, 'runtime', {
        value: String(form.value[field]), value_type: meta.type, is_secret: false
      })
    }
    ElMessage.success('运行配置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

onMounted(load)
</script>

<style scoped>
.runtime-config { padding: 20px; }
</style>
