"""Minimal Confluence Cloud (v2 REST) client — just enough to upsert a page.

Reuses the Atlassian cloud credentials already configured for Jira Cloud
(``~/.jira-tool.json`` → ``instances.cloud``: email + API token). The same token
authenticates Confluence on the same site, so no extra secret is needed.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from . import atlassian
from .atlassian import AtlassianError


class ConfluenceError(RuntimeError):
    pass


class Confluence:
    def __init__(self, site: str | None = None):
        try:
            server, email, token = atlassian.cloud_creds()
        except AtlassianError as exc:
            raise ConfluenceError(str(exc)) from exc
        self.base = (site or server).rstrip("/") + "/wiki"
        self._auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": "Basic " + self._auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise ConfluenceError(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode()[:300]}")
        except Exception as exc:  # noqa: BLE001
            raise ConfluenceError(f"{method} {path} failed: {exc}")

    def find_page(self, space_id: str, title: str) -> dict | None:
        q = urllib.parse.urlencode({"space-id": space_id, "title": title, "limit": 1})
        results = self._req("GET", f"/api/v2/pages?{q}").get("results") or []
        return results[0] if results else None

    def upsert(self, space_id: str, parent_id: str | None, title: str, html: str) -> dict:
        existing = self.find_page(space_id, title)
        if existing:
            pid = existing["id"]
            version = (self._req("GET", f"/api/v2/pages/{pid}").get("version") or {}).get("number", 1)
            page = self._req("PUT", f"/api/v2/pages/{pid}", {
                "id": str(pid), "status": "current", "title": title,
                "body": {"representation": "storage", "value": html},
                "version": {"number": version + 1, "message": "Automated update by Lustre Reporter"},
            })
            action = "updated"
        else:
            body = {"spaceId": str(space_id), "status": "current", "title": title,
                    "body": {"representation": "storage", "value": html}}
            if parent_id:
                body["parentId"] = str(parent_id)
            page = self._req("POST", "/api/v2/pages", body)
            action = "created"
        webui = ((page.get("_links") or {}).get("webui")) or ""
        return {"action": action, "id": page.get("id"),
                "url": (self.base + webui) if webui else None}
