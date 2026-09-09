<template>
  <div class="element-list page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h2>元素管理</h2>
        <div class="page-subtitle">按页面树浏览元素，支持全局共享元素、多定位器置信度调序</div>
      </div>
      <div class="header-actions">
        <el-select v-model="projectId" filterable placeholder="选择项目" style="width: 220px" @change="onProjectChange">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-select v-model="scopeFilter" clearable placeholder="作用域：全部" style="width: 150px"
          :disabled="treeFilter.mode === 'page'" @change="onScopeChange" @clear="onScopeChange">
          <el-option label="页面级" value="page" />
          <el-option label="全局" value="global" />
        </el-select>
        <el-input v-model="keyword" placeholder="搜索元素名称/文本，回车触发" clearable style="width: 240px"
          @keyup.enter="loadElements" @clear="loadElements" />
        <el-button :icon="Upload" @click="importDialogVisible = true">导入</el-button>
        <el-button :icon="Download" @click="handleExport">导出</el-button>
        <el-button :icon="Delete" @click="openRecycleBin">回收站</el-button>
        <el-button type="primary" :icon="Plus" @click="showCreateDialog">新建元素</el-button>
      </div>
    </div>

    <!-- 主体：左页面树 + 右表格 -->
    <div class="body-grid">
      <el-card shadow="never" class="tree-card">
        <template #header>
          <div class="tree-header">
            <span>页面树</span>
            <el-button size="small" text type="primary" :icon="Plus" @click="addPage">新增页面</el-button>
          </div>
        </template>
        <div
          class="tree-node" :class="{ active: treeFilter.mode === 'all' }"
          @click="selectNode('all')"
        >📁 全部元素</div>
        <div
          v-for="page in pages" :key="page.id"
          class="tree-node page-node" :class="{ active: treeFilter.mode === 'page' && treeFilter.pageId === page.id }"
          @click="selectNode('page', page.id)"
          @contextmenu.prevent="openCtxMenu($event, page)"
        >📄 {{ page.page_name }} <span class="count">({{ page.element_count ?? 0 }})</span></div>
        <div v-if="!pages.length" class="tree-empty">暂无页面，请先在「元素抓取」页抓取或点击右上角新增</div>
      </el-card>

      <el-card shadow="never" class="table-card">
        <el-table :data="elements" v-loading="loading" stripe>
          <el-table-column type="index" :index="indexOffset" label="序号" width="70" align="center" />
          <el-table-column prop="element_name" label="元素名" min-width="160" show-overflow-tooltip />
          <el-table-column prop="element_type" label="类型" width="90">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.element_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="首选定位" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <code class="locator-code" v-if="primaryLocator(row)">{{ primaryLocator(row).type }}: {{ primaryLocator(row).value }}</code>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="作用域" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.scope === 'global' ? 'warning' : 'info'">
                {{ row.scope === 'global' ? '全局' : '页面' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="所属页面" width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.page_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-switch :model-value="row.status === 'active'" @change="(v) => toggleStatus(row, v)" />
              <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'" style="margin-left: 6px">
                {{ row.status === 'active' ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="引用数" width="80" align="center">
            <template #default="{ row }">{{ refCounts[row.id] ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="来源" width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag size="small" :type="sourceTag(row.source)">{{ sourceLabel(row.source) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="160">
            <template #default="{ row }">{{ formatTime(row.updated_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link :icon="View" @click="openDetail(row)">详情</el-button>
              <el-button type="danger" link :icon="Delete" @click="deleteElement(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            :total="total"
            layout="total, sizes, prev, pager, next"
            @size-change="loadElements"
            @current-change="loadElements"
          />
        </div>
      </el-card>
    </div>

    <!-- 右键上下文菜单 -->
    <teleport to="body">
      <div v-if="ctxMenu.visible" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }">
        <div class="ctx-item" @click="openPageCreate('sub')">新建子级页面</div>
        <div class="ctx-item" @click="openPageCreate('sibling')">新建同级页面</div>
        <div class="ctx-item" @click="renamePage">重命名</div>
        <div class="ctx-item" @click="moveCtxPage('up')">上移</div>
        <div class="ctx-item" @click="moveCtxPage('down')">下移</div>
        <div class="ctx-item danger" @click="deleteCtxPage">删除</div>
      </div>
    </teleport>

    <!-- 新建子级/同级页面弹窗 -->
    <el-dialog v-model="pageCreateVisible" :title="pageCreateMode === 'sub' ? '新建子级页面' : '新建同级页面'" width="440px">
      <el-form label-width="80px">
        <el-form-item label="页面名称" required>
          <el-input v-model="pageCreateForm.name" placeholder="必填" @keyup.enter="submitPageCreate" />
        </el-form-item>
        <el-form-item label="页面 URL">
          <el-input v-model="pageCreateForm.url" placeholder="可选，留空后端生成占位 URL" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pageCreateVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPageCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="detailRow?.element_name || '元素详情'" size="480px">
      <div v-if="detailRow" class="detail-body">
        <div class="detail-tags">
          <el-tag type="info">{{ detailRow.element_type }}</el-tag>
          <el-tag :type="detailRow.scope === 'global' ? 'warning' : 'info'">
            {{ detailRow.scope === 'global' ? '全局' : '页面' }}
          </el-tag>
          <el-tag :type="statusTag(detailRow.status)">{{ detailRow.status }}</el-tag>
        </div>
        <div v-if="detailRow.element_text" class="detail-text">显示文本：{{ detailRow.element_text }}</div>

        <div class="section-title">
          定位器（按置信度排序）
          <el-button size="small" text type="primary" :icon="Plus" @click="locatorDialogVisible = true">自定义定位器</el-button>
        </div>
        <div class="section-title">
          定位器（数组原序，↑↓ 调序后后端重算 score）
          <el-button size="small" text type="primary" :icon="Plus" @click="locatorDialogVisible = true">自定义定位器</el-button>
        </div>
        <div v-if="primaryIndex >= 0" class="detail-text">
          首选定位：<code class="locator-code">{{ drawerLocators[primaryIndex].type }}: {{ drawerLocators[primaryIndex].value }}</code>
        </div>
        <div v-for="(loc, idx) in drawerLocators" :key="idx" class="locator-row">
          <span class="star" v-if="idx === primaryIndex">★</span>
          <code class="locator-code">{{ loc.type }}: {{ loc.value }}</code>
          <el-tag size="small" type="success">{{ loc.score }}</el-tag>
          <el-tag v-if="loc.source" size="small" type="info">{{ loc.source }}</el-tag>
          <span class="locator-ops">
            <el-button size="small" text :disabled="idx === 0" @click="reorder(idx, 'up')">↑</el-button>
            <el-button size="small" text :disabled="idx === drawerLocators.length - 1" @click="reorder(idx, 'down')">↓</el-button>
          </span>
        </div>
        <div v-if="!drawerLocators.length" class="tree-empty">暂无定位器</div>

        <div class="section-title">
          校验
          <el-button size="small" type="primary" plain :loading="verifying" @click="verifyPrimary">校验首选定位</el-button>
        </div>
        <div v-if="verifyResult" class="verify-result">
          <template v-if="verifyResult.error">
            <div class="verify-error">校验失败：{{ verifyResult.error }}</div>
          </template>
          <template v-else>
            命中 <b>{{ verifyResult.hit_count }}</b> 个 · score {{ verifyResult.score }}
          </template>
        </div>

        <div class="section-title">引用脚本（{{ refCounts[detailRow.id] ?? '-' }}）</div>
        <div v-for="s in refScripts" :key="s.id" class="ref-script">{{ s.name }}</div>
        <div v-if="refsLoaded && !refScripts.length" class="tree-empty">暂无脚本引用</div>
      </div>
    </el-drawer>

    <!-- 自定义定位器弹窗 -->
    <el-dialog v-model="locatorDialogVisible" title="添加自定义定位器" width="440px">
      <el-form label-width="70px">
        <el-form-item label="类型">
          <el-select v-model="newLocator.type" style="width: 100%">
            <el-option v-for="t in ['id', 'css', 'data-testid', 'text', 'xpath', '自定义']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="newLocator.value" placeholder="定位表达式" />
        </el-form-item>
        <el-form-item label="置信度">
          <el-input-number v-model="newLocator.score" :min="0" :max="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="locatorDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitLocator">添加</el-button>
      </template>
    </el-dialog>

    <!-- 新建元素弹窗 -->
    <el-dialog v-model="createDialogVisible" title="新建元素" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="createForm.element_type" style="width: 100%">
            <el-option v-for="t in ['button', 'input', 'link', 'select', 'other']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示文本">
          <el-input v-model="createForm.element_text" />
        </el-form-item>
        <el-form-item label="作用域" required>
          <el-radio-group v-model="createForm.scope">
            <el-radio value="page">页面级</el-radio>
            <el-radio value="global">全局</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.scope === 'page'" label="所属页面" required>
          <el-select v-model="createForm.page_id" style="width: 100%" placeholder="选择页面">
            <el-option v-for="p in pages" :key="p.id" :label="p.page_name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 回收站弹窗 -->
    <el-dialog v-model="recycleDialogVisible" title="回收站（30天内可恢复）" width="600px">
      <el-table :data="recycleItems" v-loading="recycleLoading" size="small">
        <el-table-column prop="element_name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="element_type" label="类型" width="90" />
        <el-table-column label="回收时间" width="160">
          <template #default="{ row }">{{ formatTime(row.recycled_at || row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="restoreElement(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 导入弹窗 -->
    <el-dialog v-model="importDialogVisible" title="导入元素" width="480px">
      <div class="import-tip">
        选择此前导出的 JSON 文件（elements_export_*.json），导入时会按元素名+页面去重，已存在则跳过。
      </div>
      <el-upload
        drag
        accept=".json"
        :auto-upload="false"
        :show-file-list="false"
        :on-change="handleImportFile"
      >
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">拖拽或点击选择 .json 文件</div>
      </el-upload>
      <div v-if="importResult" class="import-result">
        <div>导入 {{ importResult.imported }} 条，跳过 {{ importResult.skipped }} 条</div>
        <div v-for="(e, i) in (importResult.errors || [])" :key="i" class="verify-error">{{ e }}</div>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, View, Upload, Download } from '@element-plus/icons-vue'
import { elementAPI } from '@/api/element.js'
import { projectAPI } from '@/api/project.js'

const loading = ref(false)
const projects = ref([])
const projectId = ref('')
const pages = ref([])
const elements = ref([])
const keyword = ref('')
const refCounts = reactive({})
const refCountsLoaded = ref(false)

const treeFilter = ref({ mode: 'all', pageId: null })
const scopeFilter = ref('')

// ---- 分页 ----
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const indexOffset = (index) => (page.value - 1) * pageSize.value + index + 1

// ---- 详情抽屉 ----
const detailVisible = ref(false)
const detailRow = ref(null)
const refScripts = ref([])
const refsLoaded = ref(false)
const verifying = ref(false)
const verifyResult = ref(null)

// ---- 弹窗 ----
const locatorDialogVisible = ref(false)
const newLocator = ref({ type: 'css', value: '', score: 50 })
const createDialogVisible = ref(false)
const createForm = ref({ name: '', element_type: 'button', element_text: '', scope: 'page', page_id: null })
const recycleDialogVisible = ref(false)
const recycleLoading = ref(false)
const recycleItems = ref([])
const importDialogVisible = ref(false)
const importResult = ref(null)

// ---- 右键菜单 ----
const ctxMenu = reactive({ visible: false, x: 0, y: 0, page: null })
const closeCtxMenu = () => { ctxMenu.visible = false }

// 后端 to_dict 返回 locator_strategies: {strategies: [...]}，兼容 locators 字段
const extractLocators = (row) => {
  const ls = row?.locator_strategies
  if (Array.isArray(ls)) return ls
  if (ls && Array.isArray(ls.strategies)) return ls.strategies
  return row?.locators || []
}

const primaryLocator = (row) => {
  const locs = extractLocators(row).slice()
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  return locs[0] || null
}

const drawerLocators = computed(() => extractLocators(detailRow.value))

// 首选 = score 最高那条（按数组原序展示行，★ 可能不在第一行，用户调序后归位）
const primaryIndex = computed(() => {
  const locs = drawerLocators.value
  if (!locs.length) return -1
  let best = 0
  locs.forEach((l, i) => {
    if ((l.score ?? 0) > (locs[best].score ?? 0)) best = i
  })
  return best
})

const statusTag = (status) => {
  if (status === 'active' || status === 'verified') return 'success'
  if (status === 'stale' || status === 'deprecated') return 'danger'
  return 'info'
}

// ---- 来源中文映射 ----
const SOURCE_MAP = {
  manual: { label: '手工', tag: 'warning' },
  auto: { label: '自动抓取', tag: 'success' },
  healed: { label: '自愈', tag: 'danger' },
  ai_fixed: { label: 'AI修复', tag: 'primary' },
}
const sourceLabel = (source) => SOURCE_MAP[source]?.label || '原始'
const sourceTag = (source) => SOURCE_MAP[source]?.tag || 'info'

const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  })
}

// ---- 数据加载 ----
const loadPages = async () => {
  try {
    const response = await elementAPI.listPages(projectId.value)
    pages.value = (response && response.data) || response || []
  } catch (e) {
    console.error('加载页面树失败:', e)
    pages.value = []
  }
}

const loadElements = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const filter = treeFilter.value
    const response = await elementAPI.listElementsAsset(projectId.value, {
      scope: filter.mode === 'page' ? undefined : (scopeFilter.value || undefined),
      pageId: filter.mode === 'page' ? filter.pageId : undefined,
      keyword: keyword.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    // 分页信封 {code, data: {items, total, page, page_size}}
    const data = (response && response.data) || {}
    elements.value = data.items || []
    total.value = data.total ?? elements.value.length
    loadRefCounts()
  } catch (e) {
    ElMessage.error('获取元素列表失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

// ---- 状态切换 ----
const toggleStatus = async (row, enabled) => {
  try {
    await elementAPI.setElementStatus(row.id, enabled ? 'active' : 'deprecated')
    row.status = enabled ? 'active' : 'deprecated'
    ElMessage.success(enabled ? '已启用' : '已禁用')
  } catch (e) {
    ElMessage.error('状态切换失败: ' + (e.message || e))
    loadElements()
  }
}

// 引用数：仅对前 50 条逐个查询，简单限流
const loadRefCounts = async () => {
  refCountsLoaded.value = false
  const targets = elements.value.slice(0, 50)
  for (const el of targets) {
    try {
      const response = await elementAPI.elementReferences(el.id, projectId.value)
      const data = (response && response.data) || response || {}
      refCounts[el.id] = data.count ?? 0
    } catch {
      refCounts[el.id] = '-'
    }
  }
  refCountsLoaded.value = true
}

const loadAll = async () => {
  await Promise.all([loadPages(), loadElements()])
}

const fetchProjects = async () => {
  try {
    const response = await projectAPI.list()
    projects.value = response.items || response || []
    if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].id
    }
  } catch (e) {
    console.error('获取项目列表失败:', e)
  }
}

const onProjectChange = () => {
  treeFilter.value = { mode: 'all', pageId: null }
  scopeFilter.value = ''
  loadAll()
}

const selectNode = (mode, pageId = null) => {
  treeFilter.value = { mode, pageId }
  if (mode !== 'all') scopeFilter.value = ''
  loadElements()
}

const onScopeChange = () => {
  // 下拉触发时回到「全部元素」节点（页面节点自带 page 过滤，与下拉互斥）
  if (treeFilter.value.mode !== 'all') treeFilter.value = { mode: 'all', pageId: null }
  loadElements()
}

// ---- 页面树操作 ----
const addPage = async () => {
  try {
    const { value } = await ElMessageBox.prompt('输入页面名称', '新增页面', { inputPattern: /\S+/ })
    await elementAPI.createSubPage({ project_id: projectId.value, page_name: value })
    ElMessage.success('页面已创建')
    loadPages()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('创建页面失败: ' + (e.message || e))
  }
}

const openCtxMenu = (event, page) => {
  ctxMenu.visible = true
  ctxMenu.x = event.clientX
  ctxMenu.y = event.clientY
  ctxMenu.page = page
}

// ---- 右键新建子级/同级页面 ----
const pageCreateVisible = ref(false)
const pageCreateMode = ref('sub') // 'sub' | 'sibling'
const pageCreateForm = ref({ name: '', url: '' })
const pageCreateParentId = ref(null)

const openPageCreate = (mode) => {
  const page = ctxMenu.page
  closeCtxMenu()
  if (!page) return
  pageCreateMode.value = mode
  if (mode === 'sub') {
    pageCreateParentId.value = page.id
  } else {
    pageCreateParentId.value = page.parent_id || null
  }
  pageCreateForm.value = { name: '', url: '' }
  pageCreateVisible.value = true
}

const submitPageCreate = async () => {
  const name = (pageCreateForm.value.name || '').trim()
  if (!name) {
    ElMessage.warning('请输入页面名称')
    return
  }
  try {
    await elementAPI.createSubPage({
      project_id: projectId.value,
      parent_id: pageCreateParentId.value,
      page_name: name,
      page_url: (pageCreateForm.value.url || '').trim() || undefined,
    })
    ElMessage.success('页面已创建')
    pageCreateVisible.value = false
    loadPages()
  } catch (e) {
    ElMessage.error('创建页面失败: ' + (e.message || e))
  }
}

const renamePage = async () => {
  const page = ctxMenu.page
  closeCtxMenu()
  try {
    const { value } = await ElMessageBox.prompt('输入新名称', '重命名页面', { inputValue: page.page_name, inputPattern: /\S+/ })
    await elementAPI.renamePage(page.id, value)
    ElMessage.success('已重命名')
    loadPages()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('重命名失败: ' + (e.message || e))
  }
}

const moveCtxPage = async (direction) => {
  const page = ctxMenu.page
  closeCtxMenu()
  try {
    await elementAPI.movePage(page.id, direction)
    loadPages()
  } catch (e) {
    ElMessage.error('移动失败: ' + (e.message || e))
  }
}

const deleteCtxPage = async () => {
  const page = ctxMenu.page
  closeCtxMenu()
  try {
    await elementAPI.deletePageNode(page.id, null, null)
    ElMessage.success('页面已删除')
    if (treeFilter.value.pageId === page.id) selectNode('all')
    loadPages()
  } catch (e) {
    // 400：页面下有元素，让用户选迁移或强制删除
    if (e.response && e.response.status === 400) {
      try {
        const action = await ElMessageBox.confirm(
          `页面「${page.page_name}」下仍有元素，请选择处理方式`,
          '删除页面',
          {
            distinguishCancelAndClose: true,
            confirmButtonText: '迁移元素到其他页面',
            cancelButtonText: '连元素一起删除(force)',
            type: 'warning',
          }
        )
        // confirm：迁移 —— 选目标页面
        const pagesOptions = pages.value.filter(p => p.id !== page.id)
        if (!pagesOptions.length) {
          ElMessage.warning('没有其他页面可迁移，请先新增页面')
          return
        }
        const { value } = await ElMessageBox.prompt(
          '输入目标页面名称（从下列选择）：\n' + pagesOptions.map(p => p.page_name).join('、'),
          '迁移元素到', { inputPattern: /\S+/ }
        )
        const target = pagesOptions.find(p => p.page_name === value.trim())
        if (!target) {
          ElMessage.error('未找到该页面')
          return
        }
        await elementAPI.deletePageNode(page.id, target.id, null)
        ElMessage.success('页面已删除，元素已迁移')
      } catch (e2) {
        if (e2 === 'cancel') {
          // 强制删除
          try {
            await elementAPI.deletePageNode(page.id, null, true)
            ElMessage.success('页面及元素已删除')
          } catch (e3) {
            ElMessage.error('删除失败: ' + (e3.message || e3))
          }
        } else if (e2 !== 'close') {
          ElMessage.error('删除失败: ' + (e2.message || e2))
        }
      }
      if (treeFilter.value.pageId === page.id) selectNode('all')
      loadPages()
    } else {
      ElMessage.error('删除失败: ' + (e.message || e))
    }
  }
}

// ---- 详情 ----
const openDetail = async (row) => {
  detailRow.value = row
  verifyResult.value = null
  refScripts.value = []
  refsLoaded.value = false
  detailVisible.value = true
  try {
    const response = await elementAPI.elementReferences(row.id, projectId.value)
    const data = (response && response.data) || response || {}
    refScripts.value = data.scripts || []
    refCounts[row.id] = data.count ?? 0
    refsLoaded.value = true
  } catch {
    refsLoaded.value = true
  }
}

const reorder = async (index, direction) => {
  const el = detailRow.value
  if (!el) return
  try {
    await elementAPI.reorderLocator(el.id, index, direction)
    // 本地交换后刷新抽屉
    const locs = extractLocators(el).slice().sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    if (direction === 'up' && index > 0) {
      [locs[index - 1], locs[index]] = [locs[index], locs[index - 1]]
    } else if (direction === 'down' && index < locs.length - 1) {
      [locs[index + 1], locs[index]] = [locs[index], locs[index + 1]]
    }
    el.locator_strategies = { strategies: locs }
    loadElements()
  } catch (e) {
    ElMessage.error('调序失败: ' + (e.message || e))
  }
}

const submitLocator = async () => {
  const el = detailRow.value
  if (!newLocator.value.value) {
    ElMessage.warning('请输入定位值')
    return
  }
  try {
    await elementAPI.addLocator(el.id, newLocator.value.type, newLocator.value.value, newLocator.value.score)
    ElMessage.success('定位器已添加')
    locatorDialogVisible.value = false
    newLocator.value = { type: 'css', value: '', score: 50 }
    // 后端返回的 locators 可能未含新增项，重新拉该元素列表并保持抽屉打开
    const response = await elementAPI.listElementsAsset(projectId.value, {
      scope: treeFilter.value.mode === 'page' ? undefined : (scopeFilter.value || undefined),
      pageId: treeFilter.value.mode === 'page' ? treeFilter.value.pageId : undefined,
      keyword: keyword.value || undefined,
    })
    elements.value = (response && response.data) || response || []
    const fresh = elements.value.find(e => e.id === el.id)
    if (fresh) detailRow.value = fresh
  } catch (e) {
    ElMessage.error('添加定位器失败: ' + (e.message || e))
  }
}

const verifyPrimary = async () => {
  const el = detailRow.value
  const loc = primaryLocator(el)
  if (!loc) {
    ElMessage.warning('该元素暂无定位器')
    return
  }
  verifying.value = true
  try {
    const response = await elementAPI.verifyLocator(el.id, loc.type, loc.value)
    const data = (response && response.data) || response || {}
    // 后端可能 code:0 但 data.error 非空（校验失败），需展示
    verifyResult.value = data
  } catch (e) {
    verifyResult.value = { error: e.message || String(e) }
  } finally {
    verifying.value = false
  }
}

// ---- 删除 / 回收站 ----
const deleteElement = async (row) => {
  try {
    const response = await elementAPI.elementReferences(row.id, projectId.value)
    const data = (response && response.data) || response || {}
    const count = data.count ?? 0
    if (count > 0) {
      await ElMessageBox.confirm(
        `该元素被 ${count} 个脚本引用，删除将影响这些脚本。确认删除（软删，30天可恢复）？`,
        '确认删除',
        { type: 'warning' }
      )
    } else {
      await ElMessageBox.confirm(
        `确认删除元素「${row.element_name}」？（软删，30天可恢复）`,
        '确认删除',
        { type: 'warning' }
      )
    }
    await elementAPI.recycleElement(row.id)
    ElMessage.success('已移入回收站')
    loadElements()
    loadPages()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e))
  }
}

const openRecycleBin = async () => {
  recycleDialogVisible.value = true
  recycleLoading.value = true
  try {
    const response = await elementAPI.recycleBin(projectId.value)
    recycleItems.value = (response && response.data) || response || []
  } catch (e) {
    ElMessage.error('获取回收站失败: ' + (e.message || e))
  } finally {
    recycleLoading.value = false
  }
}

const restoreElement = async (row) => {
  try {
    await elementAPI.restoreElement(row.id)
    ElMessage.success('已恢复')
    openRecycleBin()
    loadElements()
    loadPages()
  } catch (e) {
    ElMessage.error('恢复失败: ' + (e.message || e))
  }
}

// ---- 新建 ----
const showCreateDialog = () => {
  createForm.value = {
    name: '',
    element_type: 'button',
    element_text: '',
    scope: treeFilter.value.mode === 'global' ? 'global' : 'page',
    page_id: treeFilter.value.mode === 'page' ? treeFilter.value.pageId : (pages.value[0]?.id || null),
  }
  createDialogVisible.value = true
}

const submitCreate = async () => {
  const form = createForm.value
  if (!form.name || !form.element_type) {
    ElMessage.warning('请填写名称和类型')
    return
  }
  if (form.scope === 'page' && !form.page_id) {
    ElMessage.warning('页面级元素需选择所属页面')
    return
  }
  try {
    await elementAPI.createElementAsset({
      project_id: projectId.value,
      name: form.name,
      element_type: form.element_type,
      element_text: form.element_text || undefined,
      scope: form.scope,
      page_id: form.scope === 'page' ? form.page_id : undefined,
      locators: [],
    })
    ElMessage.success('元素已创建')
    createDialogVisible.value = false
    loadElements()
    loadPages()
  } catch (e) {
    ElMessage.error('创建失败: ' + (e.message || e))
  }
}

// ---- 导出 / 导入 ----
const handleExport = async () => {
  try {
    const response = await elementAPI.exportElements(projectId.value)
    const data = (response && response.data) || response
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const date = new Date().toISOString().slice(0, 10)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `elements_export_${date}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.message || e))
  }
}

const handleImportFile = async (file) => {
  importResult.value = null
  try {
    const text = await file.raw.text()
    const payload = JSON.parse(text)
    const response = await elementAPI.importElementsAsset(projectId.value, payload)
    const data = (response && response.data) || response || {}
    importResult.value = data
    ElMessage.success(`导入 ${data.imported ?? 0} 条，跳过 ${data.skipped ?? 0} 条`)
    loadElements()
    loadPages()
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.message || e))
  }
}

onMounted(async () => {
  document.addEventListener('click', closeCtxMenu)
  await fetchProjects()
  if (projectId.value) loadAll()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeCtxMenu)
})
</script>

<style scoped>
.element-list.page-container {
  display: flex;
  flex-direction: column;
}

.page-subtitle {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-top: 4px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.body-grid {
  display: grid;
  grid-template-columns: 250px 1fr;
  gap: 16px;
  margin-top: 16px;
  align-items: start;
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tree-node {
  padding: 8px 10px;
  border-radius: var(--mt-radius-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--mt-text);
  user-select: none;
}

.tree-node:hover {
  background: var(--mt-sidebar-hover-bg);
}

.tree-node.active {
  background: var(--mt-primary-light);
  color: var(--mt-primary);
  font-weight: 600;
}

.tree-node .count {
  color: var(--mt-text-secondary);
  font-size: 12px;
}

.tree-empty {
  font-size: 12px;
  color: var(--mt-text-secondary);
  padding: 8px 10px;
}

.locator-code {
  background: var(--mt-bg);
  border: 1px solid var(--mt-border);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  color: var(--mt-text);
}

/* ---- 右键菜单 ---- */
.ctx-menu {
  position: fixed;
  z-index: 3000;
  background: #1E293B;
  border-radius: 6px;
  padding: 4px 0;
  min-width: 130px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}

.ctx-item {
  padding: 7px 16px;
  color: #E2E8F0;
  font-size: 13px;
  cursor: pointer;
}

.ctx-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.ctx-item.danger {
  color: #FCA5A5;
}

/* ---- 详情抽屉 ---- */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-tags {
  display: flex;
  gap: 8px;
}

.detail-text {
  font-size: 13px;
  color: var(--mt-text-secondary);
}

.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  margin-top: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--mt-border);
}

.locator-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.star {
  color: var(--mt-warning);
}

.locator-ops {
  margin-left: auto;
  display: flex;
}

.verify-result {
  font-size: 13px;
  padding: 8px 10px;
  background: var(--mt-bg);
  border-radius: var(--mt-radius-sm);
}

.verify-error {
  color: var(--mt-danger);
  font-size: 12px;
  margin-top: 4px;
}

.ref-script {
  font-size: 13px;
  padding: 4px 0;
  color: var(--mt-text);
}

/* ---- 导入 ---- */
.import-tip {
  font-size: 13px;
  color: var(--mt-text-secondary);
  margin-bottom: 12px;
}

.import-result {
  margin-top: 12px;
  font-size: 13px;
}
</style>
