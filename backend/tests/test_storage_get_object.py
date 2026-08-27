"""storage get_object_bytes tests."""
import pytest
from unittest.mock import MagicMock, patch
from app.core.storage import StorageClient


def test_get_object_bytes_returns_bytes():
    client = StorageClient()
    client.client = MagicMock()
    # minio get_object returns a response with .stream (iterable of bytes)
    client.client.get_object.return_value = MagicMock(
        stream=[b"<html>", b"report</html>"]
    )
    data = client.get_object_bytes("reports/exec-1.html")
    assert b"<html>report</html>" in data


def test_get_object_bytes_fallback_when_no_client():
    client = StorageClient()
    client.client = None
    client._fallback_store["reports/x.html"] = b"fallback-data"
    data = client.get_object_bytes("reports/x.html")
    assert data == b"fallback-data"


def test_get_object_bytes_missing_in_fallback_returns_empty():
    client = StorageClient()
    client.client = None
    data = client.get_object_bytes("reports/not-stored.html")
    assert data == b""
