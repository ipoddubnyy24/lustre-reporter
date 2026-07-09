# Lustre Reporter

A local, web-based dashboard for the health of the **ExaScaler Lustre**
release branches — **ES6 (`b_es6_0`)** and **ES7 (`b_es7_0`)**. It answers three
questions the porting team asks every week:

1. **How stable are the recent nightly builds?** — pass-rate trend over time,
   with drill-down into any period and the top failing tests.
2. **What landed recently?** — every patch merged to each branch in the last N
   days, with ticket and Gerrit links.
3. **What should we backport from master?** — patches on master that are missing
   from a branch, *including companion patches that were missed while porting a
   ticket*, cross-referenced with the DDN/EX/LU tickets, with one-click **"ping
   the branch owner on Teams"** (Li Xi for ES6, Marc-Andre Vef for ES7).

It runs entirely on your machine and serves over **https://localhost:9835**.

The UI is a Material Design dashboard: **all three reports load as soon as you
open it** (no click-to-load), with a one-click **Refresh** (app-bar icon or the
floating button) and an optional **auto-refresh** interval. Light and dark
themes follow the OS.

## How it works

The app is a small, **dependency-free** Python program (standard library only).
It does not talk to Gerrit/Jira/Maloo directly — instead it shells out to the
[`llm_jira`](../llm_jira) CLI tools (`gerrit`, `jira`, `maloo`), so it inherits
their existing credentials and settings. Nothing is hard-coded and the app
itself stores no secrets.

| Report | Source | Status |
|--------|--------|--------|
| Landed patches | `gerrit search` (project `ex/lustre-release`) | ✅ works out of the box |
| Backport candidates | `gerrit search` (masters) + `jira get` (lazy) | ✅ works out of the box |
| Build stability | `maloo sessions` / `maloo top-failures` | ⚠️ needs Maloo credentials (see below) |

> **Jenkins** was intentionally left out for now. When you want to add real
> nightly build results (`build.whamcloud.com`, jobs `lustre-b_es6_0` /
> `lustre-b_es7_0`), configure the `jenkins` CLI and wire a source module
> alongside `sources/maloo.py`.

## Requirements

- Python 3.9+
- The `llm_jira` tools installed and on `PATH` (`gerrit`, `jira`, `maloo`):
  ```
  cd ~/work/src/llm_jira && ./install.sh
  ```
- `openssl` (used once to generate the self-signed localhost certificate).

## Run

```bash
cd ~/work/src/lustre_reporter
./scripts/run.sh            # or: python3 -m lustre_reporter
```

Then open **https://localhost:9835** and accept the one-time self-signed
certificate warning (the cert is generated into `certs/`, which is git-ignored).

Options: `--port N`, `--host H`, `--open` (open a browser), `--ttl S` (cache TTL).

## Run at login (macOS)

Build a native app bundle that is **clearly identifiable in System Settings →
General → Login Items** — it appears as **"Lustre Reporter"** with a bar-chart
icon, not an anonymous `python3` process:

```bash
./scripts/make-macos-app.sh          # builds "~/Applications/Lustre Reporter.app"
```

Then add **Lustre Reporter** under Login Items → **+**. At login it starts the
server and opens the dashboard. Bundle id: `com.ddn.lustre-reporter`. (It runs as
a background agent — `LSUIElement` — so it doesn't clutter the Dock; remove that
key from `Info.plist` if you want a Dock icon.)

Prefer a headless launchd service? Use the agent template instead — it's
identifiable in `launchctl list` and Login Items by the label
`com.ddn.lustre-reporter`:

```bash
sed "s#__REPO_DIR__#$HOME/work/src/lustre_reporter#g" \
  scripts/com.ddn.lustre-reporter.plist > ~/Library/LaunchAgents/com.ddn.lustre-reporter.plist
launchctl load ~/Library/LaunchAgents/com.ddn.lustre-reporter.plist
```

## Enabling the build-stability report (Maloo)

The stability tab reads nightly CI results from Maloo
(`testing.whamcloud.com`). If it shows **"Maloo credentials rejected (HTTP
401)"**, put a working login in `~/.config/maloo-tool/.env`:

```
MALOO_USER=<your testing.whamcloud.com login>
MALOO_PASS=<your testing.whamcloud.com password>
```

Then click **↻ Refresh**. The `maloo_trigger_job` per branch defaults to
`lustre-b_es6_0` / `lustre-b_es7_0`; adjust in `config.local.json` if your CI
uses different job names.

## The Teams ping

On a backport candidate, **Ping Li Xi** (ES6) / **Ping Marc-Andre Vef** (ES7)
opens a dialog with a short, human-worded message
("*please consider this patch for backport to `b_es6_0`* …") plus the patch and
ticket links. **Open in Teams** launches a Microsoft Teams chat composer to that
person with the message pre-filled — you review it and hit send. The app never
sends anything on its own and holds no Teams credentials. **Copy** and **Email**
are provided as fallbacks. Recipients are configurable (see below).

## Configuration

Everything has a sensible default (baked into `lustre_reporter/config.py`).
To override, copy `config.example.json` to **`config.local.json`** (git-ignored)
and edit — branches, master repos to scan, ping recipients, Jira hosts, port,
and the backport scan window are all adjustable.

## API

The UI is served from `static/` and calls these JSON endpoints (all `GET`;
`?refresh=1` bypasses the short-lived cache):

| Endpoint | Purpose |
|----------|---------|
| `/api/config` | Branches, masters, defaults |
| `/api/stability?branch=es6&days=30` (or `&from=&to=`) | Trend + sessions |
| `/api/top-failures?branch=es6&days=30` | Aggregated failing tests |
| `/api/landed?days=7` | Patches merged per branch |
| `/api/backports?days=120&only_gaps=1` | master ↔ es6/es7 diff |
| `/api/ticket?key=LU-20388` | One ticket (routed to the right Jira) |
| `/api/change?url=…` | One Gerrit change's Verified/CI state |
| `/api/ping?branch=es6&subject=…&url=…&ticket=LU-1` | Draft + Teams/mailto links |

## Security

The server binds to **localhost only** and is HTTPS with a self-signed cert. It
executes local CLIs that hold your Gerrit/Jira/Maloo credentials, so do not
expose it off-box. It has no write endpoints — the "ping" only *builds* a link
for you to send yourself.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
