"""
Knowledge Service Tests
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from uuid import uuid4

# Add backend directory to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Mock only the DB and AI gateway dependencies (not the whole app package),
# so the real app.models / app.services packages stay importable.
# Save the originals so we can restore after loading this module (otherwise the
# MagicMock replacement leaks into other test modules, e.g. test_moonshot_provider
# which needs the real ai_gateway classes).
_saved_db = sys.modules.get('app.core.database')
_saved_knowledge_model = sys.modules.get('app.models.knowledge')
_saved_ai_gateway = sys.modules.get('app.services.ai_gateway')
sys.modules['app.core.database'] = MagicMock()
sys.modules['app.models.knowledge'] = MagicMock()
sys.modules['app.services.ai_gateway'] = MagicMock()

# Now load the actual knowledge_service module code by reading and executing it
import importlib.util
knowledge_service_path = backend_path / "app" / "services" / "knowledge_service.py"
spec = importlib.util.spec_from_file_location("knowledge_service", knowledge_service_path)
knowledge_service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(knowledge_service_module)

KnowledgeService = knowledge_service_module.KnowledgeService

# Restore real modules so downstream tests see the genuine ai_gateway/classes.
for _name, _orig in [
    ('app.core.database', _saved_db),
    ('app.models.knowledge', _saved_knowledge_model),
    ('app.services.ai_gateway', _saved_ai_gateway),
]:
    if _orig is not None:
        sys.modules[_name] = _orig
    else:
        sys.modules.pop(_name, None)


class TestKnowledgeService:
    """Test Knowledge Service"""

    def test_split_text_small(self):
        """Test chunking with text smaller than chunk_size"""
        text = "Short text"
        chunks = KnowledgeService._split_text(text, chunk_size=500, overlap=50)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_split_text_with_overlap(self):
        """Test chunking logic with 1000 chars, chunk_size=500, overlap=50"""
        # Create text with exactly 1000 characters
        text = "a" * 1000
        chunks = KnowledgeService._split_text(text, chunk_size=500, overlap=50)

        # Verify at least 2 chunks
        assert len(chunks) >= 2

        # Verify overlap: last 50 chars of chunk[0] == first 50 chars of chunk[1]
        assert chunks[0][-50:] == chunks[1][:50]
