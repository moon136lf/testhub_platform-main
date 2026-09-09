/**
 * ECharts 全站统一主题常量
 * 分类色序固定不循环；文字用文本色不用系列色（dataviz 规范）
 */
export const CHART_COLORS = [
  '#6366F1', // 靛蓝紫（主）
  '#0EA5E9', // 天蓝
  '#10B981', // 翠绿
  '#F59E0B', // 琥珀
  '#EF4444', // 红
  '#8B5CF6', // 紫
  '#14B8A6', // 青绿
]

export const CHART_TEXT = '#64748B'   // 轴标签/图例文字
export const CHART_LINE = '#E2E8F0'   // 分割线

/** 通用 tooltip 样式 */
export const TOOLTIP_STYLE = {
  backgroundColor: '#FFFFFF',
  borderColor: '#E2E8F0',
  borderRadius: 8,
  textStyle: { color: '#0F172A', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 12px rgba(15,23,42,.10);',
}

/** 通用 axis 样式 */
export const AXIS_STYLE = {
  axisLine: { lineStyle: { color: '#E2E8F0' } },
  axisLabel: { color: CHART_TEXT, fontSize: 12 },
  splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } },
}

/** 环形饼图基础 option 片段（中心可放总数） */
export function donutPiece(name, data, centerText = '') {
  return {
    name,
    type: 'pie',
    radius: ['45%', '70%'],
    center: ['50%', '50%'],
    itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
    label: { color: CHART_TEXT, fontSize: 12 },
    data,
    ...(centerText
      ? {
          title: {
            text: centerText,
            subtext: '总数',
            left: 'center',
            top: '42%',
            textStyle: { fontSize: 22, fontWeight: 700, color: '#0F172A' },
            subtextStyle: { fontSize: 12, color: CHART_TEXT },
          },
        }
      : {}),
  }
}

/** 平滑折线 + 面积渐变 片段（opts 可传 yAxisIndex 等额外 series 属性） */
export function smoothArea(name, data, color = CHART_COLORS[0], opts = {}) {
  return {
    name,
    type: 'line',
    smooth: true,
    lineStyle: { width: 2, color },
    itemStyle: { color },
    areaStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: color + '33' }, // 20% opacity
          { offset: 1, color: color + '00' },
        ],
      },
    },
    data,
    ...opts,
  }
}
