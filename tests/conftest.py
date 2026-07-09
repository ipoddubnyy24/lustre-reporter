"""Shared test fixtures/helpers."""
import sys
from pathlib import Path

import pytest

# Belt-and-suspenders: make the package importable even without pyproject pythonpath.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lustre_reporter import config as cfgmod  # noqa: E402
from lustre_reporter.cli import ToolResult  # noqa: E402
from lustre_reporter.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Keep the suite hermetic: never read a developer's real config.local.json
    (which may carry live credentials, e.g. a Slack webhook). Tests that want a
    config file set LUSTRE_REPORTER_CONFIG themselves, overriding this."""
    monkeypatch.delenv("LUSTRE_REPORTER_CONFIG", raising=False)
    monkeypatch.setattr(cfgmod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfgmod, "APP_SUPPORT", tmp_path / "app-support")


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
