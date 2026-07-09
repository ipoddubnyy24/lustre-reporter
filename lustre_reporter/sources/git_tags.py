"""Resolve a branch's most-recent release tag via the local ex/lustre-release
clone.

Gerrit's REST API can't cheaply answer "the newest tag reachable from this
branch", so we use a local git checkout: fetch the branch + tags
(non-destructive — only updates remote-tracking refs), find the newest
reachable tag, and return its date. The caller then reuses the normal Gerrit
``mergedafter:`` search to list what landed since.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from ..util import parse_tickets

_REVIEW_RE = re.compile(r"Reviewed-on:\s*(https?://\S+/\+/(\d+))")
_TICKET_PREFIX_RE = re.compile(r"^\s*((?:LU|EX|DDN|EHT|GCP|IME|RM)-\d+\s+)+", re.I)
_NEW_TAG_RE = re.compile(r"build:\s*New tag", re.I)


def _git(clone: str, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", clone, *args],
                          capture_output=True, text=True, timeout=timeout)


def _read_env(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _gerrit_https_url(clone: str) -> str | None:
    """Authenticated Gerrit git-over-HTTPS URL, derived from the clone's origin
    host/project + the gerrit-cli HTTP credentials. Needs no SSH key, so it
    works from the daemon/.app where an SSH agent may be absent."""
    origin = _git(clone, ["remote", "get-url", "origin"]).stdout.strip()
    m = re.search(r"://([^/:]+)(?::\d+)?/(.+?)(?:\.git)?$", origin)
    if not m:
        return None
    host, project = m.group(1), m.group(2)
    env = _read_env(Path.home() / ".config" / "gerrit-cli" / ".env")
    user, pw = env.get("GERRIT_USER"), env.get("GERRIT_PASS")
    if not (user and pw):
        return None
    return f"https://{quote(user, safe='')}:{quote(pw, safe='')}@{host}/a/{project}"


def _ensure_fresh(clone: str, gerrit_branch: str, fetch_cfg: dict) -> dict:
    """Update the clone's refs from the best reachable source, in order:
    configured remotes (e.g. a GitHub mirror) → Gerrit HTTPS → origin (SSH) →
    give up and use the local copy. Returns {source, note}; ``note`` is a
    user-facing warning only when it fell back to a possibly-stale local copy.
    """
    refspec = f"+refs/heads/{gerrit_branch}:refs/remotes/origin/{gerrit_branch}"
    attempts: list[tuple[str, str]] = []
    for url in (fetch_cfg.get("remotes") or []):
        attempts.append(("remote", url.replace("{branch}", gerrit_branch)))
    if fetch_cfg.get("use_gerrit_https", True):
        https = _gerrit_https_url(clone)
        if https:
            attempts.append(("gerrit-https", https))
    if fetch_cfg.get("use_origin", True):
        attempts.append(("origin", "origin"))

    for source, target in attempts:
        try:
            # --force so a moved release tag can't abort the whole fetch
            res = _git(clone, ["fetch", "--quiet", "--force", "--tags", target, refspec], timeout=120)
        except subprocess.TimeoutExpired:
            continue
        if res.returncode == 0:
            return {"source": source, "note": None}
    return {"source": "local",
            "note": "⚠ could not reach any remote — showing the local clone copy, which may be stale"}


def last_tag(clone_dir: str, gerrit_branch: str, *, tag: str | None = None,
             fetch: bool = True, fetch_cfg: dict | None = None) -> dict:
    """Resolve a tag for ``origin/<gerrit_branch>`` and return
    {ok, tag, date (YYYY-MM-DD), datetime, manual, fetch_note}.

    With ``tag`` given, verify it exists and is reachable from the branch;
    otherwise pick the newest tag reachable from the branch. On failure returns
    {ok: False, error}.
    """
    clone = os.path.expanduser(clone_dir or "")
    if not clone or not (Path(clone) / ".git").exists():
        return {"ok": False, "error": f"Lustre clone not found at '{clone_dir}'. "
                "Set 'lustre_clone' in config.local.json to your ex/lustre-release checkout."}

    ref = f"origin/{gerrit_branch}"
    fetch_note = _ensure_fresh(clone, gerrit_branch, fetch_cfg or {})["note"] if fetch else None

    if _git(clone, ["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
        return {"ok": False, "error": f"'{ref}' not found in {clone} (fetch it first)"}

    if tag:
        peeled = f"refs/tags/{tag}^{{commit}}"
        if _git(clone, ["rev-parse", "--verify", "--quiet", peeled]).returncode != 0:
            return {"ok": False, "error": f"tag '{tag}' not found in the clone",
                    "fetch_note": fetch_note}
        if _git(clone, ["merge-base", "--is-ancestor", peeled, ref]).returncode != 0:
            return {"ok": False, "error": f"tag '{tag}' is not on {gerrit_branch}",
                    "fetch_note": fetch_note}
        chosen, manual = tag, True
    else:
        tags = _git(clone, ["tag", "--merged", ref, "--sort=-creatordate"])
        tag_list = [t for t in tags.stdout.splitlines() if t.strip()]
        if not tag_list:
            return {"ok": False, "error": f"no tags reachable from {ref}",
                    "fetch_note": fetch_note}
        chosen, manual = tag_list[0], False

    dt = _git(clone, ["log", "-1", "--format=%cI", chosen + "^{commit}"]).stdout.strip()
    return {"ok": True, "tag": chosen, "date": (dt[:10] if dt else None),
            "datetime": dt or None, "manual": manual, "fetch_note": fetch_note}


def _subsystem(subject: str) -> str:
    """The subsystem prefix of a Lustre commit subject, e.g. 'kernel', 'pcc'."""
    rest = _TICKET_PREFIX_RE.sub("", subject or "")
    m = re.match(r"\s*([A-Za-z0-9_.\-/]+)\s*:", rest)
    return m.group(1).lower() if m else "misc"


def _areas(patches: list[dict]) -> list[list]:
    """[[subsystem, count], ...] most-common first — the QA 'areas touched' line."""
    counts = Counter(p["subsystem"] for p in patches if p.get("subsystem"))
    return [[name, n] for name, n in counts.most_common()]


def _commits(clone: str, rng: str) -> list[dict]:
    """Parse `git log <rng>` into patch records, skipping 'New tag' bump commits."""
    fmt = "%H%x1f%s%x1f%an%x1f%cI%x1f%b%x1e"
    out = _git(clone, ["log", rng, "--format=" + fmt]).stdout
    records = []
    for chunk in out.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 5:
            continue
        _sha, subject, author, cdate, body = parts[0], parts[1], parts[2], parts[3], parts[4]
        if _NEW_TAG_RE.search(subject):
            continue
        m = _REVIEW_RE.search(body)
        records.append({
            "number": int(m.group(2)) if m else None,
            "url": m.group(1) if m else None,
            "subject": subject,
            "owner": author,
            "date": cdate[:10] if cdate else None,
            "tickets": parse_tickets(subject),
            "subsystem": _subsystem(subject),
        })
    return records


def build_changelog(clone_dir: str, gerrit_branch: str, *, max_builds: int = 5,
                    fetch: bool = True, fetch_cfg: dict | None = None) -> dict:
    """Per-build changelog for one branch: the patches each recent tag introduced
    (``prev_tag..tag``) plus what's merged but unreleased (``latest_tag..HEAD``).

    Returns {ok, branch, latest_tag, latest_date, unreleased[], unreleased_count,
             builds[{tag, prev, date, count, areas, patches[]}], fetch_note}.
    """
    clone = os.path.expanduser(clone_dir or "")
    if not clone or not (Path(clone) / ".git").exists():
        return {"ok": False, "error": f"Lustre clone not found at '{clone_dir}'. "
                "Set 'lustre_clone' in config.local.json."}

    ref = f"origin/{gerrit_branch}"
    fetch_note = _ensure_fresh(clone, gerrit_branch, fetch_cfg or {})["note"] if fetch else None

    if _git(clone, ["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
        return {"ok": False, "error": f"'{ref}' not found in {clone}", "fetch_note": fetch_note}

    tags = [t for t in _git(clone, ["tag", "--merged", ref, "--sort=-creatordate"]).stdout.splitlines()
            if t.strip()]
    if not tags:
        return {"ok": False, "error": f"no tags reachable from {ref}", "fetch_note": fetch_note}

    def _tag_date(t: str) -> str:
        return _git(clone, ["log", "-1", "--format=%cI", t + "^{commit}"]).stdout.strip()[:10]

    latest = tags[0]
    unreleased = _commits(clone, f"{latest}..{ref}")
    builds = []
    for i, tag in enumerate(tags[:max_builds]):
        prev = tags[i + 1] if i + 1 < len(tags) else None
        patches = _commits(clone, f"{prev}..{tag}" if prev else tag)
        builds.append({"tag": tag, "prev": prev, "date": _tag_date(tag),
                       "count": len(patches), "areas": _areas(patches), "patches": patches})

    return {"ok": True, "branch": gerrit_branch, "latest_tag": latest,
            "latest_date": _tag_date(latest), "unreleased": unreleased,
            "unreleased_count": len(unreleased), "unreleased_areas": _areas(unreleased),
            "builds": builds, "fetch_note": fetch_note}
