"""Backport-candidate detection.

For each patch merged to a 'master' (community ``fs/lustre-release`` and/or
ExaScaler ``ex/lustre-release``), determine its status on each ExaScaler
release branch (es6 / es7):

  * ``ported``      — the branch has a change with the same ticket AND a
                      matching subject (a real backport of this patch).
  * ``ticket_only`` — the ticket exists on the branch, but *this* patch's
                      subject is not among them. Strong signal that a companion
                      patch was missed while porting the ticket.
  * ``missing``     — the ticket is absent from the branch entirely.

A patch is a *candidate* when it is ``missing`` or ``ticket_only`` on at least
one branch. Candidates are ranked with missed-companions first, then missing,
then most-recent. Live Jira/CI enrichment is done lazily per row by the server,
so this pass stays fast (a handful of Gerrit queries).
"""

from __future__ import annotations

import re

from ..sources import gerrit

_TICKET_PREFIX_RE = re.compile(r"^\s*((?:LU|EX|DDN|EHT|GCP|IME)-\d+\s+)+", re.I)
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_subject(subject: str) -> str:
    """Lowercased subject with leading ticket refs and punctuation stripped."""
    s = _TICKET_PREFIX_RE.sub("", subject or "")
    s = _NONWORD_RE.sub(" ", s.lower())
    return s.strip()


def _tokens(norm: str) -> set:
    return {t for t in norm.split() if len(t) > 2}


def _subject_match(a_norm: str, a_tok: set, b_norm: str, b_tok: set) -> bool:
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm or a_norm in b_norm or b_norm in a_norm:
        return True
    if a_tok and b_tok:
        jaccard = len(a_tok & b_tok) / len(a_tok | b_tok)
        return jaccard >= 0.7
    return False


def _prep(change: dict) -> dict:
    change["_norm"] = normalize_subject(change.get("subject", ""))
    change["_tok"] = _tokens(change["_norm"])
    return change


def _slim(c: dict) -> dict:
    return {
        "number": c.get("number"),
        "url": c.get("url"),
        "status": c.get("status"),
        "subject": c.get("subject"),
        "owner": c.get("owner"),
    }


def build_branch_index(project: str, branch: str, scan_days: int) -> dict:
    """Index a branch's merged+open changes by ticket key."""
    errors: list[str] = []
    changes: list[dict] = []
    for res in (
        gerrit.merged_last_days(project, branch, scan_days, limit=800),
        gerrit.open_changes(project, branch, limit=400),
    ):
        if res.ok:
            changes.extend(res.data)
        elif res.error:
            errors.append(res.error)

    by_ticket: dict[str, list[dict]] = {}
    for c in changes:
        _prep(c)
        for t in c.get("tickets", []):
            by_ticket.setdefault(t["key"], []).append(c)
    return {"by_ticket": by_ticket, "count": len(changes), "errors": errors}


def gather_master(masters, scan_days: int, per_repo_limit: int = 800) -> dict:
    changes: list[dict] = []
    errors: list[str] = []
    seen: set = set()
    for m in masters:
        res = gerrit.merged_last_days(m.gerrit_project, m.gerrit_branch,
                                      scan_days, limit=per_repo_limit)
        if not res.ok:
            errors.append(f"{m.gerrit_project} {m.gerrit_branch}: {res.error}")
            continue
        for c in res.data:
            num = c.get("number")
            if num in seen:
                continue
            seen.add(num)
            _prep(c)
            c["master_repo"] = m.key
            changes.append(c)
    return {"changes": changes, "errors": errors}


def status_in_branch(mc: dict, index: dict) -> dict:
    keys = [t["key"] for t in mc.get("tickets", [])]
    related: list[dict] = []
    for k in keys:
        related.extend(index["by_ticket"].get(k, []))
    for bc in related:
        if _subject_match(mc["_norm"], mc["_tok"], bc["_norm"], bc["_tok"]):
            return {"state": "ported", "change": _slim(bc)}
    if related:
        # De-dup related by change number for display.
        uniq = {c["number"]: c for c in related}
        return {"state": "ticket_only",
                "related": [_slim(c) for c in list(uniq.values())[:6]]}
    return {"state": "missing"}


def _score(row: dict, branch_keys: list[str]) -> int:
    score = 0
    for bk in branch_keys:
        state = row["branches"][bk]["state"]
        if state == "ticket_only":
            score += 3
        elif state == "missing":
            score += 1
    return score


def analyze(cfg, scan_days: int, *, only_gaps: bool = True,
            max_rows: int = 400) -> dict:
    branch_keys = [b.key for b in cfg.branches]
    indexes = {
        b.key: build_branch_index(b.gerrit_project, b.gerrit_branch, scan_days)
        for b in cfg.branches
    }
    master = gather_master(cfg.masters, scan_days)

    rows: list[dict] = []
    counts = {bk: {"missing": 0, "ticket_only": 0, "ported": 0} for bk in branch_keys}
    for mc in master["changes"]:
        per = {b.key: status_in_branch(mc, indexes[b.key]) for b in cfg.branches}
        for bk in branch_keys:
            counts[bk][per[bk]["state"]] += 1
        is_gap = any(per[bk]["state"] != "ported" for bk in branch_keys)
        if only_gaps and not is_gap:
            continue
        rows.append({
            "number": mc.get("number"),
            "subject": mc.get("subject"),
            "url": mc.get("url"),
            "owner": mc.get("owner"),
            "updated": mc.get("updated"),
            "tickets": mc.get("tickets", []),
            "master_repo": mc.get("master_repo"),
            "branches": per,
        })

    rows.sort(key=lambda r: (_score(r, branch_keys), str(r["updated"] or "")),
              reverse=True)
    truncated = len(rows) > max_rows

    errors = list(master["errors"])
    for idx in indexes.values():
        errors.extend(idx["errors"])

    return {
        "scan_days": scan_days,
        "branches": [
            {"key": b.key, "label": b.label, "gerrit_branch": b.gerrit_branch,
             "ping_name": b.ping_name, "indexed_changes": indexes[b.key]["count"]}
            for b in cfg.branches
        ],
        "masters": [{"key": m.key, "label": m.label,
                     "project": m.gerrit_project, "branch": m.gerrit_branch}
                    for m in cfg.masters],
        "master_changes_scanned": len(master["changes"]),
        "counts": counts,
        "candidate_count": len(rows),
        "truncated": truncated,
        "candidates": rows[:max_rows],
        "errors": errors,
    }
