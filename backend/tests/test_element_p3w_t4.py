"""Task 4 (elem-p3w T4) tests — 页面树层级 + 别名默认中文."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override_db(mock_db):
    from app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db


def _fake_page(**kw):
    page = MagicMock()
    page.id = uuid.uuid4()
    page.project_id = uuid.UUID(PID)
    page.page_name = "P"
    page.page_url = "http://p/"
    page.screenshot_url = None
    page.element_count = 0
    page.last_fetch_at = None
    page.created_at = None
    page.updated_at = None
    page.parent_id = kw.get("parent_id")
    page.to_dict = lambda: {
        "id": str(page.id), "project_id": PID, "page_name": "P",
        "page_url": "http://p/", "screenshot_url": None,
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "element_count": 0, "last_fetch_at": None,
        "created_at": None, "updated_at": None,
    }
    return page


def _db_returning_page(page):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = page
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------- Part B: 别名默认中文 ----------------


def _run_batch_import(page, elements):
    from app.services.element_service import ElementService
    db = _db_returning_page(page)
    return ElementService.batch_import_elements.__wrapped__ if False else None, db


@pytest.mark.asyncio
async def test_alias_default_chinese_counter_per_type():
    """无 text/name 的元素 → {类型中文}{序号}（按类型计序）."""
    from app.services.element_service import ElementService
    page = _fake_page()
    db = _db_returning_page(page)
    elements = [
        {"type": "button", "id": "btnA", "locator_chain": {"strategies": []}},
        {"type": "button", "id": "btnB", "locator_chain": {"strategies": []}},
        {"type": "input", "id": "inA", "locator_chain": {"strategies": []}},
    ]
    imported = await ElementService.batch_import_elements(db, page.id, elements)
    names = [e.element_name for e in imported]
    assert names == ["按钮1", "按钮2", "输入框1"]


@pytest.mark.asyncio
async def test_alias_prefers_element_text():
    """有 element_text 时优先用文本."""
    from app.services.element_service import ElementService
    page = _fake_page()
    db = _db_returning_page(page)
    elements = [
        {"type": "button", "id": "btnX", "text": "提 交", "locator_chain": {"strategies": []}},
        {"type": "other", "id": "zz", "locator_chain": {"strategies": []}},
    ]
    imported = await ElementService.batch_import_elements(db, page.id, elements)
    assert imported[0].element_name == "提 交"
    assert imported[1].element_name == "元素1"


@pytest.mark.asyncio
async def test_alias_user_provided_wins():
    """用户提供的 element_name > 中文默认."""
    from app.services.element_service import ElementService
    page = _fake_page()
    db = _db_returning_page(page)
    elements = [
        {"type": "button", "id": "b1", "element_name": "我的按钮", "locator_chain": {"strategies": []}},
    ]
    imported = await ElementService.batch_import_elements(db, page.id, elements)
    assert imported[0].element_name == "我的按钮"


# ---------------- Part A: 页面树端点 ----------------


def test_page_tree_endpoint(client):
    """GET /elements/pages/tree → 按 parent_id 组装嵌套树."""
    root1, root2, child = _fake_page(), _fake_page(), _fake_page()
    child.parent_id = root1.id
    for p in (root1, root2, child):
        p.last_fetch_at = None

    db = MagicMock()
    result = MagicMock()
    scal = MagicMock()
    scal.all.return_value = [root1, root2, child]
    result.scalars.return_value = scal
    db.execute = AsyncMock(return_value=result)
    _override_db(db)

    r = client.get(f"/api/v1/elements/pages/tree?project_id={PID}")
    assert r.status_code == 200, r.text
    d = r.json()
    data = d["data"] if isinstance(d, dict) and "data" in d else d
    assert len(data) == 2
    top1 = next(n for n in data if n["id"] == str(root1.id))
    assert [c["id"] for c in top1["children"]] == [str(child.id)]
