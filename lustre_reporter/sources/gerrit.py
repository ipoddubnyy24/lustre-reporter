"""Gerrit access via the ``gerrit`` / ``gc`` CLI.

Powers the 'patches landed' and 'backport candidate' reports. Changes are
returned as compact, JSON-serializable dicts with parsed ticket refs attached.
"""

from __future__ import annotations

from ..cli import ToolResult, run_json
from ..util import days_ago_iso, parse_tickets

_GERRIT = "gerrit"


def _normalize(change: dict) -> dict:
    """Compact a raw `gc search` change into our record shape."""
    subject = change.get("subject", "")
    return {
        "number": change.get("number"),
        "subject": subject,
        "project": change.get("project"),
        "branch": change.get("branch"),
        "status": change.get("status"),
        "owner": change.get("owner"),
        "updated": change.get("updated"),
        "url": change.get("url"),
        "size": change.get("size"),
        "tickets": parse_tickets(subject),
    }


def search(query: str, *, limit: int = 100) -> ToolResult:
    """Run a raw Gerrit query; returns ToolResult whose .data is a list of
    normalized change dicts (on success)."""
    res = run_json(_GERRIT, ["search", query, "-n", str(limit)])
    if not res.ok:
        return res
    changes = res.data.get("changes", []) if isinstance(res.data, dict) else []
    return ToolResult(ok=True, data=[_normalize(c) for c in changes])


def merged_since(project: str, branch: str, since_iso: str, *, limit: int = 200) -> ToolResult:
    q = f"project:{project} branch:{branch} status:merged mergedafter:{since_iso}"
    return search(q, limit=limit)


def merged_last_days(project: str, branch: str, days: int, *, limit: int = 200) -> ToolResult:
    return merged_since(project, branch, days_ago_iso(days), limit=limit)


def open_changes(project: str, branch: str, *, limit: int = 200) -> ToolResult:
    q = f"project:{project} branch:{branch} status:open"
    return search(q, limit=limit)


def change_info(url: str) -> ToolResult:
    """Full `gc info` for one change (patchsets, reviewers, CI/Verified)."""
    return run_json(_GERRIT, ["info", url])


def verified_summary(info: dict) -> dict:
    """Reduce a `gc info` payload to a compact Verified/CI indicator.

    Returns {"verified": -1|0|1|None, "label": "V-1"|"V+1"|"V0"|None,
             "jenkins_build": <url-or-None>}.
    """
    votes: list[int] = []
    for r in info.get("reviewers", []) or []:
        approvals = r.get("approvals") or {}
        raw = approvals.get("Verified")
        if raw is None:
            continue
        try:
            votes.append(int(str(raw).strip()))
        except ValueError:
            continue
    verified: int | None
    if not votes:
        verified = None
    elif any(v < 0 for v in votes):
        verified = -1
    elif any(v > 0 for v in votes):
        verified = 1
    else:
        verified = 0
    label = None
    if verified is not None:
        label = f"V{'+' if verified > 0 else ('-' if verified < 0 else '')}{abs(verified) if verified else '0'}"
        if verified == 0:
            label = "V0"
    return {
        "verified": verified,
        "label": label,
        "jenkins_build": info.get("jenkins_build"),
        "current_patchset": info.get("current_patchset"),
    }
