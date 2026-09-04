<template>
  <div class="capture-workbench">
    <!-- 工作台头部 -->
    <div class="wb-header">
      <div class="wb-title">
        <span>会话式抓取工作台</span>
        <el-tag v-if="state" type="info" size="small" effect="plain">
          {{ state.included_count }}/{{ state.total_elements }} 已勾选
        </el-tag>
        <el-tag v-if="batchCount > 0" type="success" size="small" effect="plain">
          {{ batchCount }} 批次
        </el-tag>
      </div>
      <div class="wb-actions">
        <el-button size="small" @click="toggleAll(false)" :disabled="!state || state.total_elements === 0">
          全不选
        </el-button>
        <el-button size="small" @click="toggleAll(true)" :disabled="!state || state.total_elements === 0">
          全选
        </el-button>
        <el-button size="small" type="danger" plain @click="discard" :disabled="!sessionId">
          丢弃会话
        </el-button>
      </div>
    </div>

    <!-- 空态 -->
    <el-empty v-if="!state || state.total_elements === 0" description="会话为空，先抓取一个页面" :image-size="60" />

    <template v-else>
      <!-- 批次列表（可折叠，可整批删除） -->
      <el-collapse v-model="expandedBatches" class="batch-collapse">
        <el-collapse-item
          v-for="(batch, idx) in visibleBatches"
          :key="idx"
          :name="String(idx)"
        >
          <template #title>
            <div class="batch-title">
              <el-tag size="small" effect="plain">批次 {{ idx + 1 }}</el-tag>
              <span class="batch-url">{{ batch.url }}</span>
              <span class="batch-count">{{ batch.temp_ids.length }} 元素</span>
              <el-button
                size="small" type="danger" text
                @click.stop="removeBatch(idx)"
              >删除批次</el-button>
            </div>
          </template>

          <!-- 批次截图 -->
          <div v-if="batch.screenshot_url" class="batch-shot">
            <img :src="screenshotProxy(batch.screenshot_url)" class="batch-shot-img" />
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- 元素列表 -->
      <div class="wb-elements">
        <div
          v-for="el in state.elements"
          :key="el.temp_id"
          class="wb-element"
          :class="{ excluded: !el.included }"
        >
          <el-checkbox
            :model-value="el.included"
            @change="(v) => toggleElement(el.temp_id, v)"
          >
            <el-tag :type="typeColor(el.element_type)" size="small">{{ el.element_type }}</el-tag>
            <span class="wb-el-text">{{ el.element_text || el.temp_id }}</span>
            <el-tag size="small" type="info" effect="plain">
              批次 {{ (el.batch_idx ?? 0) + 1 }}
            </el-tag>
          </el-checkbox>
          <el-button size="small" type="danger" text @click="removeElement(el.temp_id)">删除</el-button>
        </div>
      </div>
    </template>

    <!-- 入库 -->
    <div class="wb-import" v-if="state && state.included_count > 0">
      <el-select v-model="pageMode" style="width: 120px">
        <el-option label="新建页面" value="new" />
        <el-option label="已有页面" value="existing" />
      </el-select>
      <template v-if="pageMode === 'new'">
        <el-input v-model="pageName" placeholder="页面名称（留空自动取 URL）" style="width: 220px" />
        <el-input v-model="pageUrl" placeholder="页面 URL（留空自动取批次）" style="width: 260px" />
      </template>
      <el-select v-else v-model="pageId" placeholder="选择已有页面" style="width: 260px">
        <el-option v-for="p in pages" :key="p.id" :label="p.page_name" :value="p.id" />
      </el-select>
      <el-button type="primary" :loading="importing" @click="importSelected">
        入库 {{ state.included_count }} 个元素
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elementAPI } from '@/api/element'

const props = defineProps({
  sessionId: { type: String, default: '' },
  projects: { type: Array, default: () => [] }
})
const emit = defineEmits(['imported', 'discarded'])

const state = ref(null)
const expandedBatches = ref([])
const pageMode = ref('new')
const pageName = ref('')
const pageUrl = ref('')
const pageId = ref('')
const pages = ref([])
const importing = ref(false)

const batchCount = computed(() => state.value?.batches?.length || 0)
const visibleBatches = computed(() =>
  (state.value?.batches || []).map((b, idx) => ({ ...b, _idx: idx })).filter((b) => !b.removed)
)

const screenshotProxy = (raw) => {
  const m = String(raw).match(/\/moontest\/(.+)$/)
  return m ? `/api/v1/elements/screenshot?key=${encodeURIComponent(m[1])}` : raw
}

const typeColor = (type) => {
  const map = { button: 'primary', input: 'success', link: 'warning', select: 'info', textarea: 'info' }
  return map[type] || 'default'
}

const refresh = async () => {
  if (!props.sessionId) return
  try {
    state.value = await elementAPI.getCaptureState(props.sessionId)
    expandedBatches.value = visibleBatches.value.map((b) => String(b._idx))
  } catch (err) {
    // 404 = 会话过期
    state.value = null
  }
}

const loadPages = async () => {
  const projectId = state.value?.project_id
  if (!projectId) return
  try {
    pages.value = await elementAPI.listPages(projectId)
  } catch {
    pages.value = []
  }
}

const toggleElement = async (tempId, included) => {
  try {
    await elementAPI.setCaptureElementIncluded(props.sessionId, tempId, included)
    const el = state.value.elements.find((e) => e.temp_id === tempId)
    if (el) el.included = included
    state.value.included_count += included ? 1 : -1
  } catch (err) {
    ElMessage.error('操作失败（会话可能已过期）')
    refresh()
  }
}

const toggleAll = async (included) => {
  try {
    await elementAPI.setCaptureAllIncluded(props.sessionId, included)
    state.value.elements.forEach((e) => (e.included = included))
    state.value.included_count = included ? state.value.total_elements : 0
  } catch (err) {
    ElMessage.error('操作失败')
  }
}

const removeElement = async (tempId) => {
  try {
    await elementAPI.deleteCaptureElement(props.sessionId, tempId)
    await refresh()
  } catch (err) {
    ElMessage.error('删除失败')
  }
}

const removeBatch = async (batchIdx) => {
  try {
    await ElMessageBox.confirm('删除该批次及其全部元素？', '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await elementAPI.deleteCaptureBatch(props.sessionId, batchIdx)
    await refresh()
  } catch (err) {
    ElMessage.error('删除批次失败')
  }
}

const discard = async () => {
  try {
    await ElMessageBox.confirm('丢弃整个会话？所有未入库元素将丢失。', '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await elementAPI.discardCaptureSession(props.sessionId)
  } catch { /* 已过期也视为成功 */ }
  state.value = null
  ElMessage.success('会话已丢弃')
  emit('discarded')
}

const importSelected = async () => {
  const data = {
    session_id: props.sessionId,
    page_name: pageName.value || undefined,
    page_url: pageUrl.value || undefined,
    page_id: pageMode.value === 'existing' ? pageId.value : undefined
  }
  if (pageMode.value === 'existing' && !data.page_id) {
    ElMessage.warning('请选择已有页面')
    return
  }
  importing.value = true
  try {
    const result = await elementAPI.importFromCaptureSession(data)
    ElMessage.success(`成功入库 ${result.imported_count} 个元素到「${result.page_name}」`)
    state.value = null
    emit('imported', result)
  } catch (err) {
    ElMessage.error('入库失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    importing.value = false
  }
}

defineExpose({ refresh, loadPages, state })
</script>

<style scoped>
.wb-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.wb-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.wb-actions {
  display: flex;
  gap: 8px;
}
.batch-collapse {
  margin-bottom: 12px;
}
.batch-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.batch-url {
  flex: 1;
  font-size: 13px;
  color: var(--mt-text-secondary, #606266);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.batch-count {
  font-size: 12px;
  color: var(--mt-text-secondary, #909399);
}
.batch-shot {
  max-height: 260px;
  overflow: hidden;
  border-radius: 4px;
}
.batch-shot-img {
  width: 100%;
  object-fit: cover;
  object-position: top;
}
.wb-elements {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
  padding: 6px;
}
.wb-element {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  border-radius: 4px;
}
.wb-element:hover {
  background: var(--el-fill-color-light, #f5f7fa);
}
.wb-element.excluded .wb-el-text {
  text-decoration: line-through;
  color: var(--mt-text-secondary, #c0c4cc);
}
.wb-el-text {
  margin: 0 8px;
  font-size: 13px;
}
.wb-import {
  display: flex;
  gap: 10px;
  margin-top: 14px;
  align-items: center;
}
</style>
