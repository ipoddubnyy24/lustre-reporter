"""Small shared helpers: ticket parsing and date math."""

from __future__ import annotations

import re
from datetime import date, timedelta

# Lustre/ExaScaler commit subjects start with a ticket ref, e.g.
#   "LU-20388 pcc: fix ..."   "EX-14806 kernel: ..."   "DDN-1234 ..."
# Match the common trackers. Word-boundary + explicit prefixes keeps this from
# matching things like "UTF-8" or "SHA-1".
TICKET_RE = re.compile(r"\b(LU|EX|DDN|EHT|GCP|IME)-(\d+)\b")


def parse_tickets(text: str) -> list[dict]:
    """Extract unique ticket refs from a commit subject / message.

    Returns dicts: {"key": "LU-20388", "project": "LU", "number": "20388"}.
    Order-preserving and de-duplicated.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for proj, num in TICKET_RE.findall(text or ""):
        key = f"{proj}-{num}"
        if key not in seen:
            seen.add(key)
            out.append({"key": key, "project": proj, "number": num})
    return out


def ticket_keys(text: str) -> set[str]:
    return {t["key"] for t in parse_tickets(text)}


# Commit subjects lead with ticket refs, then the word before the first colon is
# the subsystem. Lustre uses "LU-1 kernel: ...", EMF uses "EX-1-desc" / "EX-1: ..."
# — so allow space, ':' or '-' as the separator after the ref.
# (NB: near-identical private copies still live in git_tags/publish/daily_report/
# backport — pre-existing duplication that could later collapse onto these.)
TICKET_PREFIX_RE = re.compile(r"^\s*((?:LU|EX|DDN|EHT|GCP|IME|RM)-\d+[\s:-]+)+", re.I)


def subsystem(subject: str) -> str:
    """The subsystem prefix of a Lustre/EMF commit subject, e.g. 'kernel', 'pcc'."""
    rest = TICKET_PREFIX_RE.sub("", subject or "")
    m = re.match(r"\s*([A-Za-z0-9_.\-/]+)\s*:", rest)
    return m.group(1).lower() if m else "misc"


def days_ago_iso(days: int, *, today: date | None = None) -> str:
    """ISO date (YYYY-MM-DD) `days` before today — for Gerrit `mergedafter:`."""
    base = today or date.today()
    return (base - timedelta(days=days)).isoformat()
