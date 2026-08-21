"""W3 version history tests."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.models.test_case import CaseVersion, TestCase


def test_case_version_model_fields():
    cols = {c.name for c in CaseVersion.__table__.columns}
    assert {"id", "case_id", "version", "snapshot", "diff_summary", "changed_by", "created_at"} <= cols
    snap = CaseVersion.__table__.c.snapshot
    assert snap.type.__class__.__name__ == "JSONB"


def test_case_version_registered_in_models_init():
    import app.models as m
    assert hasattr(m, "CaseVersion")
