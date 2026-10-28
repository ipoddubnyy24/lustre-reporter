"""Assemble the EMF reports from GitHub + Jira.

Shared by the ``/api/emf/*`` endpoints and the Confluence publisher so both
present identical data. Three collectors mirror the Lustre reports:
- ``collect_stability`` — nightly CI pass-rate trend (GitHub Actions), plus
  ``collect_failure_reasons`` (failures that repeat) and ``analyze_run`` (one
  failed run as a Markdown document).
- ``collect_landed``    — commits since the newest CalVer release.
- ``collect_coming``    — risk-weighted forecast per upcoming release, with each
  release tagged by its *release line* (main stream vs GCP vs …) so consumers
  can keep them clearly apart.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import util
from .analysis import emf_failure, emf_stability, forecast
from .cli import ToolResult
from .sources import github, jira

# A finished run never changes, so its failed jobs and a complete analysis are
# kept for the life of the process.
_FAILED_JOBS: dict = {}
_ANALYSES: dict = {}
_REASON_SAMPLE = 40     # newest failed runs read for the common reasons (one jobs lookup each)
_MAX_LOGS = 6           # failed jobs whose logs one analysis downloads


def release_line(name: str, lines: list[dict]) -> dict | None:
    """Classify a fixVersion name into a configured release line (first match)."""
    for ln in lines:
        if re.search(ln.get("match", ""), name or "", re.I):
            return ln
    return None


def _window(cfg, days: int | None, frm: str | None, to: str | None) -> tuple[dict, ToolResult]:
    """(base fields, nightly runs) for a rolling ``days`` window or a from/to range."""
    emf = cfg.emf or {}
    days = emf.get("stability_days", 30) if days is None else days
    if frm:
        since, until = frm, (to or None)
    else:
        since, until = util.days_ago_iso(days), None
    res = github.workflow_runs(emf.get("repo"), emf.get("nightly_workflow"),
                               since=since, until=until)
    base = {"days": days, "from": frm, "to": to,
            "repo": emf.get("repo"), "workflow": emf.get("nightly_workflow")}
    if res.ok and frm:  # defensively bound to the window (the server-side created filter also does)
        hi = to or "9999-99-99"
        res = ToolResult(ok=True, data=[r for r in res.data
                                        if frm <= str(r.get("created_at") or "")[:10] <= hi])
    return base, res


def collect_stability(cfg, *, days: int | None = None, frm: str | None = None,
                      to: str | None = None) -> dict:
    base, res = _window(cfg, days, frm, to)
    if not res.ok:
        return {**base, "ok": False, "kind": res.kind, "error": res.error}
    return {**base, "ok": True, **emf_stability.report(res.data, days=base["days"])}


def _failed_jobs(repo: str, run_id: int) -> ToolResult:
    if run_id in _FAILED_JOBS:
        return ToolResult(ok=True, data=_FAILED_JOBS[run_id])
    res = github.failed_jobs(repo, run_id)
    if res.ok:
        _FAILED_JOBS[run_id] = res.data
    return res


def _failed_runs(repo: str, runs: list[dict]) -> tuple[list[dict], int, int]:
    """(newest failed runs with their failed jobs, failed runs in total, lookups that failed)."""
    failed = sorted((r for r in runs if r.get("conclusion") == "failure"),
                    key=lambda r: str(r.get("created_at") or ""), reverse=True)
    sample = failed[:_REASON_SAMPLE]
    with ThreadPoolExecutor(max_workers=16) as pool:
        found = list(pool.map(lambda r: _failed_jobs(repo, r.get("id")), sample))
    read = [{"id": r.get("id"), "date": r.get("created_at"), "url": r.get("url"), "jobs": j.data}
            for r, j in zip(sample, found) if j.ok]
    return read, len(failed), len(sample) - len(read)


def collect_failure_reasons(cfg, *, days: int | None = None, frm: str | None = None,
                            to: str | None = None) -> dict:
    """The failure signatures that repeat across the window's failed nightly runs."""
    base, res = _window(cfg, days, frm, to)
    if not res.ok:
        return {**base, "ok": False, "kind": res.kind, "error": res.error}
    read, failed, errors = _failed_runs(base["repo"], res.data)
    return {**base, "ok": True, "failed": failed, "read": len(read), "errors": errors,
            "reasons": emf_failure.common_reasons(read, min_count=2, top=5)}


def analyze_run(cfg, run_id: int, *, refresh: bool = False) -> dict:
    """Markdown analysis of one nightly run: where each failed job stopped and the
    log lines before it, how often the same failure hit the runs of the window
    leading up to it, and what changed since the last successful run."""
    if not refresh and run_id in _ANALYSES:
        return _ANALYSES[run_id]
    repo = (cfg.emf or {}).get("repo")
    rres = github.run(repo, run_id)
    if not rres.ok:
        return {"ok": False, "kind": rres.kind, "error": rres.error, "run_id": run_id}
    run = rres.data
    if refresh:
        _FAILED_JOBS.pop(run_id, None)
    jres = _failed_jobs(repo, run_id)
    if not jres.ok:
        return {"ok": False, "kind": jres.kind, "error": jres.error, "run_id": run_id}
    jobs = jres.data[:_MAX_LOGS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        logs = list(pool.map(lambda j: github.failed_log(repo, j["id"]), jobs))
    rows = []
    for j, lres in zip(jobs, logs):
        parsed = emf_failure.parse_log(lres.data) if lres.ok else None
        rows.append({**j, "signature": emf_failure.signature(j.get("name"), j.get("failed_steps") or []),
                     "parsed": parsed, "log_error": None if lres.ok else lres.error,
                     "category": emf_failure.classify(parsed) if parsed else None})

    day = str(run.get("created_at") or "")[:10]
    days = (cfg.emf or {}).get("stability_days", 30)
    frm = (date.fromisoformat(day) - timedelta(days=days - 1)).isoformat() if day else None
    base, wres = _window(cfg, days, frm, day or None)
    reasons, failed_total, last, changes = [], 0, None, None
    if wres.ok:
        read, failed_total, _ = _failed_runs(repo, wres.data)
        reasons = emf_failure.common_reasons(read)
        earlier = [r for r in wres.data if r.get("conclusion") == "success"
                   and str(r.get("created_at") or "") < str(run.get("created_at") or "")]
        last = max(earlier, key=lambda r: str(r.get("created_at") or ""), default=None)
        if last and last.get("head_sha") and run.get("head_sha") and last["head_sha"] != run["head_sha"]:
            cres = github.compare(repo, last["head_sha"], run["head_sha"])
            changes = cres.data if cres.ok else {"error": cres.error}
    doc = emf_failure.markdown({
        "repo": repo, "workflow": base["workflow"], "window_days": days, "run": run, "jobs": rows,
        "reasons": reasons, "failed_total": failed_total, "last_success": last, "changes": changes,
        "history_error": None if wres.ok else wres.error,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    complete = (wres.ok and all(r["log_error"] is None for r in rows)
                and not (changes or {}).get("error") and run.get("status") == "completed")
    result = {"ok": True, "run_id": run_id, "run_number": run.get("run_number"), "url": run.get("url"),
              "filename": f"emf-nightly-{run.get('run_number') or run_id}-analysis.md",
              "markdown": doc, "complete": complete}
    if complete:
        _ANALYSES[run_id] = result
    return result


def collect_landed(cfg, *, tag: str | None = None) -> dict:
    emf = cfg.emf or {}
    repo, branch = emf.get("repo"), emf.get("release_branch")
    if not branch:                          # unset: follow the repo's default branch
        res = github.default_branch(repo)
        if not res.ok:
            return {"ok": False, "error": res.error, "kind": res.kind}
        branch = res.data["name"]
    result = github.landed(repo, branch, tag=tag)
    patches = result.get("patches", [])
    for p in patches:
        for t in p.get("tickets", []):
            t["url"] = f"{cfg.jira_browse_base(t['project'])}/{t['key']}"
            t["is_cloud"] = cfg.is_cloud_project(t["project"])
    products = emf.get("products") or []
    if result.get("ok") and products:
        proj = emf.get("jira_project", "EX")
        fres = jira.fix_versions(sorted({t["key"] for p in patches for t in p.get("tickets", [])
                                         if t["project"] == proj}))
        fixes = fres.data if fres.ok else {}
        for p in patches:
            p["products"] = _products_for(p.get("tickets", []), products, fixes)
        result["products"] = [{"key": pr["key"], "label": pr.get("label"), "note": pr.get("note"),
                               "count": sum(pr["key"] in p["products"] for p in patches)}
                              for pr in products]
        result["unassigned"] = sum(not p["products"] for p in patches)
        if not fres.ok:
            result["products_error"] = fres.error
    return result


def _products_for(tickets: list[dict], products: list[dict], fixes: dict) -> list[str]:
    """Keys of the products a commit's tickets name, in config order: by Jira
    project, or by a fixVersion of the ticket matching the product's regex."""
    hit = set()
    for t in tickets:
        for pr in products:
            rx = pr.get("fix_versions")
            if t["project"] in (pr.get("projects") or []) or (
                    rx and any(re.match(rx, v or "") for v in fixes.get(t["key"], []))):
                hit.add(pr["key"])
    return [pr["key"] for pr in products if pr["key"] in hit]


def collect_coming(cfg) -> dict:
    emf = cfg.emf or {}
    proj = emf.get("jira_project", "EX")
    vres = jira.versions(proj)
    if not vres.ok:
        return {"ok": False, "kind": vres.kind, "error": vres.error, "project": proj}
    unreleased = [v for v in vres.data if not v.get("released")]
    tracked = emf.get("track_versions") or []
    if tracked:
        chosen = [v for v in unreleased if v.get("name") in tracked]
    else:  # auto: unreleased versions dated within the grace window
        grace = emf.get("coming_grace_days", 30)
        chosen = [v for v in unreleased if v.get("release_date")
                  and (forecast.days_until(v["release_date"]) or -99999) >= -grace]

    lines = emf.get("release_lines") or []

    def _rank(v):
        ln = release_line(v.get("name"), lines)
        return (lines.index(ln) if ln in lines else len(lines),
                v.get("release_date") or "9999-99-99")
    chosen.sort(key=_rank)
    # Unreleased versions left out (undated, or overdue past the grace window), so a
    # line with nothing to forecast can still say why on its page.
    picked = {v.get("name") for v in chosen}
    untracked = [{"name": v.get("name"), "release_date": v.get("release_date"),
                  "days": forecast.days_until(v.get("release_date")),
                  "line": (release_line(v.get("name"), lines) or {}).get("key", "other")}
                 for v in unreleased if v.get("name") not in picked]
    untracked.sort(key=lambda u: u["release_date"] or "9999-99-99", reverse=True)  # undated, then newest

    pr_map: dict = {}
    prs = github.open_prs(emf.get("repo"))
    if prs.ok:
        for p in prs.data:
            text = f"{p.get('title') or ''} {p.get('headRefName') or ''}"
            for t in util.parse_tickets(text):
                pr_map.setdefault(t["key"], []).append(
                    {"number": p.get("number"), "url": p.get("url"), "draft": p.get("isDraft")})

    bands, tiers = emf.get("risk_bands") or [], emf.get("status_tiers") or {}
    releases = []
    for v in chosen:
        ln = release_line(v.get("name"), lines) or {}
        jql = 'project = %s AND fixVersion = "%s" AND statusCategory != Done' % (proj, v["name"])
        ires = jira.search(jql, cloud=True, limit=200)
        items = ires.data if ires.ok else []
        for it in items:
            it["url"] = f"{cfg.jira_cloud_base}/{it['key']}"
            it["prs"] = pr_map.get(it["key"], [])
        fc = forecast.forecast(items, v.get("release_date"), bands=bands, tiers=tiers)
        releases.append({"name": v.get("name"), "overdue": v.get("overdue"),
                         "line": ln.get("key", "other"), "line_label": ln.get("label", "Other"),
                         "line_note": ln.get("note", ""),
                         "items_ok": ires.ok,
                         "items_error": None if ires.ok else ires.error, **fc})
    return {"ok": True, "project": proj, "repo": emf.get("repo"), "releases": releases,
            "untracked": untracked}
