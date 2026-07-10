"""GitHub access for EMF via the ``gh`` CLI.

EMF lives on GitHub (``whamcloud/exascaler-management-framework``), so we shell
out to ``gh`` (already authenticated in the user's keyring) exactly as the other
sources shell out to their CLIs. ``gh api`` emits JSON on stdout, so we reuse
``cli.run_json``. ``--jq`` slims each payload to one JSON value.

Three jobs, mirroring the Lustre reports:
- ``workflow_runs`` — CI run conclusions for the build-stability trend.
- ``releases`` + ``landed`` — CalVer releases and what merged since the newest one.
- ``open_prs`` — open PRs to corroborate "in review" for the forecast.
"""

from __future__ import annotations

import re
from collections import Counter

from ..cli import ToolResult, run_json
from ..util import parse_tickets, subsystem

_GH = "gh"
_PR_RE = re.compile(r"\(#(\d+)\)")
# Release plumbing commits, not real changes — skip like Lustre's "New tag".
_SKIP_RE = re.compile(r"^\s*(?:-\s*)?(?:Bump CalVer|Update changelog|New tag)\b", re.I)


def _api(path: str, jq: str, *, timeout: int = 90) -> ToolResult:
    return run_json(_GH, ["api", path, "--jq", jq], timeout=timeout)


def workflow_runs(repo: str, workflow: str, *, limit: int = 80) -> ToolResult:
    """Recent runs of one workflow: [{conclusion, status, created_at, head_branch, url}]."""
    jq = ('[.workflow_runs[] | {conclusion, status, created_at, '
          'head_branch, event, url: .html_url}]')
    return _api(f"repos/{repo}/actions/workflows/{workflow}/runs?per_page={limit}", jq)


def releases(repo: str, *, limit: int = 40) -> ToolResult:
    """Releases newest-first: [{tag, name, published_at, prerelease, draft}]."""
    jq = '[.[] | {tag: .tag_name, name, published_at, prerelease, draft}]'
    return _api(f"repos/{repo}/releases?per_page={limit}", jq)


def compare(repo: str, base: str, head: str) -> ToolResult:
    """`base...head` commits: {total, commits: [{sha, message, author, date, url}]}."""
    jq = ('{total: .total_commits, commits: [.commits[] | {sha: .sha[0:12], '
          'message: .commit.message, author: .commit.author.name, '
          'date: .commit.committer.date, url: .html_url}]}')
    return _api(f"repos/{repo}/compare/{base}...{head}", jq)


def open_prs(repo: str, *, limit: int = 100) -> ToolResult:
    """Open PRs: [{number, title, url, isDraft, headRefName, updatedAt}]."""
    return run_json(_GH, ["pr", "list", "-R", repo, "--state", "open",
                          "--limit", str(limit),
                          "--json", "number,title,url,isDraft,headRefName,updatedAt"])


def _parse_commit(c: dict, repo: str) -> dict | None:
    """One compare commit -> a patch record, or None to skip a plumbing commit."""
    subject = (c.get("message") or "").split("\n", 1)[0].strip()
    if not subject or _SKIP_RE.search(subject):
        return None
    m = _PR_RE.search(subject)
    number = int(m.group(1)) if m else None
    return {
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}" if number else c.get("url"),
        "subject": subject,
        "owner": c.get("author"),
        "date": (c.get("date") or "")[:10] or None,
        "tickets": parse_tickets(subject),
        "subsystem": subsystem(subject),
    }


def _areas(patches: list[dict]) -> list[list]:
    counts = Counter(p["subsystem"] for p in patches if p.get("subsystem"))
    return [[name, n] for name, n in counts.most_common()]


def landed(repo: str, branch: str, *, tag: str | None = None) -> dict:
    """What merged onto ``branch`` since the newest CalVer release (or ``tag``).

    Mirrors the Lustre "since last tag" changelog shape:
    {ok, repo, branch, tag, tag_date, manual, ahead, count, patches[], areas}.
    """
    rel = releases(repo)
    if not rel.ok:
        return {"ok": False, "error": rel.error, "kind": rel.kind}
    calvers = [r for r in rel.data if not r.get("draft")]
    if tag:
        base = tag
        base_date = next((r.get("published_at") for r in calvers if r.get("tag") == tag), None)
    elif calvers:
        base, base_date = calvers[0].get("tag"), calvers[0].get("published_at")
    else:
        return {"ok": False, "error": f"no releases found for {repo}", "kind": "error"}

    cmp = compare(repo, base, branch)
    if not cmp.ok:
        return {"ok": False, "error": cmp.error, "kind": cmp.kind, "tag": base}
    commits = (cmp.data or {}).get("commits") or []
    patches = [p for p in (_parse_commit(c, repo) for c in commits) if p]
    return {"ok": True, "repo": repo, "branch": branch, "tag": base,
            "tag_date": (base_date or "")[:10] or None, "manual": bool(tag),
            "ahead": (cmp.data or {}).get("total"), "count": len(patches),
            "patches": patches, "areas": _areas(patches)}
