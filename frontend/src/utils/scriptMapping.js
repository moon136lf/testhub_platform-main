// pipeline step_mapping → StepEditor 行式结构 的公共映射（ScriptConvert / AutoUITest 共用）
//
// 阶段3验收反馈修订：断言不再拆行（7 步变 14 行太乱）——每条 pipeline 步骤
// 一行，断言期望合并进行内 expected 字段；codegen 对非空 expected 的动作行
// 追加 to_have_text（assert_db 行保持 DB 比对语义）。

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
  // 断言期望合并进行内（不再拆行）：assertion.expected 非空时填 expected，
  // codegen 对非 assert_db 动作行的非空 expected 追加 to_have_text
  const assertExpected = (m.assertion && m.assertion.expected) || ''
  // 仅模糊断言（is_valid=false，如"进入登录页"）不落断言——避免生成永真断言
  const assertValid = !(m.assertion && m.assertion.is_valid === false)
  return [{
    seq: m.step || 0,
    action,
    target: action === 'navigate' ? '' : (extractLocator(m.impl) || m.element_name || ''),
    value: m.value || '',
    element_name: m.element_name || '',
    expected: (assertExpected && assertValid) ? assertExpected : '',
  }]
}

export const toEditorRows = (stepMapping) => {
  const rows = (stepMapping || []).flatMap(fromPipelineMapping)
  return rows.map((r, i) => ({ ...r, seq: i + 1 }))
}
