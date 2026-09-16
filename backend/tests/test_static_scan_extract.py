"""StaticScanService.vue 提取器：template截取/交互元素识别/hash"""
import shutil, tempfile, os
import pytest
from app.services.static_scan_service import StaticScanService

CASES_VUE = """<template>
  <div class="cases">
    <el-button type="primary" @click="showCreateDialog">新建用例</el-button>
    <el-input v-model="keyword" placeholder="搜索用例" />
    <a href="/detail" class="row-link">详情</a>
    <span class="plain">不可交互</span>
  </div>
</template>
<script setup>
const keyword = ref('')
</script>
"""

MIN_VUE = """<template><button @click="go">提交</button></template>
<script>export default {}</script>
"""


ATTRS_VUE = """<template>
  <div>
    <el-button data-id="btn1">数据编号</el-button>
    <el-button id="real-id" name="real-name" data-testid="tid">正常属性</el-button>
    <el-input v-model="q"></el-input><div>搜索</div>
    <el-button><el-icon>+</el-icon>新建</el-button>
    <input type="text" />
  </div>
</template>
"""

@pytest.fixture
def repo(tmp_path):
    views = tmp_path / "src" / "views"
    views.mkdir(parents=True)
    (views / "Cases.vue").write_text(CASES_VUE, encoding="utf-8")
    (views / "Min.vue").write_text(MIN_VUE, encoding="utf-8")
    (views / "no_template.css").write_text(".a{}", encoding="utf-8")
    (views / "Attrs.vue").write_text(ATTRS_VUE, encoding="utf-8")
    return tmp_path


class TestExtract:
    def test_extracts_vue_components(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        paths = {c["file_path"] for c in comps}
        assert "src/views/Cases.vue" in paths
        assert "src/views/Min.vue" in paths

    def test_interactive_elements_only(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        cases = next(c for c in comps if c["component_name"] == "Cases")
        tags = [e["tag"] for e in cases["elements"]]
        assert "el-button" in tags and "el-input" in tags and "a" in tags
        assert "span" not in tags  # 非交互元素剔除

    def test_element_attrs_captured(self, repo):
        svc = StaticScanService()
        cases = next(c for c in svc.extract_components(str(repo))
                     if c["component_name"] == "Cases")
        btn = next(e for e in cases["elements"] if e["tag"] == "el-button")
        assert btn["text"] == "新建用例"
        inp = next(e for e in cases["elements"] if e["tag"] == "el-input")
        assert inp["placeholder"] == "搜索用例"
        assert inp["v_model"] == "keyword"

    def test_content_hash_stable_and_sensitive(self, repo):
        svc = StaticScanService()
        c1 = svc.extract_components(str(repo))
        h_before = {c["file_path"]: c["content_hash"] for c in c1}
        # 重跑相同内容 hash 一致
        h_again = {c["file_path"]: c["content_hash"] for c in svc.extract_components(str(repo))}
        assert h_before == h_again
        # 改内容 hash 变
        (repo / "src" / "views" / "Min.vue").write_text(
            MIN_VUE.replace("提交", "确认"), encoding="utf-8")
        h_after = {c["file_path"]: c["content_hash"] for c in svc.extract_components(str(repo))}
        assert h_after["src/views/Min.vue"] != h_before["src/views/Min.vue"]

    def test_template_snippet_truncated(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        for c in comps:
            assert len(c["template_snippet"]) <= 4000

    def test_skip_dirs_and_non_vue(self, repo):
        node_modules = repo / "node_modules" / "pkg"
        node_modules.mkdir(parents=True)
        (node_modules / "X.vue").write_text("<template><button>x</button></template>", encoding="utf-8")
        svc = StaticScanService()
        paths = {c["file_path"] for c in svc.extract_components(str(repo))}
        assert all("node_modules" not in p for p in paths)


def _attrs_elements(repo):
    svc = StaticScanService()
    comp = next(c for c in svc.extract_components(str(repo))
                if c["component_name"] == "Attrs")
    return comp["elements"]


class TestFixes:
    def test_empty_tag_no_sibling_text(self, repo):
        # I-1: 空非自闭合标签不应抓到兄弟文本 "搜索"
        els = _attrs_elements(repo)
        inp = next(e for e in els if e.get("v_model") == "q")
        assert inp["text"] is None

    def test_nested_child_not_own_text(self, repo):
        # I-1: 嵌套子元素 "+" 不归属父按钮，text 取 "新建"
        els = _attrs_elements(repo)
        btn = next(e for e in els if e["text"] == "新建")
        assert btn is not None

    def test_data_id_not_matched_as_id(self, repo):
        # I-2: data-id 不应被当作 id
        els = _attrs_elements(repo)
        btn = next(e for e in els if e["text"] == "数据编号")
        assert btn["id"] is None

    def test_id_name_testid_normal(self, repo):
        els = _attrs_elements(repo)
        btn = next(e for e in els if e["text"] == "正常属性")
        assert btn["id"] == "real-id"
        assert btn["name"] == "real-name"
        assert btn["data_testid"] == "tid"

    def test_self_closing_no_text(self, repo):
        els = _attrs_elements(repo)
        inp = next(e for e in els if e["tag"] == "input")
        assert inp["text"] is None
