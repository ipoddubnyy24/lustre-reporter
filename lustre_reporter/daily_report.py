"""Daily build-health report for Slack: per-branch build stability (with a
trend) + what's landed since each branch's last tag.

Rendered in Slack ``mrkdwn`` for the app's own sender; a ``flavor="md"`` variant
(standard markdown) is used for previews via the interactive connector.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .analysis import stability
from .publish import now_pt  # PT-aware "now" (zoneinfo America/Los_Angeles)
from .sources import git_tags, maloo, slack

_TICKET_PREFIX_RE = re.compile(r"^\s*((?:LU|EX|DDN|EHT|GCP|IME|RM)-\d+\s+)+", re.I)


def next_run_pt(hour: int, now=None):
    """Next occurrence of HH:00 Pacific strictly after ``now``."""
    now = now or now_pt()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return target if now < target else target + timedelta(days=1)


def build_report(cfg, *, days: int | None = None) -> dict:
    days = days or (cfg.slack or {}).get("days", 14)
    branches = []
    for b in cfg.branches:
        sres = maloo.sessions(b.maloo_trigger_job, days=days, limit=500)
        if sres.ok:
            st = {"ok": True, "summary": stability.summarize(sres.data),
                  "trend": stability.trend(sres.data)}
        else:
            st = {"ok": False, "error": sres.error}

        cl = git_tags.build_changelog(cfg.lustre_clone, b.gerrit_branch,
                                      max_builds=1, fetch_cfg=cfg.git_fetch)
        if cl.get("ok"):
            landed = {"ok": True, "tag": cl["latest_tag"], "patches": cl["unreleased"],
                      "fetch_note": cl.get("fetch_note")}
        else:
            landed = {"ok": False, "error": cl.get("error")}

        branches.append({"key": b.key, "label": b.label, "gerrit_branch": b.gerrit_branch,
                         "stability": st, "landed": landed})
    return {"date": now_pt().strftime("%Y-%m-%d"), "days": days, "branches": branches}


def _trend_str(trend: list) -> str:
    vals = [b["session_pass_rate"] for b in trend[-7:] if b.get("session_pass_rate") is not None]
    if not vals:
        return "n/a"
    arrow = "→"
    if len(vals) >= 2:
        arrow = "↗" if vals[-1] > vals[0] else ("↘" if vals[-1] < vals[0] else "→")
    return " → ".join(f"{v:g}%" for v in vals) + f"  {arrow}"


def render(report: dict, cfg, *, flavor: str = "mrkdwn") -> str:
    if flavor == "mrkdwn":
        def bold(s):
            return f"*{s}*"

        def link(text, url):
            return f"<{url}|{text}>"
    else:
        def bold(s):
            return f"**{s}**"

        def link(text, url):
            return f"[{text}]({url})"

    lines = [f":bar_chart: {bold('Lustre daily report — ' + report['date'])}"]
    for b in report["branches"]:
        lines.append("")
        lines.append(bold(f"{b['label']} ({b['gerrit_branch']})"))

        st = b["stability"]
        if st.get("ok"):
            s = st["summary"]
            sp = "n/a" if s["session_pass_rate"] is None else f"{s['session_pass_rate']}%"
            tp = "n/a" if s["testset_pass_rate"] is None else f"{s['testset_pass_rate']}%"
            lines.append(f"  • Build stability ({report['days']}d): {sp} clean · {tp} test-sets · "
                         f"{s['sessions']} sessions, {s['failed_sessions']} with failures")
            lines.append(f"  • Trend (clean/day): {_trend_str(st['trend'])}")
        else:
            lines.append(f"  • Build stability: _unavailable_ ({(st.get('error') or '?')[:60]})")

        ld = b["landed"]
        if not ld.get("ok"):
            lines.append(f"  • Landed: _unavailable_ ({(ld.get('error') or '?')[:60]})")
        elif ld["patches"]:
            lines.append(f"  • Landed since {ld['tag']} ({len(ld['patches'])}):")
            for p in ld["patches"][:15]:
                tickets = ", ".join(link(t["key"], f"{cfg.jira_browse_base(t['project'])}/{t['key']}")
                                    for t in p.get("tickets", [])) or "—"
                patch = link(f"#{p['number']}", p["url"]) if p.get("url") and p.get("number") \
                    else (f"#{p['number']}" if p.get("number") else "")
                subject = _TICKET_PREFIX_RE.sub("", p.get("subject", ""))
                lines.append(f"        ◦ {tickets} {patch} {subject}")
            if len(ld["patches"]) > 15:
                lines.append(f"        …and {len(ld['patches']) - 15} more")
        else:
            lines.append(f"  • Landed since {ld['tag']}: _nothing yet_")
    return "\n".join(lines)


def send_daily(cfg) -> dict:
    """Build the report and post it to Slack. Returns {ok, error?, date}."""
    if not slack.configured(cfg.slack or {}):
        return {"ok": False, "error": "Slack is not enabled/configured (set slack.enabled + webhook_url or bot_token)."}
    report = build_report(cfg)
    res = slack.post(cfg.slack, render(report, cfg, flavor="mrkdwn"))
    return {"ok": bool(res.get("ok")), "error": res.get("error"), "date": report["date"]}
