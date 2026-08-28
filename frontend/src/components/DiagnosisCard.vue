<template>
  <div class="diagnosis-card">
    <el-descriptions :column="1" border size="small">
      <el-descriptions-item label="模式">
        <el-tag :type="card.mode === 'multimodal' ? 'warning' : 'info'" size="small">
          {{ card.mode === 'multimodal' ? 'AI 多模态' : '规则归因' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="根因">{{ card.diagnosis || card.reason || '—' }}</el-descriptions-item>
      <el-descriptions-item v-if="card.suggestion" label="建议">{{ card.suggestion }}</el-descriptions-item>
      <el-descriptions-item v-if="card.new_locator" label="新定位器">
        <code class="locator">{{ card.new_locator }}</code>
      </el-descriptions-item>
      <el-descriptions-item v-if="card.confidence != null" label="置信度">
        <el-progress :percentage="Math.round(card.confidence * 100)" :stroke-width="14" style="width: 200px" />
      </el-descriptions-item>
    </el-descriptions>
    <div style="margin-top: 12px; text-align: right">
      <slot name="actions" />
      <el-button type="primary" :disabled="!card.new_locator" :loading="applying" @click="$emit('apply', card)">
        应用修复
      </el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  card: { type: Object, required: true },
  applying: { type: Boolean, default: false },
})
defineEmits(['apply'])
</script>

<style scoped>
.locator { background: #f5f7fa; padding: 2px 8px; border-radius: 4px; font-family: monospace; }
</style>
