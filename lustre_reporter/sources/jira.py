"""Jira access via the ``jira`` CLI.

LU tickets resolve on the Whamcloud Jira (default instance); EX/DDN/etc. on
the DDN cloud instance (``-I cloud``). The caller decides which via the
``cloud`` flag (computed from the project prefix in config).
"""

from __future__ import annotations

from ..cli import ToolResult, run_json
from . import atlassian

_JIRA = "jira"
_FIELDS = "key,summary,status,priority,assignee,reporter,labels,fixVersions,issuetype,resolution,updated,created"


def _flatten(value: object, *keys: str) -> str | None:
    """Pull a display string out of a Jira field that may be a str or object."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in keys:
            if value.get(k):
                return str(value[k])
    return str(value)


def normalize(raw: dict) -> dict:
    fix_versions = raw.get("fixVersions") or raw.get("fix_versions") or []
    if isinstance(fix_versions, list):
        fix_versions = [_flatten(v, "name") for v in fix_versions if v]
    labels = raw.get("labels") or []
    return {
        "key": raw.get("key"),
        "summary": raw.get("summary"),
        "status": _flatten(raw.get("status"), "name"),
        "priority": _flatten(raw.get("priority"), "name"),
        "assignee": _flatten(raw.get("assignee"), "displayName", "name", "emailAddress"),
        "reporter": _flatten(raw.get("reporter"), "displayName", "name", "emailAddress"),
        "issue_type": _flatten(raw.get("issue_type") or raw.get("issuetype"), "name"),
        "resolution": _flatten(raw.get("resolution"), "name"),
        "labels": labels if isinstance(labels, list) else [],
        "fix_versions": fix_versions,
        "updated": raw.get("updated"),
    }


def get(key: str, *, cloud: bool = False) -> ToolResult:
    args = ["get", key, "--fields", _FIELDS]
    if cloud:
        args += ["-I", "cloud"]
    res = run_json(_JIRA, args)
    if not res.ok:
        return res
    if not isinstance(res.data, dict):
        return ToolResult(ok=False, data=None, error="unexpected jira payload", kind="error")
    return ToolResult(ok=True, data=normalize(res.data))


def search(jql: str, *, cloud: bool = False, limit: int = 50) -> ToolResult:
    args = ["search", jql, "--limit", str(limit), "--fields", _FIELDS]
    if cloud:
        args += ["-I", "cloud"]
    res = run_json(_JIRA, args)
    if not res.ok:
        return res
    # The tool may return a bare list or {issues: [...]}.
    issues = res.data
    if isinstance(issues, dict):
        issues = issues.get("issues") or issues.get("results") or []
    if not isinstance(issues, list):
        issues = []
    return ToolResult(ok=True, data=[normalize(i) for i in issues])


def versions(project: str) -> ToolResult:
    """Project fixVersions with release dates (Jira Cloud REST).

    Returns [{name, release_date (YYYY-MM-DD|None), released, overdue}].
    """
    try:
        data = atlassian.cloud_get(f"/rest/api/3/project/{project}/versions")
    except atlassian.AtlassianError as exc:
        return ToolResult(ok=False, data=None, error=str(exc), kind="error")
    if not isinstance(data, list):
        return ToolResult(ok=False, data=None, error="unexpected versions payload", kind="error")
    out = [{
        "name": v.get("name"),
        "release_date": v.get("releaseDate"),
        "released": bool(v.get("released")),
        "overdue": bool(v.get("overdue")),
    } for v in data if isinstance(v, dict)]
    return ToolResult(ok=True, data=out)
