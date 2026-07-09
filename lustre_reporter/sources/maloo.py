"""Maloo CI test-results access via the ``maloo`` CLI.

Powers the build/test stability report. Maloo aggregates the nightly CI test
sessions per branch (``trigger_job``), e.g. ``lustre-b_es6_0``. When Maloo
credentials are missing or rejected (HTTP 401) the ToolResult carries
kind="auth"/"missing" so the UI can show an actionable "not configured" state
instead of crashing.
"""

from __future__ import annotations

from ..cli import ToolResult, run_json

_MALOO = "maloo"


def sessions(trigger_job: str, *, days: int = 14, limit: int = 60,
             failed: bool = False) -> ToolResult:
    """Recent test sessions for a branch. .data is the list of session dicts:
    {session_id, submission, test_host, passed, failed, aborted, total,
     duration, trigger_job, url, enforcing, test_group, test_name}.
    """
    args = ["sessions", "--branch", trigger_job, "--days", str(days),
            "--limit", str(limit)]
    if failed:
        args.append("--failed")
    res = run_json(_MALOO, args, timeout=120)
    if not res.ok:
        return res
    data = res.data if isinstance(res.data, dict) else {}
    return ToolResult(ok=True, data=data.get("sessions", []))


def top_failures(trigger_job: str, *, days: int = 14, sessions: int = 50,
                 limit: int = 20) -> ToolResult:
    """Most common failing tests for a branch. .data is the top_failures list."""
    args = ["top-failures", trigger_job, "--days", str(days),
            "--sessions", str(sessions), "--limit", str(limit)]
    res = run_json(_MALOO, args, timeout=180)
    if not res.ok:
        return res
    data = res.data if isinstance(res.data, dict) else {}
    return ToolResult(ok=True, data=data.get("top_failures", []))
