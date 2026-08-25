<template>
  <el-alert
    v-if="visible"
    title="Token 预警"
    :description="`当前项目 Token 剩余不足 ${threshold}%，请及时补充配额。`"
    type="error"
    :closable="false"
    show-icon
    style="border-radius: 0"
  />
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { systemAPI } from '@/api/system.js'
import { projectAPI } from '@/api/project.js'

const visible = ref(false)
const threshold = ref(10)
let timer = null
let currentProjectId = null

const checkStatus = async () => {
  if (document.hidden) return
  if (!currentProjectId) {
    try {
      const res = await projectAPI.list()
      const projects = res.items || res || []
      if (!projects.length) return
      currentProjectId = projects[0].id
    } catch { return }
  }
  try {
    const res = await systemAPI.tokenStatus(currentProjectId)
    const s = res.data || res
    threshold.value = s.warning_threshold
    if (s.is_warning) {
      visible.value = true
      const key = `token_warned_${currentProjectId}`
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1')
        ElMessageBox.alert(
          `Token 剩余不足 ${s.warning_threshold}%（剩余 ${s.remaining}），请及时处理。`,
          'Token 预警', { type: 'warning' }
        )
      }
    } else {
      visible.value = false
    }
  } catch { /* silent */ }
}

onMounted(() => {
  checkStatus()
  timer = setInterval(checkStatus, 5 * 60 * 1000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
