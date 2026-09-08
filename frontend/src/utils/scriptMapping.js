// pipeline step_mapping → StepEditor 行式结构 的公共映射（ScriptConvert / AutoUITest 共用）

const ACTION_MAP = {
  navigate: 'navigate', click: 'click', fill: 'input', select: 'select',
  check: 'click', create: 'input', edit: 'input', delete: 'click', workflow_action: 'click',
}

const extractLocator = (impl) => {
  if (!impl) return ''
  const m = String(impl).match(/"([^"]+)"/)   // get_by_xxx("val", ...) / locator("#btn") → 取引号内
  if (m) return m[1]
  return String(impl).replace(/^page\./, '').replace(/\)$/, '')  // 裸 css（page.#btn 罕见）兜底
}

export const fromPipelineMapping = (m) => {
  const action = ACTION_MAP[m.action]
  if (!action) {
    console.warn('[StepEditor] 无法映射的 pipeline action，降级为 wait 1s:', m.action, m)
    return [{ seq: m.step || 0, action: 'wait', target: '', value: '1', element_name: '', expected: '' }]
  }
  const rows = [{
    seq: m.step || 0,
    action,
    target: action === 'navigate' ? '' : (extractLocator(m.impl) || m.element_name || ''),
    value: m.value || '',
    element_name: m.element_name || '',
    expected: '',
  }]
  // 断言单独成行：assertion.expected 非空追加一行 assert_text
  const expected = (m.assertion && m.assertion.expected) || ''
  if (expected) {
    rows.push({
      seq: m.step || 0, action: 'assert_text',
      target: m.assertion.target ? extractLocator(m.assertion.target) : (rows[0].target),
      value: expected, element_name: '', expected: expected,
    })
  }
  return rows
}

export const toEditorRows = (stepMapping) => {
  const rows = (stepMapping || []).flatMap(fromPipelineMapping)
  return rows.map((r, i) => ({ ...r, seq: i + 1 }))
}
