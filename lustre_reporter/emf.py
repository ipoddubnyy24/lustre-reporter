"""Assemble the EMF reports from GitHub + Jira.

Shared by the ``/api/emf/*`` endpoints and the Confluence publisher so both
present identical data. Three collectors mirror the Lustre reports:
- ``collect_stability`` — nightly CI pass-rate trend (GitHub Actions).
- ``collect_landed``    — commits since the newest CalVer release.
- ``collect_coming``    — risk-weighted forecast per upcoming release, with each
  release tagged by its *release line* (main stream vs GCP vs …) so consumers
  can keep them clearly apart.
"""

from __future__ import annotations

import re

from . import util
from .analysis import emf_stability, forecast
from .sources import github, jira


def release_line(name: str, lines: list[dict]) -> dict | None:
    """Classify a fixVersion name into a configured release line (first match)."""
    for ln in lines:
        if re.search(ln.get("match", ""), name or "", re.I):
            return ln
    return None


def collect_stability(cfg, *, days: int | None = None, frm: str | None = None,
                      to: str | None = None) -> dict:
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
    if not res.ok:
        return {**base, "ok": False, "kind": res.kind, "error": res.error}
    runs = res.data
    if frm:  # defensively bound to the window (the server-side created filter also does)
        hi = to or "9999-99-99"
        runs = [r for r in runs if frm <= str(r.get("created_at") or "")[:10] <= hi]
    return {**base, "ok": True, **emf_stability.report(runs, days=days)}


def collect_landed(cfg, *, tag: str | None = None) -> dict:
    emf = cfg.emf or {}
    result = github.landed(emf.get("repo"), emf.get("release_branch"), tag=tag)
    for p in result.get("patches", []):
        for t in p.get("tickets", []):
            t["url"] = f"{cfg.jira_browse_base(t['project'])}/{t['key']}"
            t["is_cloud"] = cfg.is_cloud_project(t["project"])
    return result


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
    return {"ok": True, "project": proj, "repo": emf.get("repo"), "releases": releases}
