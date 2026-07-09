"""Thin subprocess wrapper around the ``llm_jira`` CLI tools.

We shell out to the installed ``gerrit``/``gc``, ``jira`` and ``maloo``
commands rather than importing their internals: they already emit JSON on
stdout and load their own credentials/settings (``~/.jira-tool.json``,
``~/.config/gerrit-cli/.env``, ``~/.config/maloo-tool/.env``), which is exactly
what the user asked for — "use llm_jira for settings".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


class ToolError(RuntimeError):
    """A CLI tool failed, was missing, or returned an error payload."""

    def __init__(self, tool: str, message: str, *, kind: str = "error"):
        super().__init__(message)
        self.tool = tool
        self.kind = kind  # "missing" | "auth" | "error"


@dataclass
class ToolResult:
    ok: bool
    data: object
    error: str | None = None
    kind: str | None = None  # "missing" | "auth" | "error" when not ok


# Tools may take a few seconds; Maloo aggregation can be slow.
_DEFAULT_TIMEOUT = 90


def _is_available(tool: str) -> bool:
    return shutil.which(tool) is not None


def _classify(payload: object, stderr: str) -> tuple[str, str]:
    """Map a tool error payload to a (kind, message)."""
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("message") or payload.get("error") or "")
    text = text or stderr or "unknown error"
    low = text.lower()
    if "401" in low or "unauthor" in low or "credential" in low or "403" in low:
        return "auth", text
    return "error", text


def run_json(tool: str, args: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> ToolResult:
    """Run ``tool args...`` and parse stdout as JSON.

    Returns a ToolResult; never raises for expected failure modes (missing
    binary, auth error, non-zero exit) so callers can degrade gracefully.
    """
    if not _is_available(tool):
        return ToolResult(
            ok=False,
            data=None,
            error=f"'{tool}' not found on PATH. Install the llm_jira tools "
            f"(~/work/src/llm_jira/install.sh).",
            kind="missing",
        )

    try:
        proc = subprocess.run(
            [tool, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, data=None,
                          error=f"'{tool}' timed out after {timeout}s", kind="error")

    stdout = proc.stdout.strip()
    payload: object = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

    # These CLIs report errors as a JSON object with a "code"/"message", and
    # often still exit 0. Treat that as a failure.
    if isinstance(payload, dict) and payload.get("code") and "message" in payload:
        kind, msg = _classify(payload, proc.stderr)
        return ToolResult(ok=False, data=None, error=msg, kind=kind)

    if proc.returncode != 0:
        kind, msg = _classify(payload, proc.stderr)
        return ToolResult(ok=False, data=None, error=msg, kind=kind)

    if payload is None:
        return ToolResult(ok=False, data=None,
                          error=f"'{tool}' returned no parseable JSON", kind="error")

    return ToolResult(ok=True, data=payload)
