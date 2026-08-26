"""Notifier stub tests (P1 push placeholder)."""
import pytest
from app.services.notifier import Notifier, notify_report_ready


@pytest.mark.asyncio
async def test_notify_does_not_raise():
    n = Notifier()
    await n.notify_report_ready("exec-1", {"html_url": "x"})


@pytest.mark.asyncio
async def test_module_helper():
    await notify_report_ready("exec-1", {"score": 90})
