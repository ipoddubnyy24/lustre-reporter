import subprocess

import pytest

from lustre_reporter.sources import git_tags


def cp(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess(args=["git"], returncode=rc, stdout=stdout, stderr=stderr)


def _rec(sha, subject, author, cdate, body):
    return "\x1f".join([sha, subject, author, cdate, body])


def _log_output(recs):
    return "\x1e".join(recs) + "\x1e"


ES6 = r"2\.14\.0-ddn\d+"
ES7 = r"2\.16\.0-ddn\d+"


# ---------------- pure helpers ----------------
def test_subsystem():
    assert git_tags._subsystem("LU-1 kernel: x") == "kernel"
    assert git_tags._subsystem("RM-2 build: New tag") == "build"
    assert git_tags._subsystem("no colon here") == "misc"


def test_areas_ordered():
    pts = [{"subsystem": "kernel"}, {"subsystem": "kernel"}, {"subsystem": "pcc"}]
    assert git_tags._areas(pts) == [["kernel", 2], ["pcc", 1]]


def test_commits_parsing(monkeypatch):
    recs = [
        _rec("sha1", "LU-1 kernel: x", "Alice", "2026-07-09T10:00:00Z",
             "Change-Id: I1\nReviewed-on: https://g/c/ex/lustre-release/+/100\n"),
        _rec("sha2", "RM-620 build: New tag 2.16.0-ddn54", "Bob", "2026-07-09T09:00:00Z", "b"),
        _rec("sha3", "EX-2 pcc: y", "Carol", "2026-07-08T10:00:00Z", "no footer"),
        "no-delimiters-here",   # malformed (<5 fields) -> skipped
    ]
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(stdout=_log_output(recs)) if a[0] == "log" else cp())
    out = git_tags._commits("/c", "A..B")
    assert len(out) == 2  # "New tag" bump skipped
    assert out[0]["number"] == 100 and out[0]["url"].endswith("/100")
    assert out[0]["subsystem"] == "kernel" and out[0]["tickets"][0]["key"] == "LU-1"
    assert out[1]["number"] is None and out[1]["date"] == "2026-07-08"


def test_read_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# comment\nGERRIT_USER=me\nGERRIT_PASS="secret"\nBAD LINE\nX=\n')
    env = git_tags._read_env(p)
    assert env == {"GERRIT_USER": "me", "GERRIT_PASS": "secret", "X": ""}


def test_read_env_missing(tmp_path):
    assert git_tags._read_env(tmp_path / "nope") == {}


def test_gerrit_https_url(monkeypatch):
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(stdout="ssh://review.whamcloud.com:29418/ex/lustre-release\n")
                        if a[:2] == ["remote", "get-url"] else cp())
    monkeypatch.setattr(git_tags, "_read_env", lambda p: {"GERRIT_USER": "u", "GERRIT_PASS": "p+s"})
    assert git_tags._gerrit_https_url("/c") == "https://u:p%2Bs@review.whamcloud.com/a/ex/lustre-release"


def test_gerrit_https_url_no_creds(monkeypatch):
    monkeypatch.setattr(git_tags, "_git", lambda c, a, **k: cp(stdout="ssh://h:1/proj\n"))
    monkeypatch.setattr(git_tags, "_read_env", lambda p: {})
    assert git_tags._gerrit_https_url("/c") is None


def test_gerrit_https_url_bad_origin(monkeypatch):
    monkeypatch.setattr(git_tags, "_git", lambda c, a, **k: cp(stdout="not-a-url\n"))
    assert git_tags._gerrit_https_url("/c") is None


# ---------------- _ensure_fresh (fallback chain) ----------------
def test_ensure_fresh_configured_remote_first(monkeypatch):
    monkeypatch.setattr(git_tags, "_git", lambda c, a, **k: cp(rc=0) if a[0] == "fetch" else cp())
    r = git_tags._ensure_fresh("/c", "b", {"remotes": ["gh://{branch}"],
                                           "use_gerrit_https": False, "use_origin": False})
    assert r["source"] == "remote" and r["note"] is None


def test_ensure_fresh_gerrit_https(monkeypatch):
    monkeypatch.setattr(git_tags, "_gerrit_https_url", lambda c: "https://u:p@h/a/proj")

    def resp(c, a, **k):
        if a[0] == "fetch":
            return cp(rc=0) if "@" in a[4] else cp(rc=1)
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    r = git_tags._ensure_fresh("/c", "b", {})
    assert r["source"] == "gerrit-https" and r["note"] is None


def test_ensure_fresh_origin(monkeypatch):
    monkeypatch.setattr(git_tags, "_gerrit_https_url", lambda c: None)
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: (cp(rc=0) if a[4] == "origin" else cp(rc=1))
                        if a[0] == "fetch" else cp())
    r = git_tags._ensure_fresh("/c", "b", {})
    assert r["source"] == "origin"


def test_ensure_fresh_all_fail(monkeypatch):
    monkeypatch.setattr(git_tags, "_gerrit_https_url", lambda c: "https://x@h/p")
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(rc=1) if a[0] == "fetch" else cp())
    r = git_tags._ensure_fresh("/c", "b", {})
    assert r["source"] == "local" and "stale" in r["note"]


def test_ensure_fresh_timeout(monkeypatch):
    monkeypatch.setattr(git_tags, "_gerrit_https_url", lambda c: "https://x@h/p")

    def resp(c, a, **k):
        if a[0] == "fetch":
            raise subprocess.TimeoutExpired("git", 1)
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    assert git_tags._ensure_fresh("/c", "b", {})["source"] == "local"


# ---------------- last_tag ----------------
def test_last_tag_clone_missing():
    r = git_tags.last_tag("/nonexistent/xyz", "b", tag_pattern=ES7)
    assert r["ok"] is False and "not found" in r["error"]


def _fresh(monkeypatch):
    monkeypatch.setattr(git_tags, "_ensure_fresh", lambda c, b, fc: {"source": "x", "note": None})


def test_last_tag_latest(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="2.16.0-ddn54\n2.16.0-ddn53\n")
        if a[0] == "log":
            return cp(stdout="2026-07-08T00:00:00Z\n")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    r = git_tags.last_tag(str(tmp_path), "b_es7_0", tag_pattern=ES7, fetch_cfg={})
    assert r["ok"] and r["tag"] == "2.16.0-ddn54" and r["date"] == "2026-07-08" and r["manual"] is False


def test_last_tag_ref_missing(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(rc=1) if a[0] == "rev-parse" else cp())
    r = git_tags.last_tag(str(tmp_path), "b", tag_pattern=ES7, fetch_cfg={})
    assert r["ok"] is False and "not found" in r["error"]


def test_last_tag_no_tags(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="\n")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    assert git_tags.last_tag(str(tmp_path), "b", tag_pattern=ES7, fetch_cfg={})["ok"] is False


def test_last_tag_specific_ok(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "merge-base":
            return cp(rc=0)
        if a[0] == "log":
            return cp(stdout="2026-07-01T00:00:00Z\n")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    r = git_tags.last_tag(str(tmp_path), "b", tag="2.16.0-ddn52", tag_pattern=ES7, fetch_cfg={})
    assert r["ok"] and r["tag"] == "2.16.0-ddn52" and r["manual"] is True


def test_last_tag_specific_not_found(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: (cp(rc=0) if a[-1].startswith("origin/") else cp(rc=1))
                        if a[0] == "rev-parse" else cp())
    r = git_tags.last_tag(str(tmp_path), "b", tag="nope", tag_pattern=ES7, fetch_cfg={})
    assert r["ok"] is False and "not found" in r["error"]


def test_last_tag_specific_not_ancestor(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(rc=1) if a[0] == "merge-base"
                        else (cp(rc=0) if a[0] == "rev-parse" else cp()))
    r = git_tags.last_tag(str(tmp_path), "b", tag="X", tag_pattern=ES7, fetch_cfg={})
    assert r["ok"] is False and "not on" in r["error"]


def test_last_tag_fetch_false(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_tags, "_ensure_fresh",
                        lambda *a: pytest.fail("must not fetch when fetch=False"))

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="T1\n")
        if a[0] == "log":
            return cp(stdout="2026-01-01T00:00:00Z\n")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    r = git_tags.last_tag(str(tmp_path), "b", tag_pattern=r"T\d+", fetch=False, fetch_cfg={})
    assert r["ok"] and r["fetch_note"] is None


def test_last_tag_skips_foreign_tags(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="lipe-2.101\nEXA6.3.10\n2.14.0-ddn263\nlipe-2.100\n")
        if a[0] == "log":
            assert a[-1] == "2.14.0-ddn263^{commit}"
            return cp(stdout="2026-10-02T09:01:47+08:00\n")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    r = git_tags.last_tag(str(tmp_path), "b_es6_0", tag_pattern=ES6, fetch_cfg={})
    assert r["ok"] and r["tag"] == "2.14.0-ddn263" and r["manual"] is False


# ---------------- build_changelog ----------------
def test_build_changelog(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_tags, "_ensure_fresh",
                        lambda c, b, fc: {"source": "gerrit-https", "note": None})

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="T3\nT2\nT1\n")
        if a[0] == "log" and a[1] == "-1":
            return cp(stdout="2026-07-09T00:00:00Z\n")
        if a[0] == "log":
            rng = a[1]
            n = 2 if rng == "T2..T3" else 1
            recs = [_rec(f"s{i}", f"LU-{i} kernel: x", "Al", "2026-07-05T00:00:00Z",
                         f"Reviewed-on: https://g/c/ex/lustre-release/+/{100 + i}") for i in range(n)]
            return cp(stdout=_log_output(recs))
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    cl = git_tags.build_changelog(str(tmp_path), "b", tag_pattern=r"T\d+", max_builds=2, fetch_cfg={})
    assert cl["ok"] and cl["latest_tag"] == "T3" and cl["latest_date"] == "2026-07-09"
    assert len(cl["builds"]) == 2
    assert cl["builds"][0]["tag"] == "T3" and cl["builds"][0]["prev"] == "T2" and cl["builds"][0]["count"] == 2
    assert cl["builds"][1]["tag"] == "T2" and cl["builds"][1]["prev"] == "T1"
    assert cl["unreleased_count"] == 1 and "unreleased_areas" in cl
    assert cl["fetch_note"] is None


def test_build_changelog_clone_missing():
    assert git_tags.build_changelog("/no/where", "b", tag_pattern=ES6)["ok"] is False


def test_build_changelog_ref_missing(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_tags, "_ensure_fresh", lambda *a: {"note": "⚠ stale"})
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(rc=1) if a[0] == "rev-parse" else cp())
    r = git_tags.build_changelog(str(tmp_path), "b", tag_pattern=ES6, fetch_cfg={})
    assert r["ok"] is False and r["fetch_note"] == "⚠ stale"


def test_build_changelog_no_tags(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_tags, "_ensure_fresh", lambda *a: {"note": None})

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="")
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    assert git_tags.build_changelog(str(tmp_path), "b", tag_pattern=ES6, fetch_cfg={})["ok"] is False


def test_build_changelog_skips_adjacent_foreign_tags(monkeypatch, tmp_path):
    # b_es6_0 as of 2 Oct 2026: lipe-2.100 was cut 43s before 2.14.0-ddn263 on
    # its parent commit and EXA6.3.9 shares ddn262's commit. Neither may become
    # a build boundary, nor may the mistyped 2.14.0-2.14.0-ddn116.
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)
    sizes = {"2.14.0-ddn262..2.14.0-ddn263": 29, "2.14.0-ddn261..2.14.0-ddn262": 4,
             "2.14.0-ddn261": 7, "2.14.0-ddn263..origin/b_es6_0": 3}

    def resp(c, a, **k):
        if a[0] == "rev-parse":
            return cp(rc=0)
        if a[0] == "tag":
            return cp(stdout="2.14.0-ddn263\nlipe-2.100\nEXA6.3.9\n2.14.0-ddn262\n"
                             "lipe-2.99\n2.14.0-ddn261\n2.14.0-2.14.0-ddn116\n")
        if a[0] == "log" and a[1] == "-1":
            return cp(stdout="2026-10-02T09:01:47+08:00\n")
        if a[0] == "log":
            recs = [_rec(f"s{i}", f"EX-{i} osd: x", "Al", "2026-10-01T00:00:00Z", "")
                    for i in range(sizes[a[1]])]
            return cp(stdout=_log_output(recs))
        return cp()
    monkeypatch.setattr(git_tags, "_git", resp)
    cl = git_tags.build_changelog(str(tmp_path), "b_es6_0", tag_pattern=ES6, fetch_cfg={})
    assert cl["ok"] and cl["latest_tag"] == "2.14.0-ddn263"
    assert [(b["tag"], b["prev"], b["count"]) for b in cl["builds"]] == [
        ("2.14.0-ddn263", "2.14.0-ddn262", 29),
        ("2.14.0-ddn262", "2.14.0-ddn261", 4),
        ("2.14.0-ddn261", None, 7),
    ]
    assert cl["unreleased_count"] == 3


def test_build_changelog_only_foreign_tags(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    _fresh(monkeypatch)
    monkeypatch.setattr(git_tags, "_git",
                        lambda c, a, **k: cp(stdout="lipe-2.100\nEXA6.3.9\n") if a[0] == "tag" else cp())
    r = git_tags.build_changelog(str(tmp_path), "b_es6_0", tag_pattern=ES6, fetch_cfg={})
    assert r["ok"] is False and "no tags matching" in r["error"]


def test_git_runs_real(tmp_path):
    import subprocess as sp
    sp.run(["git", "init", "-q", str(tmp_path)], check=True)
    r = git_tags._git(str(tmp_path), ["rev-parse", "--is-inside-work-tree"])
    assert r.returncode == 0 and "true" in r.stdout
