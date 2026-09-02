"""CodeStructureAnalyzer tests (pure regex parsing, zero mocks)."""
from app.services.code_structure_analyzer import CodeStructureAnalyzer


ROUTER_JS = '''
const routes = [
  { path: '/dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '仪表盘' } },
  {
    path: '/cases',
    name: 'Cases',
    component: () => import('@/views/Cases.vue'),
    meta: { title: '用例管理' }
  },
  { path: '/settings/ai', name: 'AISettings', meta: { title: 'AI设置' } },
]
'''

API_PY = '''
@router.get("/projects")
async def list_projects():
    """获取项目列表"""
    ...

@router.post("/projects")
async def create_project(req: ProjectCreate):
    ...

@router.delete("/projects/{id}")
async def delete_project(id: str):
    """删除项目"""
    ...

@other_router.post("/scan")
async def trigger_scan(req):
    ...
'''


class TestAnalyzeFrontend:
    def test_extracts_routes_with_titles(self, tmp_path):
        rdir = tmp_path / "frontend" / "src" / "router"
        rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(ROUTER_JS, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        assert len(menus) == 3
        assert menus[0]["path"] == "/dashboard"
        assert menus[0]["title"] == "仪表盘"
        assert menus[1]["title"] == "用例管理"

    def test_skips_redirect_and_node_modules(self, tmp_path):
        rdir = tmp_path / "src" / "router"
        rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(
            "{ path: '/a', redirect: '/b' },\n"
            "{ path: '/b', name: 'B', meta: { title: 'B页' } },", encoding="utf-8")
        nm = tmp_path / "node_modules" / "x" / "router"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text(ROUTER_JS, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        assert len(menus) == 1  # redirect 行跳过, node_modules 忽略


class TestAnalyzeBackend:
    def test_extracts_api_endpoints(self, tmp_path):
        apidir = tmp_path / "backend" / "app" / "api" / "v1"
        apidir.mkdir(parents=True)
        (apidir / "projects.py").write_text(API_PY, encoding="utf-8")
        apis = CodeStructureAnalyzer().analyze_backend(str(tmp_path))
        assert len(apis) >= 3
        m = {(a["method"], a["path"]) for a in apis}
        assert ("GET", "/projects") in m
        assert ("POST", "/projects") in m
        assert ("DELETE", "/projects/{id}") in m
        # docstring 首行
        desc = next(a["desc"] for a in apis if a["method"] == "GET" and a["path"] == "/projects")
        assert "项目列表" in desc
        # 无 docstring 的有默认值 (函数名)
        post_desc = next(a["desc"] for a in apis if a["method"] == "POST" and a["path"] == "/projects")
        assert post_desc

    def test_empty_repo_returns_empty(self, tmp_path):
        assert CodeStructureAnalyzer().analyze_frontend(str(tmp_path)) == []
        assert CodeStructureAnalyzer().analyze_backend(str(tmp_path)) == []


# ---- V1.1 修复: 嵌套路由块提取 + redirect 不连坐 + .claude/worktrees 跳过 ----

ROUTER_JS_NESTED = '''
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: Layout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'Dashboard', component: Dashboard, meta: { title: '仪表盘' } },
        { path: 'cases', name: 'Cases', component: Cases, meta: { title: '用例管理' } },
        { path: 'ai', name: 'AI', component: AI, meta: { title: 'AI智能' } },
      ]
    },
    { path: '/login', name: 'Login', component: Login },
    { path: '/reports', name: 'Reports', component: Reports, meta: { title: '执行记录' } },
  ]
})
'''


class TestNestedRoutes:
    def test_nested_children_extracted(self, tmp_path):
        """嵌套 children 路由逐条提取; 顶层 redirect 不连坐其他路由."""
        rdir = tmp_path / "src" / "router"
        rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(ROUTER_JS_NESTED, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        paths = [m["path"] for m in menus]
        assert "dashboard" in paths
        assert "cases" in paths
        assert "ai" in paths
        assert "/reports" in paths
        assert len(menus) == 5  # login 无 title 也算菜单; 顶层 '/' 的 path 锚点也切出, 但 redirect+无 title 不影响其他条
        titles = [m.get("title") for m in menus]
        assert "仪表盘" in titles
        assert "用例管理" in titles

    def test_skips_claude_worktrees(self, tmp_path):
        """.claude/worktrees 下的旧 router 不重复扫描."""
        wt = tmp_path / ".claude" / "worktrees" / "x" / "src" / "router"
        wt.mkdir(parents=True)
        (wt / "index.js").write_text(ROUTER_JS, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        assert menus == []
