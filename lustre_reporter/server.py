"""HTTPS server + JSON API for Lustre Reporter.

Pure standard-library (``http.server``). Binds to localhost only — it shells
out to CLIs that hold the user's Gerrit/Jira/Maloo credentials, so it must not
be reachable off-box. Heavy read endpoints are cached briefly; ``?refresh=1``
bypasses the cache. Nothing here writes to Gerrit/Jira; the "ping" endpoint
only *builds* a Teams compose link for the user to send themselves.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import publish
from .analysis import backport, stability
from .config import Config
from .sources import gerrit, git_tags, jira, maloo, teams

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json",
}


class TTLCache:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._d: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._d.get(key)
            if not hit:
                return None
            expires, value = hit
            if time.time() > expires:
                self._d.pop(key, None)
                return None
            return value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._d[key] = (time.time() + self.ttl, value)

    def drop(self, key: str) -> None:
        with self._lock:
            self._d.pop(key, None)


# ----------------------------- endpoint logic -----------------------------


def _int(qs: dict, name: str, default: int) -> int:
    try:
        return int(qs.get(name, [str(default)])[0])
    except (ValueError, TypeError):
        return default


def api_config(cfg: Config, qs: dict) -> dict:
    return {
        "branches": [{
            "key": b.key, "label": b.label, "gerrit_branch": b.gerrit_branch,
            "gerrit_project": b.gerrit_project, "maloo_trigger_job": b.maloo_trigger_job,
            "ping_name": b.ping_name, "ping_email": b.ping_email,
        } for b in cfg.branches],
        "masters": [{"key": m.key, "label": m.label,
                     "project": m.gerrit_project, "branch": m.gerrit_branch}
                    for m in cfg.masters],
        "gerrit_web_base": cfg.gerrit_web_base,
        "confluence_enabled": bool((cfg.confluence or {}).get("enabled")),
        "today": date.today().isoformat(),
        "defaults": {"landed_days": 7, "stability_days": 30,
                     "backport_days": cfg.backport_scan_days},
    }


def api_stability(cfg: Config, qs: dict) -> dict:
    branch_key = qs.get("branch", ["es6"])[0]
    b = cfg.branch(branch_key)
    frm = qs.get("from", [None])[0]
    to = qs.get("to", [None])[0]

    if frm:
        try:
            span = (date.today() - date.fromisoformat(frm)).days + 1
        except ValueError:
            span = _int(qs, "days", 30)
        days = max(1, min(span, 365))
    else:
        days = _int(qs, "days", 30)

    res = maloo.sessions(b.maloo_trigger_job, days=days, limit=500)
    base = {
        "branch": branch_key, "label": b.label,
        "trigger_job": b.maloo_trigger_job, "days": days,
        "from": frm, "to": to,
    }
    if not res.ok:
        base.update({"ok": False, "kind": res.kind, "error": res.error})
        return base

    sessions = res.data
    if frm or to:
        lo = frm or "0000-00-00"
        hi = to or "9999-99-99"
        sessions = [s for s in sessions
                    if lo <= str(s.get("submission") or "")[:10] <= hi]
    base.update({"ok": True, **stability.report(sessions)})
    return base


def api_top_failures(cfg: Config, qs: dict) -> dict:
    branch_key = qs.get("branch", ["es6"])[0]
    b = cfg.branch(branch_key)
    days = _int(qs, "days", 30)
    res = maloo.top_failures(b.maloo_trigger_job, days=days,
                             sessions=_int(qs, "sessions", 60),
                             limit=_int(qs, "limit", 25))
    if not res.ok:
        return {"ok": False, "kind": res.kind, "error": res.error,
                "branch": branch_key, "days": days}
    return {"ok": True, "branch": branch_key, "days": days, "failures": res.data}


def _attach_ticket_urls(cfg: Config, tickets: list[dict]) -> None:
    for t in tickets:
        t["url"] = f"{cfg.jira_browse_base(t['project'])}/{t['key']}"
        t["is_cloud"] = cfg.is_cloud_project(t["project"])


def api_landed(cfg: Config, qs: dict) -> dict:
    mode = qs.get("mode", ["days"])[0]
    days = _int(qs, "days", 7)
    req_tag = (qs.get("tag", [""])[0] or "").strip() or None
    branches = []
    for b in cfg.branches:
        entry = {"key": b.key, "label": b.label, "gerrit_branch": b.gerrit_branch,
                 "gerrit_project": b.gerrit_project}
        if mode == "tag":
            tg = git_tags.last_tag(cfg.lustre_clone, b.gerrit_branch, tag=req_tag)
            if tg.get("fetch_note"):
                entry["fetch_note"] = tg["fetch_note"]
            if not tg.get("ok"):
                entry.update({"ok": False, "kind": "error", "error": tg.get("error"),
                              "count": 0, "patches": []})
                branches.append(entry)
                continue
            entry["tag"] = tg["tag"]
            entry["tag_date"] = tg["date"]
            entry["tag_manual"] = tg.get("manual", False)
            res = gerrit.merged_since(b.gerrit_project, b.gerrit_branch, tg["date"], limit=500)
        else:
            res = gerrit.merged_last_days(b.gerrit_project, b.gerrit_branch, days, limit=300)
        if res.ok:
            for p in res.data:
                _attach_ticket_urls(cfg, p.get("tickets", []))
            entry.update({"ok": True, "count": len(res.data), "patches": res.data})
        else:
            entry.update({"ok": False, "kind": res.kind, "error": res.error,
                          "count": 0, "patches": []})
        branches.append(entry)
    return {"mode": mode, "days": days, "tag": req_tag, "branches": branches}


def api_backports(cfg: Config, qs: dict) -> dict:
    days = _int(qs, "days", cfg.backport_scan_days)
    only_gaps = qs.get("only_gaps", ["1"])[0] != "0"
    result = backport.analyze(cfg, days, only_gaps=only_gaps)
    for row in result["candidates"]:
        _attach_ticket_urls(cfg, row.get("tickets", []))
    for bm in result["branches"]:
        bm["ping_email"] = cfg.branch(bm["key"]).ping_email
    return result


def api_ticket(cfg: Config, qs: dict) -> dict:
    key = qs.get("key", [""])[0]
    if not key or "-" not in key:
        return {"ok": False, "error": "missing/invalid ticket key", "key": key}
    prefix = key.split("-")[0]
    cloud = cfg.is_cloud_project(prefix)
    browse = f"{cfg.jira_browse_base(prefix)}/{key}"
    res = jira.get(key, cloud=cloud)
    if not res.ok:
        return {"ok": False, "kind": res.kind, "error": res.error,
                "key": key, "url": browse, "is_cloud": cloud}
    data = dict(res.data)
    data.update({"ok": True, "url": browse, "is_cloud": cloud})
    return data


def api_change(cfg: Config, qs: dict) -> dict:
    url = qs.get("url", [""])[0]
    if not url:
        return {"ok": False, "error": "missing change url"}
    res = gerrit.change_info(url)
    if not res.ok:
        return {"ok": False, "kind": res.kind, "error": res.error}
    return {"ok": True, **gerrit.verified_summary(res.data)}


def api_ping(cfg: Config, qs: dict) -> dict:
    branch_key = qs.get("branch", [""])[0]
    try:
        b = cfg.branch(branch_key)
    except KeyError:
        return {"ok": False, "error": f"unknown branch {branch_key!r}"}
    subject = qs.get("subject", [""])[0]
    url = qs.get("url", [""])[0]
    ticket_lines = [
        f"{k} {cfg.jira_browse_base(k.split('-')[0])}/{k}"
        for k in qs.get("ticket", []) if "-" in k
    ]
    result = teams.compose(b.ping_email, b.ping_name, b.gerrit_branch,
                           subject, url, ticket_lines)
    result["ok"] = True
    result["branch"] = branch_key
    return result


def api_publish(cfg: Config, qs: dict) -> dict:
    """Build + push the per-branch landed-patches changelog to Confluence now."""
    return publish.publish_all(cfg)


# Endpoints that are safe/beneficial to cache, with their TTLs (seconds).
_CACHED = {
    "/api/stability": 300,
    "/api/top-failures": 900,
    "/api/landed": 300,
    "/api/backports": 600,
    "/api/ticket": 900,
    "/api/change": 600,
}
_ROUTES = {
    "/api/config": api_config,
    "/api/stability": api_stability,
    "/api/top-failures": api_top_failures,
    "/api/landed": api_landed,
    "/api/backports": api_backports,
    "/api/ticket": api_ticket,
    "/api/change": api_change,
    "/api/ping": api_ping,
    "/api/publish": api_publish,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "LustreReporter/0.1"
    cfg: Config = None  # type: ignore[assignment]
    cache: TTLCache = None  # type: ignore[assignment]

    def log_message(self, fmt, *args):  # quieter, single-line access log
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    # --- helpers ---
    def _send_json(self, obj: object, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        if rel in ("", "/"):
            rel = "index.html"
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path in _ROUTES:
                self._handle_api(path, qs)
                return
            if path == "/" or path == "/index.html":
                self._send_static("index.html")
                return
            if path.startswith("/static/"):
                self._send_static(path[len("/static/"):])
                return
            self._send_json({"error": "not found", "path": path}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # never let a handler crash the server
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)

    def _handle_api(self, path: str, qs: dict) -> None:
        refresh = qs.get("refresh", ["0"])[0] == "1"
        ttl = _CACHED.get(path)
        cache_key = None
        if ttl is not None:
            keyq = {k: v for k, v in qs.items() if k != "refresh"}
            cache_key = path + "?" + json.dumps(keyq, sort_keys=True)
            if refresh:
                self.cache.drop(cache_key)
            else:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    self._send_json(cached)
                    return
        result = _ROUTES[path](self.cfg, qs)
        if cache_key is not None:
            self.cache.set(cache_key, result)
        self._send_json(result)


def make_server(cfg: Config, cache_ttl: int = 300) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,),
                   {"cfg": cfg, "cache": TTLCache(cache_ttl)})
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), handler)
    return httpd
