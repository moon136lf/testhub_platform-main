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
        <el-button type="warning" plain :disabled="!selectedRows.length"
          @click="openBulkMigrate">迁移（{{ selectedRows.length }}）</el-button>
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
        <el-tree
          v-if="pages.length"
          :data="pages"
          node-key="id"
          :props="{ label: 'page_name', children: 'children' }"
          default-expand-all
          :expand-on-click-node="false"
        >
          <template #default="{ data }">
            <span
              class="tree-node page-node"
              :class="{ active: treeFilter.mode === 'page' && treeFilter.pageId === data.id }"
              @click="selectNode('page', data.id)"
              @contextmenu.prevent="openCtxMenu($event, data)"
            >📄 {{ data.page_name }} <span class="count">({{ data.element_count ?? 0 }})</span></span>
          </template>
        </el-tree>
        <div v-if="!pages.length" class="tree-empty">暂无页面，请先在「元素抓取」页抓取或点击右上角新增</div>
      </el-card>

      <el-card shadow="never" class="table-card">
        <el-table :data="elements" v-loading="loading" stripe @selection-change="onSelectionChange">
          <el-table-column type="selection" width="42" />
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
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link :icon="Edit" @click="openEditDialog(row)">编辑</el-button>
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
        <div class="ctx-item" @click="openPageEdit">编辑</div>
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

    <!-- 新建元素（全屏大弹窗，容纳定位器编辑） -->
    <el-dialog v-model="createDialogVisible" title="新建元素" width="860px" top="6vh">
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
            <el-option v-for="p in flattenTree(pages)" :key="p.id" :label="p.page_name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="定位器">
          <div style="width:100%">
            <div v-for="(loc, i) in createForm.locators" :key="i" class="locator-edit-row">
              <el-select v-model="loc.type" style="width:170px">
                <el-option v-for="t in ['id', 'css', 'data-testid', 'text', 'xpath']" :key="t" :label="t" :value="t" />
              </el-select>
              <el-input v-model="loc.value" placeholder="定位表达式" style="flex:1" />
              <el-input-number v-model="loc.score" :min="0" :max="150" style="width:120px" />
              <span class="locator-move-btns">
                <el-button text type="primary" class="locator-move-btn"
                  :disabled="i === 0" @click="moveCreateLocator(i, -1)">▲</el-button>
                <el-button text type="primary" class="locator-move-btn"
                  :disabled="i === createForm.locators.length - 1" @click="moveCreateLocator(i, 1)">▼</el-button>
              </span>
              <el-button type="danger" text @click="createForm.locators.splice(i, 1)">删除</el-button>
            </div>
            <el-button text type="primary" @click="createForm.locators.push({ type: 'css', value: '', score: 50 })">+ 添加定位器</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑元素（全屏大弹窗：字段+定位器增删调序+校验，详情并入此处） -->
    <el-dialog v-model="editDialogVisible" title="编辑元素" width="860px" top="6vh">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="editForm.element_type" style="width: 100%">
            <el-option v-for="t in ['button', 'input', 'link', 'select', 'other']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示文本">
          <el-input v-model="editForm.element_text" />
        </el-form-item>
        <el-form-item label="作用域" required>
          <el-radio-group v-model="editForm.scope" disabled>
            <el-radio value="page">页面级</el-radio>
            <el-radio value="global">全局</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editForm.scope === 'page'" label="所属页面" required>
          <el-select v-model="editForm.page_id" style="width: 100%" placeholder="选择页面">
            <el-option v-for="p in flattenTree(pages)" :key="p.id" :label="p.page_name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="定位器">
          <div style="width:100%">
            <div v-for="(loc, i) in editForm.locators" :key="i" class="locator-edit-row">
              <el-select v-model="loc.type" style="width:170px">
                <el-option v-for="t in ['id', 'css', 'data-testid', 'text', 'xpath']" :key="t" :label="t" :value="t" />
              </el-select>
              <el-input v-model="loc.value" placeholder="定位表达式" style="flex:1" />
              <el-input-number v-model="loc.score" :min="0" :max="150" style="width:120px" />
              <span class="locator-move-btns">
                <el-button text type="primary" class="locator-move-btn"
                  :disabled="i === 0" @click="moveEditLocator(i, -1)">▲</el-button>
                <el-button text type="primary" class="locator-move-btn"
                  :disabled="i === editForm.locators.length - 1" @click="moveEditLocator(i, 1)">▼</el-button>
              </span>
              <el-button type="danger" text @click="editForm.locators.splice(i, 1)">删除</el-button>
            </div>
            <el-button text type="primary" @click="editForm.locators.push({ type: 'css', value: '', score: 50 })">+ 添加定位器</el-button>
          </div>
        </el-form-item>
        <el-form-item label="校验">
          <div class="verify-section">
            <el-button type="primary" plain :loading="verifying" @click="verifyEditPrimary">校验首选定位</el-button>
            <span class="locator-count-hint">校验列表中 score 最高的定位器（真实页面跑一次）</span>
          </div>
          <div v-if="editVerifyResult" class="verify-result" style="width:100%">
            <template v-if="editVerifyResult.error">
              <div class="verify-error">校验失败：{{ editVerifyResult.error }}</div>
            </template>
            <template v-else>
              命中 <b>{{ editVerifyResult.hit_count }}</b> 个 · score {{ editVerifyResult.score }}
            </template>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 回收站弹窗 -->
    <el-dialog v-model="recycleDialogVisible" title="回收站（30天内可恢复）" width="860px">
      <el-table :data="recycleItems" v-loading="recycleLoading">
        <el-table-column prop="element_name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="page_name" label="所属页面" width="140" show-overflow-tooltip />
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
    <!-- 页面编辑弹窗（名称+URL） -->
    <el-dialog v-model="pageEditVisible" title="编辑页面" width="440px">
      <el-form label-width="80px">
        <el-form-item label="页面名称" required>
          <el-input v-model="pageEditForm.name" @keyup.enter="submitPageEdit" />
        </el-form-item>
        <el-form-item label="页面 URL">
          <el-input v-model="pageEditForm.url" placeholder="完整 URL，如 http://host/path" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pageEditVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPageEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 迁移元素：双页面树选择目标（删页迁移 / 批量迁移共用） -->
    <el-dialog v-model="migrateVisible" :title="bulkMigrateMode ? '迁移元素到目标页面' : '迁移元素到'" width="640px">
      <div class="migrate-tip">
        {{ bulkMigrateMode
          ? `将 ${selectedRows.length} 个元素迁移到左侧选中目标页面（已排除所选元素当前所在页面）。`
          : '左侧为可选目标页面树（已排除被删页面及其子级），点击选中目标后确认。' }}
      </div>
      <div class="migrate-body">
        <div class="migrate-pane">
          <div class="migrate-pane-title">目标页面树</div>
          <el-tree
            :data="bulkMigrateMode ? bulkMigrateTreeData : migrateTreeData"
            node-key="id"
            :props="{ label: 'page_name', children: 'children' }"
            default-expand-all
            :expand-on-click-node="false"
            :highlight-current="true"
            @node-click="(d) => (migrateTargetId = d.id)"
          >
            <template #default="{ data }">
              <span class="migrate-node" :class="{ picked: migrateTargetId === data.id }">
                📄 {{ data.page_name }}
              </span>
            </template>
          </el-tree>
        </div>
        <div class="migrate-arrow">→</div>
        <div class="migrate-pane">
          <div class="migrate-pane-title">已选目标</div>
          <div v-if="migrateTargetId" class="migrate-picked-name">
            {{ flattenTree(pages).find((p) => p.id === migrateTargetId)?.page_name }}
          </div>
          <div v-else class="migrate-empty">尚未选择</div>
        </div>
      </div>
      <template #footer>
        <el-button @click="cancelMigrate">取消</el-button>
        <el-button type="primary" @click="bulkMigrateMode ? confirmBulkMigrate() : confirmMigrate()">确认迁移</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Upload, Download, Edit } from '@element-plus/icons-vue'
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
const verifying = ref(false)

// ---- 弹窗 ----
const createDialogVisible = ref(false)
const createForm = ref({ name: '', element_type: 'button', element_text: '', scope: 'page', page_id: null, locators: [] })
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
    // 页面树用嵌套接口（按 parent_id 组装，子级缩进展示）
    const response = await elementAPI.getPageTree(projectId.value)
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

// ---- 页面编辑弹窗（名称+URL，问题17） ----
const pageEditVisible = ref(false)
const pageEditForm = ref({ id: null, name: '', url: '' })

const openPageEdit = () => {
  const page = ctxMenu.page
  closeCtxMenu()
  if (!page) return
  pageEditForm.value = { id: page.id, name: page.page_name, url: page.page_url || '' }
  pageEditVisible.value = true
}

const submitPageEdit = async () => {
  const form = pageEditForm.value
  if (!(form.name || '').trim()) {
    ElMessage.warning('请输入页面名称')
    return
  }
  try {
    await elementAPI.renamePage(form.id, form.name.trim(), (form.url || '').trim())
    ElMessage.success('页面已保存')
    pageEditVisible.value = false
    loadPages()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
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
        // confirm：迁移 —— 双树选择目标页面（左树可选，右树为已选目标，含子级页面）
        const pagesOptions = flattenTree(pages.value).filter(p => p.id !== page.id)
        if (!pagesOptions.length) {
          ElMessage.warning('没有其他页面可迁移，请先新增页面')
          return
        }
        const target = await pickTargetPage(page)
        if (!target) return
        await elementAPI.deletePageNode(page.id, target.id, null)
        ElMessage.success(`页面已删除，元素已迁移到「${target.page_name}」`)
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

// ---- 迁移目标双树弹窗 ----
const flattenTree = (nodes, out = []) => {
  for (const n of nodes || []) {
    out.push(n)
    if (n.children?.length) flattenTree(n.children, out)
  }
  return out
}

const migrateVisible = ref(false)
const migrateSourcePage = ref(null)
const migrateTargetId = ref(null)
// 迁移目标树：排除被删页面本身及其子树（子树会一并删除）
const migrateTreeData = computed(() => {
  const exclude = (nodes) => {
    if (!migrateSourcePage.value) return nodes
    return nodes
      .filter((n) => n.id !== migrateSourcePage.value.id)
      .map((n) => ({ ...n, children: n.children?.length ? exclude(n.children) : [] }))
  }
  return exclude(pages.value)
})

const pickTargetPage = (sourcePage) => {
  bulkMigrateMode.value = false
  migrateSourcePage.value = sourcePage
  migrateTargetId.value = null
  migrateVisible.value = true
  return new Promise((resolve) => { migrateResolve.value = resolve })
}
const migrateResolve = ref(null)
const confirmMigrate = () => {
  const target = flattenTree(pages.value).find((p) => p.id === migrateTargetId.value)
  if (!target) {
    ElMessage.warning('请先在右侧选择目标页面')
    return
  }
  migrateVisible.value = false
  migrateResolve.value?.(target)
  migrateResolve.value = null
}
const cancelMigrate = () => {
  migrateVisible.value = false
  migrateResolve.value?.(null)
  migrateResolve.value = null
}

// ---- 批量迁移元素（问题19：勾选单个/多个 → 迁移按钮 → 双树选目标） ----
const selectedRows = ref([])
const onSelectionChange = (rows) => { selectedRows.value = rows }
const bulkMigrateTargetId = ref(null)
const bulkMigrateMode = ref(false)

// 批量迁移目标树：排除已选元素所在页面（迁到同页无意义）
const bulkMigrateTreeData = computed(() => {
  const srcIds = new Set(selectedRows.value.map((r) => r.page_id).filter(Boolean))
  const exclude = (nodes) => nodes
    .filter((n) => !srcIds.has(n.id))
    .map((n) => ({ ...n, children: n.children?.length ? exclude(n.children) : [] }))
  return exclude(pages.value)
})

const openBulkMigrate = () => {
  if (!selectedRows.value.length) return
  if (selectedRows.value.every((r) => r.scope === 'global')) {
    ElMessage.warning('所选元素均为全局元素（无页面归属），无需迁移')
    return
  }
  bulkMigrateMode.value = true
  migrateTargetId.value = null
  migrateVisible.value = true
}

const confirmBulkMigrate = async () => {
  const target = flattenTree(pages.value).find((p) => p.id === migrateTargetId.value)
  if (!target) {
    ElMessage.warning('请先在左侧选择目标页面')
    return
  }
  try {
    const ids = selectedRows.value.filter((r) => r.scope !== 'global').map((r) => r.id)
    const r = await elementAPI.moveElementsToPage(ids, target.id)
    ElMessage.success(`已迁移 ${r.data?.moved ?? ids.length} 个元素到「${target.page_name}」`)
    migrateVisible.value = false
    selectedRows.value = []
    loadElements()
    loadPages()
  } catch (e) {
    ElMessage.error('迁移失败: ' + (e.response?.data?.detail || e.message || e))
  }
}

// ---- 编辑元素（字段与新建一致，弹窗展示） ----
const editDialogVisible = ref(false)
const editForm = ref({ id: null, name: '', element_type: 'button', element_text: '', scope: 'page', page_id: null, locators: [] })
// 编辑保存时记录定位器原序，删除/新增的分别处理
let editOriginalLocators = []

const openEditDialog = (row) => {
  const raw = extractLocators(row)
  editOriginalLocators = raw.map((s) => ({ ...s }))
  editForm.value = {
    id: row.id,
    name: row.element_name || '',
    element_type: row.element_type || 'button',
    element_text: row.element_text || '',
    scope: row.scope || 'page',
    page_id: row.page_id || null,
    locators: raw.map((s) => ({ type: s.type, value: s.value, score: s.score })),
  }
  editVerifyResult.value = null  // 重置上次校验结果
  editDialogVisible.value = true
}

// 编辑弹窗内定位器行上移/下移（本地数组交换，保存时统一按差异同步）
const moveEditLocator = (i, dir) => {
  const arr = editForm.value.locators
  const j = i + dir
  if (j < 0 || j >= arr.length) return
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

// 新建弹窗内定位器行上移/下移（同编辑）
const moveCreateLocator = (i, dir) => {
  const arr = createForm.value.locators
  const j = i + dir
  if (j < 0 || j >= arr.length) return
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

// 编辑弹窗内校验首选定位（详情页校验能力并入编辑，问题8/15）
const editVerifyResult = ref(null)
const verifyEditPrimary = async () => {
  const locs = editForm.value.locators || []
  if (!locs.length) {
    ElMessage.warning('该元素暂无定位器，请先添加')
    return
  }
  // score 最高者为首选（与详情页 drawerLocators 排序一致）
  const loc = locs.slice().sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0]
  verifying.value = true
  editVerifyResult.value = null
  try {
    const response = await elementAPI.verifyLocator(editForm.value.id, loc.type, loc.value)
    const data = (response && response.data) || response || {}
    editVerifyResult.value = data
  } catch (e) {
    editVerifyResult.value = { error: e.response?.data?.detail || e.message || String(e) }
  } finally {
    verifying.value = false
  }
}

const submitEdit = async () => {
  const form = editForm.value
  if (!form.name || !form.element_type) {
    ElMessage.warning('请填写名称和类型')
    return
  }
  if (form.scope === 'page' && !form.page_id) {
    ElMessage.warning('页面级元素需选择所属页面')
    return
  }
  try {
    // 基础字段（后端白名单校验）
    await elementAPI.updateElement(form.id, {
      element_name: form.name,
      element_type: form.element_type,
      element_text: form.element_text || undefined,
      page_id: form.scope === 'page' ? form.page_id : undefined,
    })
    // 定位器差异同步：以原始列表为基准做删除 + 调序，再追加新增行。
    // 以「后端当前实际列表」为准：拉一次最新数据，避免弹窗打开期间后端已被其他
    // 操作修改（如上次保存已删过）导致原序索引越界（400 定位器索引越界）
    const freshResp = await elementAPI.listElementsAsset(projectId.value, { page: 1, pageSize: 100 })
    const freshItems = (freshResp && freshResp.data && freshResp.data.items) || []
    const freshEl = freshItems.find((e) => e.id === form.id)
    const serverLocators = freshEl ? extractLocators(freshEl) : editOriginalLocators
    const keptValues = new Set(form.locators.map((l) => `${l.type}|${l.value}`))
    // 1) 删除：服务器列表中不在现列表的，从尾往前删（避免索引位移）
    for (let i = serverLocators.length - 1; i >= 0; i--) {
      const orig = serverLocators[i]
      if (!keptValues.has(`${orig.type}|${orig.value}`)) {
        try {
          await elementAPI.deleteLocator(form.id, i)
        } catch (e) {
          // 越界（并发修改）容忍：跳过该条继续，最后统一以服务器为准刷新
          if (!(e.response && e.response.status === 400)) throw e
        }
      }
    }
    // 2) 重算删除后的原序列表，再按现列表顺序提交 reorder + add
    const remaining = serverLocators.filter(
      (o) => keptValues.has(`${o.type}|${o.value}`))
    const remainingKeys = new Set(remaining.map((o) => `${o.type}|${o.value}`))
    // 现列表中已存在项：按现列表顺序对原序做对齐（简单做法：若顺序不同则逐个 down 顶到位置——
    // 为避免复杂度，直接采用「删除全部再新增」以外的方式：已存在项顺序与原序一致时跳过）
    const existingKept = form.locators.filter((l) => remainingKeys.has(`${l.type}|${l.value}`))
    // 若顺序有变化，用 reorder 逐条上移到目标位置
    for (let target = 0; target < existingKept.length; target++) {
      const key = `${existingKept[target].type}|${existingKept[target].value}`
      const curRawIdx = remaining.indexOf(remaining.find((o) => `${o.type}|${o.value}` === key))
      if (curRawIdx !== target) {
        await elementAPI.reorderLocator(form.id, curRawIdx, 'up')
        // 同步本地 remaining 视图
        const [moved] = remaining.splice(curRawIdx, 1)
        remaining.splice(target, 0, moved)
      }
    }
    // 3) 新增项：原列表没有的逐条 add
    const originalKeys = new Set(serverLocators.map((o) => `${o.type}|${o.value}`))
    for (const l of form.locators) {
      if (!originalKeys.has(`${l.type}|${l.value}`)) {
        await elementAPI.addLocator(form.id, l.type, l.value, l.score)
      }
    }
    ElMessage.success('元素已保存')
    editDialogVisible.value = false
    loadElements()
    loadPages()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message || e))
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
    locators: [],  // 重置定位器行（showCreateDialog 复用对象缺失此键 → push 报错）
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
  if ((form.locators || []).some((l) => (l.value || '').trim() && !l.type)) {
    ElMessage.warning('定位器需选择类型')
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
      locators: (form.locators || [])
        .filter((l) => (l.value || '').trim())
        .map((l) => ({ type: l.type, value: l.value.trim(), score: l.score, source: 'manual' })),
    })
    ElMessage.success('元素已创建')
    createDialogVisible.value = false
    createForm.value = { name: '', element_type: 'button', element_text: '', scope: 'page', page_id: null, locators: [] }
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
.migrate-tip {
  font-size: 13px;
  color: #909399;
  margin-bottom: 10px;
}
.migrate-body {
  display: grid;
  grid-template-columns: 1fr 40px 1fr;
  align-items: start;
  min-height: 260px;
}
.migrate-pane {
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 4px;
  padding: 8px;
  max-height: 320px;
  overflow: auto;
}
.migrate-pane-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.migrate-arrow {
  text-align: center;
  color: #909399;
  font-size: 18px;
  padding-top: 8px;
}
.migrate-node {
  font-size: 13px;
  cursor: pointer;
  display: inline-block;
  padding: 0 4px;
  border-radius: 3px;
  width: 100%;
}
.migrate-node.picked {
  background: var(--el-color-primary-light-9, #ecf5ff);
  color: var(--el-color-primary, #409eff);
}
.migrate-picked-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-color-primary, #409eff);
  padding: 8px 4px;
}
.migrate-empty {
  color: #c0c4cc;
  font-size: 13px;
  padding: 8px 4px;
}
/* 编辑/新建弹窗定位器行：对齐 + 统一尺寸 */
.locator-edit-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.locator-move-btns {
  display: inline-flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  line-height: 1;
  gap: 0;
  width: 24px;
  flex: none;
  align-self: stretch;
}
.locator-move-btn {
  padding: 0 !important;
  height: 15px !important;
  width: 24px !important;
  font-size: 11px;
  line-height: 15px !important;
  margin: 0 !important;
}
.locator-count-hint {
  font-size: 12px;
  color: #909399;
}
.verify-section {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
</style>
