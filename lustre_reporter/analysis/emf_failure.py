"""Read failed EMF nightly runs: where they failed, the error, and the pattern.

Pure functions over GitHub data, so the collectors stay thin and testable:
- ``signature``: a failure's job (matrix values dropped) and first failed step,
  the key used to spot the same failure across runs
- ``parse_log``: the failing action, the error line and the lines before it,
  from ``gh run view --log-failed`` output
- ``classify``: a keyword guess at the kind of failure (labelled as a guess)
- ``common_reasons``: signatures ranked by how many failed runs hit them
- ``markdown``: the analysis document for one run
"""

from __future__ import annotations

import re
from collections import Counter

_MATRIX = re.compile(r"\s*\([^)]*\)")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TS = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_START = re.compile(r"##\[start-action display=(.*?);id=([^\]]+)\]")
_END = re.compile(r"##\[end-action id=([^;\]]+);outcome=(\w+)")
_ERROR = re.compile(r"##\[error\](.*)")
_EXIT = re.compile(r"exit code (\d+)")
_DIGITS = re.compile(r"\d+")
_ERRORISH = re.compile(r"error|fail|fatal|timed? ?out|timeout|cannot|no such file|not found|denied|"
                       r"refused|panicked|traceback|exception", re.I)
_LOOKBACK, _EXCERPT, _KEY_LINES, _MAX_COMMITS, _MAX_OTHERS = 400, 12, 5, 25, 8

# The first category whose pattern matches the line closest to the error wins.
_CATEGORIES = [
    ("Timeout", re.compile(r"exceeds timeout|timed? ?out\b|timeout", re.I)),
    ("Disk full", re.compile(r"no space left on device", re.I)),
    ("Missing file or command", re.compile(r"no such file or directory|cannot stat|command not found|"
                                           r"exit code 127", re.I)),
    ("Permission denied", re.compile(r"permission denied|access denied", re.I)),
    ("Network", re.compile(r"connection (refused|reset)|could not resolve|name or service not known|"
                           r"unreachable", re.I)),
    ("Rust panic", re.compile(r"panicked at", re.I)),
    ("Compile error", re.compile(r"error\[E\d{4}\]|could not compile", re.I)),
    ("Test failure", re.compile(r"test result: FAILED|tests? failed|assertion", re.I)),
]


def signature(job_name: str | None, failed_steps: list[str]) -> str:
    """'<job path without matrix values> › <first failed step>'. Later failed
    steps are usually diagnostics (SOS reports) that run after the first one."""
    job = _MATRIX.sub("", job_name or "").strip() or "(unnamed job)"
    step = failed_steps[0] if failed_steps else "(no failed step reported)"
    return f"{job} › {step}"


def _clean(raw: str) -> str:
    """One log line without its 'job<TAB>step<TAB>' prefix, timestamp and colours."""
    return _ANSI.sub("", _TS.sub("", raw.split("\t", 2)[-1])).rstrip()


def _collapse(lines: list[str]) -> list[str]:
    """Drop runner markers and blank lines, and fold a repeated line (digits
    ignored) into its last occurrence with a ×N count. Order kept, newest last."""
    kept = [t.strip() for t in lines if t.strip() and not t.lstrip().startswith("##[")]
    keys = [_DIGITS.sub("#", t) for t in kept]
    counts, last = Counter(keys), {k: i for i, k in enumerate(keys)}
    return [t + (f"  (×{counts[k]})" if counts[k] > 1 else "")
            for i, (t, k) in enumerate(zip(kept, keys)) if last[k] == i]


def parse_log(text: str | None) -> dict:
    """{actions, error, exit_code, key_lines, excerpt} from failed-step log text.

    ``actions`` are the composite-action steps that ended in failure, innermost
    first. ``key_lines`` (error-looking lines) and ``excerpt`` come from the
    lines before the first ``##[error]``.
    """
    lines = [_clean(raw) for raw in (text or "").splitlines()]
    names: dict = {}
    actions: list = []
    err_at = None
    for i, t in enumerate(lines):
        start, end = _START.search(t), _END.search(t)
        if start:
            names[start.group(2)] = start.group(1)
        elif end and end.group(2) == "failure":
            actions.append(names.get(end.group(1), end.group(1)))
        elif err_at is None and _ERROR.search(t):
            err_at = i
    if err_at is None:
        return {"actions": actions, "error": None, "exit_code": None, "key_lines": [], "excerpt": []}
    error = _ERROR.search(lines[err_at]).group(1).strip()
    code = _EXIT.search(error)
    ctx = _collapse(lines[max(0, err_at - _LOOKBACK):err_at])
    return {"actions": actions, "error": error, "exit_code": int(code.group(1)) if code else None,
            "key_lines": [t for t in ctx if _ERRORISH.search(t)][-_KEY_LINES:],
            "excerpt": ctx[-_EXCERPT:]}


def classify(parsed: dict) -> str | None:
    """Keyword guess at the kind of failure, from the line closest to the error."""
    lines = [*parsed.get("key_lines", []), *parsed.get("excerpt", []), parsed.get("error") or ""]
    for line in reversed(lines):
        for name, rx in _CATEGORIES:
            if rx.search(line):
                return name
    return None


def common_reasons(runs: list[dict], *, min_count: int = 1, top: int | None = None) -> list[dict]:
    """Failure signatures ranked by how many runs hit them (once per run), then
    by recency: [{signature, count, last_seen, runs: [{id, date, url}]}]."""
    groups: dict = {}
    for r in runs:
        jobs = r.get("jobs") or []
        for sig in dict.fromkeys(signature(j.get("name"), j.get("failed_steps") or []) for j in jobs):
            g = groups.setdefault(sig, {"signature": sig, "count": 0, "runs": []})
            g["count"] += 1
            g["runs"].append({"id": r.get("id"), "date": r.get("date"), "url": r.get("url")})
    for g in groups.values():
        g["runs"].sort(key=lambda x: str(x["date"] or ""), reverse=True)
        g["last_seen"] = g["runs"][0]["date"]
    ranked = sorted(groups.values(), key=lambda g: str(g["last_seen"] or ""), reverse=True)
    ranked = sorted((g for g in ranked if g["count"] >= min_count), key=lambda g: -g["count"])
    return ranked[:top] if top else ranked


def _when(ts: object) -> str:
    return str(ts)[:16].replace("T", " ") + " UTC" if ts else "?"


def _day(ts: object) -> str:
    return str(ts)[:10] if ts else "?"


def _code(s: object) -> str:
    """Text safe inside `inline code`."""
    return str(s).replace("`", "'")[:200]


def _block(lines: list[str]) -> list[str]:
    """A fenced text block that a ``` inside a log line cannot close early."""
    return ["```text", *(t.replace("```", "'''") for t in lines), "```", ""]


def _job_section(n: int, j: dict) -> list[str]:
    p, steps = j.get("parsed"), j.get("failed_steps") or []
    out = [f"### {n}. {j.get('name')}", "",
           f"- **Failed step:** {steps[0] if steps else '(none reported)'}"]
    if len(steps) > 1:
        out.append(f"- **Later failed steps:** {', '.join(steps[1:])} (usually diagnostics after "
                   "the first failure)")
    if p and p.get("actions"):
        out.append(f"- **Failing action inside the step:** {p['actions'][0]}")
    if p and p.get("error"):
        out.append(f"- **Error:** {p['error']}")
    if j.get("category"):
        out.append(f"- **Likely category:** {j['category']} (keyword guess, check the log)")
    out += [f"- **Job log:** [open on GitHub]({j.get('url')})", ""]
    if j.get("log_error"):
        return out + [f"The failed-step log could not be downloaded: {j['log_error']}", ""]
    if p and p.get("error") is None:
        return out + ["No `##[error]` line was found in the failed-step log.", ""]
    if p and p.get("key_lines"):
        out += ["Error lines before the failure:", "", *_block(p["key_lines"])]
    if p and p.get("excerpt"):
        out += ["Last lines before the failure:", "", *_block(p["excerpt"])]
    return out


def markdown(a: dict) -> str:
    """The analysis document for one failed run (GitHub-flavoured Markdown).

    ``a``: repo, workflow, window_days, run, jobs (each with signature, parsed,
    log_error, category), reasons (common_reasons over the window), failed_total,
    last_success, changes ({total, commits} or {error}), history_error, generated.
    """
    run, repo, jobs = a.get("run") or {}, a.get("repo"), a.get("jobs") or []
    num, sha, days = run.get("run_number") or run.get("id"), run.get("head_sha"), a.get("window_days")
    out = [f"# EMF nightly failure: run #{num}", "",
           f"- **Workflow:** `{a.get('workflow')}` in `{repo}`",
           f"- **Run:** [#{num}]({run.get('url')}), attempt {run.get('run_attempt') or 1}, started "
           f"{_when(run.get('created_at'))} ({run.get('event') or '?'})",
           f"- **Commit:** [{(sha or '')[:10]}](https://github.com/{repo}/commit/{sha}) on "
           f"`{run.get('head_branch')}`"]
    if run.get("title") and run.get("event") != "schedule":     # a scheduled run's title is the workflow name
        out.append(f"- **Run title:** {run['title']}")
    out += [f"- **Result:** {run.get('conclusion') or '?'}, {len(jobs)} failed job(s)", "",
            "## Summary", ""]
    for j in jobs:
        p = j.get("parsed") or {}
        line = (p.get("key_lines") or p.get("excerpt") or [None])[-1]
        cat = f" ({j['category']}, keyword guess)" if j.get("category") else ""
        where = (j.get("failed_steps") or ["(no failed step reported)"])[0]
        out.append(f"- **{j.get('name')}** failed at *{where}*{cat}"
                   + (f": `{_code(line)}`" if line else "."))
    if not jobs:
        out.append("No failed jobs were reported for this run.")
    out += ["", "## Failed jobs", ""]
    for n, j in enumerate(jobs, 1):
        out += _job_section(n, j)

    out += [f"## Pattern in the {days} days up to this run", ""]
    if a.get("history_error"):
        out += [f"Run history unavailable: {a['history_error']}", ""]
    else:
        by_sig = {g["signature"]: g for g in a.get("reasons") or []}
        for sig in dict.fromkeys(j.get("signature") for j in jobs):
            g = by_sig.get(sig)
            others = [r for r in (g or {}).get("runs", []) if r.get("id") != run.get("id")]
            if not others:
                out.append(f"- `{_code(sig)}`: no other failed run in the window had this failure.")
                continue
            out.append(f"- `{_code(sig)}`: {g['count']} of {a.get('failed_total')} failed runs. Others: "
                       + ", ".join(f"[{_day(r['date'])}]({r['url']})" for r in others[:_MAX_OTHERS])
                       + (f" and {len(others) - _MAX_OTHERS} more" if len(others) > _MAX_OTHERS else ""))
        out.append("")

        out += ["## Since the last successful run", ""]
        last = a.get("last_success")
        if not last:
            out += [f"No successful run in the {days} days up to this one, so changes are not listed.", ""]
        else:
            out.append(f"- **Last success:** [#{last.get('run_number') or last.get('id')}]({last.get('url')}) "
                       f"on {_when(last.get('created_at'))}, commit `{(last.get('head_sha') or '')[:10]}`")
            ch = a.get("changes")
            if last.get("head_sha") == sha:
                out.append("- Same commit as this run: no code changed between the two, which points at the "
                           "test environment rather than the code (inference).")
            elif ch and ch.get("error"):
                out.append(f"- Changes could not be listed: {ch['error']}")
            elif ch:
                commits = list(reversed(ch.get("commits") or []))          # newest first
                out.append(f"- **Commits since then:** {ch.get('total', len(commits))}")
                for c in commits[:_MAX_COMMITS]:
                    subject = (c.get("message") or "").split("\n", 1)[0]
                    out.append(f"  - [{(c.get('sha') or '')[:10]}]({c.get('url')}) {subject} ({c.get('author')})")
                if len(commits) > _MAX_COMMITS:
                    out.append(f"  - and {len(commits) - _MAX_COMMITS} more")
            out.append("")
    out += ["---", "", f"Generated by EXA Merge Reporter on {a.get('generated')}. Categories are keyword "
            "guesses from the log; read the log before acting."]
    return "\n".join(out) + "\n"
