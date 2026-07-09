"""Send a message to Slack — via an Incoming Webhook URL or a bot token.

Used by the daily-report scheduler in the daemon, which runs autonomously, so it
needs its own credential (not the interactive MCP connector). Prefers a webhook
URL; falls back to a bot token + channel (chat.postMessage).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class SlackError(RuntimeError):
    pass


def configured(slack_cfg: dict) -> bool:
    return bool(slack_cfg.get("enabled")
                and (slack_cfg.get("webhook_url") or slack_cfg.get("bot_token")))


def _post(url: str, payload: dict, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode()


def _via_webhook(url: str, text: str) -> dict:
    try:
        status, body = _post(url, {"text": text}, {})
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"webhook HTTP {exc.code}: {exc.read().decode()[:200]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"webhook failed: {exc}"}
    if status == 200 and body.strip() == "ok":
        return {"ok": True}
    return {"ok": False, "error": f"webhook returned {status}: {body[:200]}"}


def _via_bot(token: str, channel: str, text: str) -> dict:
    try:
        _status, body = _post("https://slack.com/api/chat.postMessage",
                              {"channel": channel, "text": text},
                              {"Authorization": "Bearer " + token})
        data = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"chat.postMessage HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"chat.postMessage failed: {exc}"}
    if data.get("ok"):
        return {"ok": True, "ts": data.get("ts"), "channel": data.get("channel")}
    return {"ok": False, "error": "slack error: " + str(data.get("error") or body[:200])}


def post(slack_cfg: dict, text: str) -> dict:
    """Post `text` (Slack mrkdwn). Returns {ok, error?}."""
    webhook = (slack_cfg.get("webhook_url") or "").strip()
    token = (slack_cfg.get("bot_token") or "").strip()
    if webhook:
        return _via_webhook(webhook, text)
    if token:
        channel = (slack_cfg.get("channel") or "").strip()
        if not channel:
            return {"ok": False, "error": "slack.channel is required with a bot_token"}
        return _via_bot(token, channel, text)
    return {"ok": False, "error": "no slack.webhook_url or slack.bot_token configured"}
