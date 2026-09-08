<template>
  <div class="highlight-wrapper" ref="wrapper">
    <img v-if="screenshotUrl" :src="screenshotUrl" @load="onImgLoad" class="highlight-img" />
    <div v-else class="no-screenshot">暂无截图</div>
    <div
      v-for="el in elements"
      :key="el.temp_id"
      class="hotspot"
      :class="{
        selected: selectedIds.includes(el.temp_id),
        flashing: hoverId === el.temp_id
      }"
      :style="hotspotStyle(el)"
      @click="$emit('pick', el.temp_id)"
      @mouseenter="$emit('card-hover', el.temp_id)"
      @mouseleave="$emit('card-hover', null)"
    >
      <span class="hotspot-label">{{ el.element_text || el.temp_id }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  screenshotUrl: { type: String, default: '' },
  elements: { type: Array, default: () => [] },
  selectedIds: { type: Array, default: () => [] },
  hoverId: { type: String, default: '' }
})

defineEmits(['pick', 'card-hover'])

const wrapper = ref(null)
const scale = ref(1)

// 截图为 full_page（顶部对齐），元素坐标为视口坐标，仅按显示宽/原始宽缩放
const onImgLoad = (event) => {
  const img = event.target
  const naturalWidth = img.naturalWidth
  if (naturalWidth > 0) {
    scale.value = img.clientWidth / naturalWidth
  } else if (wrapper.value) {
    scale.value = 1
  }
}

const hotspotStyle = (el) => {
  if (!el || el.position_x == null || el.position_y == null) return { display: 'none' }
  const s = scale.value
  return {
    left: `${el.position_x * s}px`,
    top: `${el.position_y * s}px`,
    width: `${(el.width || 0) * s}px`,
    height: `${(el.height || 0) * s}px`
  }
}
</script>

<style scoped>
.highlight-wrapper {
  position: relative;
  width: 100%;
}

.highlight-img {
  display: block;
  width: 100%;
  border-radius: 4px;
}

.no-screenshot {
  color: #909399;
  font-size: 14px;
  text-align: center;
  padding: 180px 0;
}

.hotspot {
  position: absolute;
  border: 2px solid #f56c6c;
  background: transparent;
  cursor: pointer;
  pointer-events: auto;
}

.hotspot:hover {
  border-width: 3px;
}

.hotspot.selected {
  border-color: #67c23a;
  background: rgba(103, 194, 26, 0.12);
}

.hotspot.flashing {
  animation: flash 0.6s ease 2;
}

@keyframes flash {
  50% {
    border-color: #e6a23c;
    background: rgba(230, 162, 60, 0.45);
  }
}

.hotspot-label {
  position: absolute;
  top: -18px;
  left: 0;
  font-size: 10px;
  line-height: 16px;
  white-space: nowrap;
  color: #f56c6c;
  background: rgba(255, 255, 255, 0.85);
  padding: 0 4px;
  border-radius: 2px;
  pointer-events: none;
}

.hotspot.selected .hotspot-label {
  color: #67c23a;
}
</style>
