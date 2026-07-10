"""Build the per-branch 'landed patches' QA changelog and publish it to Confluence.

Layout per branch page (Confluence storage format):
  * info panel  — freshness + "how to read"
  * In build <latest tag> — TEST THIS   (prev_tag..latest_tag; always populated)
  * Coming next — since <latest tag>     (latest_tag..HEAD; may be empty)
  * Earlier builds                        (collapsed expand macros)
Each section has an "Areas touched" line (subsystem counts) to aid test planning.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - zoneinfo always present on 3.9+/macOS
    _PT = None

from .sources import git_tags
from .sources.confluence import Confluence, ConfluenceError

_TICKET_PREFIX_RE = re.compile(r"^\s*((?:LU|EX|DDN|EHT|GCP|IME|RM)-\d+\s+)+", re.I)


def now_pt() -> datetime:
    return datetime.now(_PT) if _PT else datetime.now()


def next_update_pt(now: datetime | None = None) -> datetime:
    """Next 00:00 or 12:00 Pacific strictly after ``now``."""
    now = now or now_pt()
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return noon if now < noon else (midnight + timedelta(days=1))


def _esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _strip_ticket(subject: str) -> str:
    return _TICKET_PREFIX_RE.sub("", subject or "")


def _ticket_cell(cfg, tickets) -> str:
    if not tickets:
        return "—"
    return " ".join(
        f'<a href="{_esc(cfg.jira_browse_base(t["project"]))}/{_esc(t["key"])}">{_esc(t["key"])}</a>'
        for t in tickets
    )


def _patch_cell(p) -> str:
    if p.get("url") and p.get("number"):
        return f'<a href="{_esc(p["url"])}">#{_esc(p["number"])}</a>'
    return f'#{_esc(p["number"])}' if p.get("number") else "—"


def _areas_line(areas) -> str:
    if not areas:
        return ""
    txt = " · ".join(f"{_esc(name)} ×{n}" for name, n in areas)
    return f"<p><strong>Areas touched:</strong> {txt}</p>"


def _table(cfg, patches) -> str:
    if not patches:
        return "<p><em>None.</em></p>"
    head = "<tr><th>Ticket</th><th>Patch</th><th>Subject</th><th>Owner</th><th>Merged</th></tr>"
    rows = "".join(
        "<tr>"
        f"<td>{_ticket_cell(cfg, p.get('tickets'))}</td>"
        f"<td>{_patch_cell(p)}</td>"
        f"<td>{_esc(_strip_ticket(p.get('subject')))}</td>"
        f"<td>{_esc(p.get('owner'))}</td>"
        f"<td>{_esc(p.get('date'))}</td>"
        "</tr>"
        for p in patches
    )
    return f"<table><tbody>{head}{rows}</tbody></table>"


def build_page_html(cfg, branch, cl: dict, *, now: datetime | None = None) -> str:
    now = now or now_pt()
    ts, nxt = now.strftime("%Y-%m-%d %H:%M"), next_update_pt(now).strftime("%Y-%m-%d %H:%M")
    parts = [
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        f"<p><strong>Updated {ts} PT</strong> · next update {nxt} PT · "
        f"branch <code>{_esc(branch.gerrit_branch)}</code> ({_esc(branch.gerrit_project)}).</p>"
        "<p><em>How to read:</em> <strong>In build &lt;tag&gt;</strong> = what that build added "
        "versus the previous build — this is what to test. <strong>Coming next</strong> = merged "
        "since the latest tag, not yet in a build.</p>"
        "</ac:rich-text-body></ac:structured-macro>"
    ]
    if cl.get("fetch_note"):
        parts.append(f"<p><em>Note: {_esc(cl['fetch_note'])}</em></p>")

    builds = cl.get("builds") or []
    if not builds:
        parts.append("<p>No tags found on this branch.</p>")
        return "".join(parts)

    latest = builds[0]
    parts.append(f"<h2>Latest build: {_esc(latest['tag'])} ({_esc(latest['date'])})</h2>")
    parts.append(f"<h3>In build {_esc(latest['tag'])} ({latest['count']})</h3>")
    parts.append(_areas_line(latest["areas"]))
    parts.append(_table(cfg, latest["patches"]))

    parts.append(f"<h3>Coming next — since {_esc(cl['latest_tag'])} ({cl['unreleased_count']})</h3>")
    parts.append(_areas_line(cl.get("unreleased_areas")))
    parts.append(_table(cfg, cl.get("unreleased")))

    if len(builds) > 1:
        parts.append("<h3>Earlier builds</h3>")
        for b in builds[1:]:
            inner = _areas_line(b["areas"]) + _table(cfg, b["patches"])
            parts.append(
                '<ac:structured-macro ac:name="expand">'
                f'<ac:parameter ac:name="title">{_esc(b["tag"])} ({b["count"]} patches) — {_esc(b["date"])}</ac:parameter>'
                f"<ac:rich-text-body>{inner}</ac:rich-text-body>"
                "</ac:structured-macro>"
            )
    return "".join(parts)


def _page_title(conf, branch) -> str:
    tmpl = conf.get("title_template", "ExaScaler Landed Patches — {label} ({gerrit_branch})")
    return tmpl.format(label=branch.label, gerrit_branch=branch.gerrit_branch, key=branch.key)


def targets(conf: dict) -> list:
    """Publish destinations as [{space_id, parent_id}].

    ``targets`` is authoritative; otherwise fall back to the legacy single
    ``space_id``/``parent_id``; otherwise empty (nothing configured).
    """
    ts = [t for t in (conf.get("targets") or []) if t.get("space_id")]
    if ts:
        return ts
    if conf.get("space_id"):
        return [{"space_id": conf["space_id"], "parent_id": conf.get("parent_id")}]
    return []


def publish_all(cfg) -> dict:
    """Build each branch page once and upsert it to every configured target."""
    conf = getattr(cfg, "confluence", None) or {}
    if not conf.get("enabled"):
        return {"ok": False, "error": "Confluence publishing is disabled (set confluence.enabled)."}
    dests = targets(conf)
    if not dests:
        return {"ok": False, "error": "confluence has no targets (set confluence.targets or space_id)."}
    try:
        client = Confluence(conf.get("site"))
    except ConfluenceError as exc:
        return {"ok": False, "error": str(exc)}

    now = now_pt()
    results = []
    for b in cfg.branches:
        cl = git_tags.build_changelog(cfg.lustre_clone, b.gerrit_branch,
                                      max_builds=conf.get("max_builds", 5),
                                      fetch_cfg=cfg.git_fetch)
        if not cl.get("ok"):
            results.append({"branch": b.key, "label": b.label, "ok": False, "error": cl.get("error")})
            continue
        title = _page_title(conf, b)
        html = build_page_html(cfg, b, cl, now=now)
        for t in dests:
            entry = {"branch": b.key, "label": b.label, "space": t["space_id"], "title": title}
            try:
                up = client.upsert(t["space_id"], t.get("parent_id"), title, html)
                entry.update({"ok": True, "latest_tag": cl["latest_tag"], **up})
            except ConfluenceError as exc:
                entry.update({"ok": False, "error": str(exc)})
            results.append(entry)

    return {"ok": all(r.get("ok") for r in results),
            "published_at": now.strftime("%Y-%m-%d %H:%M %Z") or now.strftime("%Y-%m-%d %H:%M"),
            "results": results}
