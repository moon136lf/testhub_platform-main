"""AI gateway token logging tests (W10埋点).

These tests verify the W10 ai_call_log 埋点 added to ``AIGateway.chat``:
- passing ``project_id`` writes a log entry via ``log_ai_call``
- omitting ``project_id`` skips logging
- a logging failure never breaks the chat call (best-effort)

The genuine ``ai_gateway.py`` is loaded directly via ``importlib.util`` (rather
than ``from app.services.ai_gateway import AIGateway``) because some other test
modules replace ``sys.modules['app.services.ai_gateway']`` with a MagicMock at
collection time, which would otherwise leak in here and make ``AIGateway`` a
non-class. ``log_ai_call`` is then patched with ``patch.object`` on the loaded
module object so the patch targets the exact module whose globals ``chat``
looks up — avoiding any sys.modules / package-import cascade.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND_PATH = Path(__file__).parent.parent
_AI_GATEWAY_PATH = _BACKEND_PATH / "app" / "services" / "ai_gateway.py"


def _load_ai_gateway_module(module_name: str):
    """Load the genuine ai_gateway module from source under ``module_name``."""
    spec = importlib.util.spec_from_file_location(module_name, _AI_GATEWAY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gateway_with_mock_provider():
    """Build an AIGateway with a single mock provider registered."""
    ai_gateway_module = _load_ai_gateway_module("ai_gateway_for_logging_test")
    AIGateway = ai_gateway_module.AIGateway

    gw = AIGateway.__new__(AIGateway)
    gw._providers = {"glm-2.5": MagicMock()}
    gw._providers["glm-2.5"].chat_completion = AsyncMock(return_value={"content": "hi", "tokens": 150})
    return gw, ai_gateway_module


@pytest.mark.asyncio
async def test_chat_with_project_id_writes_log(gateway_with_mock_provider):
    gw, ai_gateway_module = gateway_with_mock_provider
    with patch.object(ai_gateway_module, "log_ai_call", new=AsyncMock()) as mock_log:
        result = await gw.chat(
            [{"role": "user", "content": "x"}],
            provider="glm-2.5",
            project_id="00000000-0000-0000-0000-000000000001",
            stage="identify_point",
        )
        assert result["content"] == "hi"
        mock_log.assert_awaited_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["project_id"] == "00000000-0000-0000-0000-000000000001"
        assert call_kwargs["provider_name"] == "glm-2.5"
        assert call_kwargs["tokens"] == 150
        assert call_kwargs["stage"] == "identify_point"


@pytest.mark.asyncio
async def test_chat_without_project_id_skips_log(gateway_with_mock_provider):
    gw, ai_gateway_module = gateway_with_mock_provider
    with patch.object(ai_gateway_module, "log_ai_call", new=AsyncMock()) as mock_log:
        await gw.chat([{"role": "user", "content": "x"}], provider="glm-2.5")
        mock_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_failure_does_not_break_chat(gateway_with_mock_provider):
    gw, ai_gateway_module = gateway_with_mock_provider
    with patch.object(ai_gateway_module, "log_ai_call", new=AsyncMock(side_effect=Exception("db down"))):
        # should NOT raise — logging is best-effort
        result = await gw.chat(
            [{"role": "user", "content": "x"}],
            provider="glm-2.5",
            project_id="00000000-0000-0000-0000-000000000001",
            stage="identify_point",
        )
        assert result["content"] == "hi"
