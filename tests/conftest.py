"""Shared test fixtures/helpers."""
import sys
from pathlib import Path

import pytest

# Belt-and-suspenders: make the package importable even without pyproject pythonpath.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lustre_reporter.cli import ToolResult  # noqa: E402
from lustre_reporter.config import Config  # noqa: E402


@pytest.fixture
def cfg():
    """A fresh default Config (es6/es7, community+exa masters)."""
    return Config()


@pytest.fixture
def tr():
    """Factory for ToolResult."""
    def make(data=None, ok=True, error=None, kind=None):
        return ToolResult(ok=ok, data=data, error=error, kind=kind)
    return make
