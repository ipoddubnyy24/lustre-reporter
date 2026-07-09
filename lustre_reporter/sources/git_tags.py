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


def last_tag(clone_dir: str, gerrit_branch: str, *, tag: str | None = None,
             fetch: bool = True) -> dict:
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
