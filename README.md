# EXA Reporter

A local, web-based dashboard for **ExaScaler** engineering health, split into two
products via a top-level **Lustre / EMF** switch:

- **Lustre** — the ExaScaler Lustre release branches **ES6 (`b_es6_0`)** and
  **ES7 (`b_es7_0`)**, sourced from Gerrit/Maloo.
- **EMF** — the **EXAScaler Management Framework**
  (`whamcloud/exascaler-management-framework`), sourced from GitHub + Jira.

**Lustre** answers three questions the porting team asks every week:

1. **How stable are the recent nightly builds?** — pass-rate trend over time,
   with drill-down into any period and the top failing tests.
2. **What landed recently?** — every patch merged to each branch in the last N
   days, with ticket and Gerrit links.
3. **What should we backport from master?** — patches on master that are missing
   from a branch, *including companion patches that were missed while porting a
   ticket*, cross-referenced with the DDN/EX/LU tickets, with one-click **"ping
   the branch owner on Teams"** (Li Xi for ES6, Marc-Andre Vef for ES7).

**EMF** answers the parallel questions from GitHub + Jira: build stability, what
landed since the last CalVer release, and — uniquely — a **risk-weighted forecast
of what's coming** in each upcoming release (see [EMF reports](#emf-reports-github--jira)).

It runs entirely on your machine and serves over **https://localhost:9835**.

The UI is a Material Design dashboard: **every report loads as soon as you open
it** (no click-to-load; EMF loads on first switch), with a one-click **Refresh**
(app-bar icon or the floating button) and an optional **auto-refresh** interval
(30 min – 24 h). Light and dark themes follow the OS.

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

## EMF reports (GitHub + Jira)

Switch to **EMF** in the top bar for the EXAScaler Management Framework. It needs
the **`gh`** CLI on `PATH` (authenticated — `gh auth status`) for GitHub, and the
cloud Atlassian token (the same `~/.jira-tool.json` one Confluence uses) for Jira.

| EMF report | Source | What it shows |
|---|---|---|
| Build stability | GitHub Actions (`nightly-build-6_3_x.yml`) | pass-rate trend of the nightly workflow |
| Landed | GitHub Releases (CalVer) + commit compare | what merged onto the release branch since the newest CalVer release (`6.3.8-YYYYMMDDNN`) |
| Coming | EX Jira items + `fixVersion` release dates | a **risk-weighted forecast** of what lands in each upcoming release |

**The "Coming" forecast.** For each upcoming release (an unreleased EX
`fixVersion` that carries a date), each open item is scored by how advanced it is
(status tier) and how much runway remains (days to release), then summed into an
expected landing count:

| days to release | To Do | In Progress | In Review |
|---|---|---|---|
| overdue (≤ 0) | 2% | 30% | 75% |
| 1–4 | 5% | 45% | 85% |
| **5–10** | **10%** | **60%** | **90%** |
| 11–30 | 35% | 75% | 92% |
| > 30 | 60% | 85% | 95% |

Open GitHub PRs whose title/branch reference the ticket are linked in as
corroboration. Release **dates come from the Jira `fixVersion`** (cleaner and more
current than the human-maintained Confluence release timeline). The bands, the
status→tier mapping, which versions to track, and the grace window are all
configurable under `emf` in `config.local.json`; set `emf.enabled` to `false` to
hide the EMF half entirely.

### EMF Confluence publishing

The EMF Landed + Coming reports also publish to Confluence (the **"exa" folder**),
**deliberately split so nothing is confused**:

- **`EMF — Landed (current build)`** — commits already merged since the last CalVer
  release (history, *not* a forecast).
- **`EMF — Incoming: Main release`** — forecast for the ES6.3.x/ES7.x stream.
- **`EMF — Incoming: GCP`** — forecast for the Google Cloud quarterly.

Upcoming releases are classified into **release lines** (config `emf.release_lines`,
by fixVersion name) and each line gets its own page, so *landed* vs *coming* and
*main* vs *GCP* are never mixed. Each page carries a plain "what this is / what it
isn't" banner plus a companion-pages note. Auto-published twice daily (**00:00 /
12:00 America/Los_Angeles**, alongside Lustre); manual via the EMF **Publish to
Confluence** button, `GET /api/emf/publish`, or `python3 -m lustre_reporter
--publish-now` (which does Lustre + EMF). Config under `emf.confluence`
(`space_id`, `parent_id` = the folder, titles).

## Requirements

- Python 3.9+
- The `llm_jira` tools installed and on `PATH` (`gerrit`, `jira`, `maloo`):
  ```
  cd ~/work/src/llm_jira && ./install.sh
  ```
- `openssl` (used once to generate the self-signed localhost certificate).
- For the **EMF** reports: the GitHub CLI **`gh`** on `PATH`, authenticated
  (`gh auth status`), with read access to `whamcloud/exascaler-management-framework`.
  (Lustre-only users can set `emf.enabled` to `false` and skip this.)

## Run

```bash
cd ~/work/src/lustre_reporter
./scripts/run.sh            # or: python3 -m lustre_reporter
```

Then open **https://localhost:9835** and accept the one-time self-signed
certificate warning (the cert is generated into `certs/`, which is git-ignored).

Options: `--port N`, `--host H`, `--open` (open a browser), `--ttl S` (cache TTL).

## Install as a macOS app

Build a **self-contained** "Lustre Reporter.app" — it bundles the code and web
assets, so it runs from `/Applications` with no source checkout. Either build a
drag-to-install disk image, or install straight to `~/Applications`:

```bash
./scripts/make-dmg.sh        # → dist/Lustre Reporter.dmg  (open it, drag onto Applications)
# or:
./scripts/make-macos-app.sh  # installs "~/Applications/Lustre Reporter.app"
```

Double-click to run — it opens **https://localhost:9835** and shows a Dock icon
(quit from there). It's **clearly identifiable in System Settings → General →
Login Items**, so add **Lustre Reporter** there to launch at login (bundle id
`com.ddn.lustre-reporter`).

- **Requirements:** `python3` (macOS Command Line Tools or Homebrew) and the
  `llm_jira` CLIs (`jira`/`gerrit`/`maloo`) on `PATH` for data.
- **Writable state:** the TLS cert and an optional `config.local.json` live in
  `~/Library/Application Support/Lustre Reporter/` — the app bundle stays
  read-only. (Overridable with `LUSTRE_REPORTER_CERT_DIR` / `LUSTRE_REPORTER_CONFIG`.)

### Run as a background service (daemon)

For a headless launchd service (no Dock icon, survives crashes, autostarts at
login), use the control script — a per-user LaunchAgent labeled
`com.ddn.exa-reporter`:

```bash
./scripts/exa_reporter_daemon.sh start       # install + run (also starts at login)
./scripts/exa_reporter_daemon.sh status      # loaded? PID? last exit? port listening?
./scripts/exa_reporter_daemon.sh restart
./scripts/exa_reporter_daemon.sh stop         # stop now (agent stays; returns at next login)
./scripts/exa_reporter_daemon.sh uninstall    # stop + remove the agent (disables autostart)
./scripts/exa_reporter_daemon.sh logs [N]     # tail stdout/stderr
```

Logs are written to `~/Library/Logs/com.ddn.exa-reporter.*.log`. Override the
port with `LUSTRE_REPORTER_PORT` (default 9835) — don't run the daemon and
`run.sh` on the same port simultaneously.

## Confluence publishing (QA changelog)

The Landed report publishes a **per-branch QA changelog** to Confluence — one
page per branch in the target folder. For each *build* (tag) it shows:

- **In build `<tag>`**: what that build added vs the previous build
  (`prev_tag..tag`). Always populated, even right after a tag is cut — which is
  exactly what QA needs to plan tests for that build.
- **Coming next**: merged since the latest tag (`tag..HEAD`), not yet in a build.
- **Earlier builds**: collapsed history.

Each section has an **"Areas touched"** subsystem summary (e.g.
`kernel ×3 · pcc ×2 · tests ×4 · lnet ×1`) so QA can pick which suites to run,
with linked tickets (Jira, correct host) and patches (Gerrit).

- **Automatic:** as the daemon, it republishes at **00:00 and 12:00
  America/Los_Angeles** (DST-correct via `zoneinfo`).
- **Manual:** the **Publish to Confluence** button on the Landed tab, or
  `python3 -m lustre_reporter --publish-now`.

Configure under `confluence` in `config.local.json` (`enabled`, `space_id`,
`parent_id` = target folder, `title_template`, `max_builds`). Credentials reuse
the cloud Atlassian token from `~/.jira-tool.json`. Set `confluence.enabled` to
`false` to disable.

## Daily Slack report

The daemon can post a **daily build-health report to Slack** — per branch, the
build-stability numbers **plus the last-7-days clean-rate trend** (e.g.
`57.1% → 43.8% → 37.5%  ↘`) and the **patches landed since the last tag only**
(each with its ticket and Gerrit links; "nothing yet" right after a tag is cut).

- **Automatic:** as the daemon, it posts once a day at **09:00
  America/Los_Angeles** (DST-correct via `zoneinfo`; change the hour with
  `slack.hour`).
- **Manual:** `python3 -m lustre_reporter --slack-now` (also the
  `GET /api/slack-report` endpoint).

Configure under `slack` in `config.local.json`. Provide **either** an
[Incoming Webhook](https://api.slack.com/messaging/webhooks) URL **or** a bot
token (`chat:write`) plus a `channel`:

```json
"slack": { "enabled": true, "webhook_url": "https://hooks.slack.com/services/…" }
```
```json
"slack": { "enabled": true, "bot_token": "xoxb-…", "channel": "#lustre-builds" }
```

Then `./scripts/exa_reporter_daemon.sh restart` to pick up the schedule. Set
`slack.enabled` to `false` (the default) to disable.

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
the backport scan window, and `lustre_clone` (your local `ex/lustre-release`
checkout, used by the Landed **"since last tag"** filter to resolve each
branch's latest release tag — or a specific tag you type in) are all adjustable.

**Data freshness:** the tag/changelog data is refreshed from the remote *before
every read* so it never depends on your local copy being up to date — it tries,
in order, any URLs in `git_fetch.remotes` (put a GitHub mirror here, may use
`{branch}`), then **Gerrit over HTTPS** (needs no SSH key), then the clone's SSH
origin, then the local copy as-is (shown with a visible ⚠ if no remote was
reachable). The other reports (stability, landed-by-days, backports) already
query Gerrit/Maloo live.

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
| `/api/publish` | Push the QA changelog to Confluence now |
| `/api/slack-report` | Post the daily build-health report to Slack now |
| `/api/emf/stability?days=30` | EMF nightly CI pass-rate trend (GitHub Actions) |
| `/api/emf/landed?tag=…` | EMF commits since the latest (or given) CalVer release |
| `/api/emf/coming` | Risk-weighted forecast per upcoming release (Jira × bands) |
| `/api/emf/publish` | Push the EMF Landed + per-line Incoming pages to Confluence now |

## Tests

```bash
./scripts/test.sh          # bootstraps .venv, runs pytest with coverage
```

Unit tests live in `tests/` (pytest). Every external interaction — the
`llm_jira` CLIs, `git`, and Confluence/Slack/HTTP — is mocked, so the suite is
hermetic and fast (no network, no real repos). Coverage is enforced at **100%**
(statements **and** branches) via `pyproject.toml` (`fail_under = 100`).

## Security

The server binds to **localhost only** and is HTTPS with a self-signed cert. It
executes local CLIs that hold your Gerrit/Jira/Maloo credentials, so do not
expose it off-box. It has no write endpoints — the "ping" only *builds* a link
for you to send yourself.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
