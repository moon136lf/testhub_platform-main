"""CodeStructureAnalyzer — 静态解析前端路由与后端 API 端点（纯 regex，零依赖）。"""
import os
import re
from typing import Any


class CodeStructureAnalyzer:
    """扫描代码仓库，提取前端菜单（Vue Router 路由）与后端 API 端点（FastAPI 装饰器）。"""

    # 跳过的目录（第三方/构建产物）
    SKIP_DIRS = {"node_modules", "dist", "build", ".git", "__pycache__", "venv", ".venv"}

    # 路由对象内的字段提取
    _PATH_RE = re.compile(r"path\s*:\s*['\"]([^'\"]+)['\"]")
    _REDIRECT_RE = re.compile(r"\bredirect\s*:")
    _META_RE = re.compile(r"meta\s*:\s*\{([^{}]*)\}")
    _TITLE_RE = re.compile(r"title\s*:\s*['\"]([^'\"]+)['\"]")

    # FastAPI 装饰器：@router.get("/path") / @other_router.post(...)
    _API_RE = re.compile(
        r"@[\w]*router\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]*)['\"]",
        re.IGNORECASE,
    )
    _FUNC_RE = re.compile(r"def\s+(\w+)\s*\(")
    _DOCSTRING_RE = re.compile(r"['\"]{3}([^'\"]*)")

    def analyze_frontend(self, repo_path: str) -> list[dict[str, Any]]:
        """提取 Vue Router 路由：[{path, name, title}]，跳过 redirect 路由。"""
        menus: list[dict[str, Any]] = []
        for js_path in self._walk(repo_path, (".js", ".ts")):
            if "router" not in js_path.replace("\\", "/").lower():
                continue
            try:
                content = self._read(js_path)
            except OSError:
                continue
            for block in self._route_blocks(content):
                if self._REDIRECT_RE.search(block):
                    continue
                m = self._PATH_RE.search(block)
                if not m:
                    continue
                route: dict[str, Any] = {"path": m.group(1)}
                name = re.search(r"name\s*:\s*['\"]([^'\"]+)['\"]", block)
                if name:
                    route["name"] = name.group(1)
                meta = self._META_RE.search(block)
                if meta:
                    title = self._TITLE_RE.search(meta.group(1))
                    if title:
                        route["title"] = title.group(1)
                menus.append(route)
        return menus

    def analyze_backend(self, repo_path: str) -> list[dict[str, Any]]:
        """提取 FastAPI 端点：[{method, path, desc}]，desc 为 docstring 首行（缺省用函数名）。"""
        apis: list[dict[str, Any]] = []
        for py_path in self._walk(repo_path, (".py",)):
            try:
                content = self._read(py_path)
            except OSError:
                continue
            for m in self._API_RE.finditer(content):
                method = m.group(1).upper()
                path = m.group(2)
                tail = content[m.end(): m.end() + 2000]
                func = self._FUNC_RE.search(tail)
                desc = ""
                if func:
                    # docstring 在函数签名之后
                    after_sig = tail[func.end():]
                    doc = self._DOCSTRING_RE.search(after_sig)
                    if doc:
                        desc = doc.group(1).strip().splitlines()[0].strip()
                if not desc:
                    desc = func.group(1) if func else path.rsplit("/", 1)[-1] or path
                apis.append({"method": method, "path": path, "desc": desc})
        return apis

    # ------------------------------------------------------------------ utils

    def _walk(self, root: str, exts: tuple[str, ...]):
        """递归遍历目录，跳过 SKIP_DIRS，产出匹配扩展名的文件路径。"""
        if not os.path.isdir(root):
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(exts):
                    yield os.path.join(dirpath, fn)

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def _route_blocks(content: str) -> list[str]:
        """按 { } 大致切分路由对象块（支持单行与多行写法）。"""
        blocks: list[str] = []
        depth = 0
        start = None
        for i, ch in enumerate(content):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        blocks.append(content[start: i + 1])
                        start = None
        return blocks
