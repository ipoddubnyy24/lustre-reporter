"""Shared Atlassian *cloud* access.

Jira Cloud and Confluence Cloud live on the same DDN site and share one
email + API-token (``~/.jira-tool.json`` → ``instances.cloud``). This is the
single place that loads those creds and does an authenticated GET, so the
Confluence client and the Jira-versions lookup don't each reinvent it.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path


class AtlassianError(RuntimeError):
    pass


def cloud_creds() -> tuple[str, str, str]:
    """Return (server, email, token) for the DDN Atlassian cloud site."""
    path = Path.home() / ".jira-tool.json"
    if not path.exists():
        raise AtlassianError("~/.jira-tool.json not found (need Atlassian cloud email + token)")
    cloud = (json.loads(path.read_text()).get("instances") or {}).get("cloud") or {}
    auth = cloud.get("auth") or {}
    server, email, token = (cloud.get("server") or "").rstrip("/"), auth.get("email"), auth.get("token")
    if not (server and email and token):
        raise AtlassianError("~/.jira-tool.json 'cloud' instance missing server/email/token")
    return server, email, token


def auth_header() -> str:
    """HTTP Basic header value for the cloud creds."""
    _, email, token = cloud_creds()
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def cloud_get(path: str) -> object:
    """GET ``<server><path>`` with cloud basic auth; return parsed JSON (or None)."""
    server, _, _ = cloud_creds()
    req = urllib.request.Request(server + path, headers={
        "Authorization": auth_header(), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise AtlassianError(f"GET {path} -> HTTP {exc.code}: {exc.read().decode()[:200]}")
    except Exception as exc:  # noqa: BLE001
        raise AtlassianError(f"GET {path} failed: {exc}")
