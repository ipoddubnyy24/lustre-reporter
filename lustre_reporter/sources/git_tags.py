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
import subprocess
from pathlib import Path


def _git(clone: str, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", clone, *args],
                          capture_output=True, text=True, timeout=timeout)


def last_tag(clone_dir: str, gerrit_branch: str, *, fetch: bool = True) -> dict:
    """Return {ok, tag, date (YYYY-MM-DD), datetime, fetch_note} for the newest
    tag reachable from ``origin/<gerrit_branch>``; {ok: False, error} otherwise."""
    clone = os.path.expanduser(clone_dir or "")
    if not clone or not (Path(clone) / ".git").exists():
        return {"ok": False, "error": f"Lustre clone not found at '{clone_dir}'. "
                "Set 'lustre_clone' in config.local.json to your ex/lustre-release checkout."}

    ref = f"origin/{gerrit_branch}"
    fetch_note = None
    if fetch:
        try:
            fr = _git(clone, ["fetch", "--quiet", "--tags", "origin", gerrit_branch])
            if fr.returncode != 0:
                tail = (fr.stderr or "").strip().splitlines()
                fetch_note = tail[-1] if tail else "git fetch failed; using local clone state"
        except subprocess.TimeoutExpired:
            fetch_note = "git fetch timed out; using local clone state"

    if _git(clone, ["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
        return {"ok": False, "error": f"'{ref}' not found in {clone} (fetch it first)"}

    tags = _git(clone, ["tag", "--merged", ref, "--sort=-creatordate"])
    tag_list = [t for t in tags.stdout.splitlines() if t.strip()]
    if not tag_list:
        return {"ok": False, "error": f"no tags reachable from {ref}"}

    tag = tag_list[0]
    dt = _git(clone, ["log", "-1", "--format=%cI", tag + "^{commit}"]).stdout.strip()
    return {"ok": True, "tag": tag, "date": (dt[:10] if dt else None),
            "datetime": dt or None, "fetch_note": fetch_note}
