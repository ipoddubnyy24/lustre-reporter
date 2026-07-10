# EXA Reporter — Installation Guide (for an AI agent)

> **Audience:** an autonomous coding agent installing and running this app on a
> fresh machine. Execute the steps **in order**. After each step, run its
> **Verify** command and confirm the **Expect**ed result before continuing. On a
> mismatch, apply **On failure**; if that doesn't resolve it, **stop and report
> the exact failing step + output** — do not guess.
>
> **Hard rules:**
> - Never invent, guess, or hard-code a credential. If a secret/CLI is missing,
>   report *exactly which one* and which reports it gates; then continue with the
>   parts that don't need it (the app degrades gracefully per source).
> - Never commit `config.local.json`, `certs/`, `.venv/`, or `dist/` (all
>   git-ignored; `config.local.json` holds secrets).
> - Secrets belong in the CLI credential files (below), **not** typed into the app.

---

## 0. What you are installing

A local, dependency-free (Python **standard-library only**) web dashboard that
serves **`https://localhost:9835`** and reports on two products via a top-level
switch: **Lustre** (ExaScaler Lustre branches, from Gerrit/Maloo) and **EMF**
(EXAScaler Management Framework, from GitHub + Jira). It holds no secrets itself
— it **shells out** to already-configured CLIs (`gerrit`/`gc`, `jira`, `maloo`,
`gh`, `git`) and reuses their credentials.

| Report | Product | Data source (CLI/API) | Degrades to |
|---|---|---|---|
| Build stability | Lustre | `maloo` | error banner if Maloo unauthenticated |
| Landed / Backports | Lustre | `gerrit`, `jira`, local `git` clone | error banner |
| Build stability | EMF | `gh` (GitHub Actions) | error banner |
| Landed (CalVer) | EMF | `gh` (releases + compare) | error banner |
| Incoming (forecast) | EMF | `jira` (EX) + Atlassian cloud REST | error banner |

The app runs even if some sources are unauthenticated — each failing report just
shows a banner. So a partial install is valid; enable sources incrementally.

---

## 1. Platform assumptions

- macOS or Linux, `bash`/`zsh`.
- Network egress to: `github.com`, `review.whamcloud.com`, `testing.whamcloud.com`,
  `ime-ddn.atlassian.net` (DDN-internal — a public runner cannot reach these or
  hold the credentials; that is expected).

---

## 2. Prerequisites — verify each

```bash
python3 --version          # Expect: Python 3.9 or newer
git --version              # Expect: any
openssl version            # Expect: any (used once to self-sign the localhost cert)
gh --version               # Expect: any (EMF reports)
command -v gerrit gc jira maloo   # Expect: paths for all four (Lustre + Jira reports)
```

**On failure:**
- No `python3`/`git`/`openssl` → install via the OS package manager (macOS:
  `xcode-select --install` gives python3+git; `brew install openssl gh`).
- No `gerrit`/`gc`/`jira`/`maloo` → they come from the `llm_jira` toolset:
  `cd ~/work/src/llm_jira && ./install.sh`. If that repo is absent, these Lustre
  reports cannot work — record it and continue with EMF.
- No `gh` → `brew install gh`, then step 4.

---

## 3. Get the code

```bash
gh repo clone ipoddubnyy24/lustre-reporter ~/work/src/lustre_reporter
cd ~/work/src/lustre_reporter
```

**Verify:** `ls lustre_reporter/ scripts/ static/ pyproject.toml`
**Expect:** all exist. **On failure:** the repo is **private** — ensure `gh auth status` shows an account with read access, then retry.

---

## 4. Credentials matrix (which report each unlocks, and where it lives)

The app reads these files at request time via the CLIs/REST. Populate only the
ones for the reports you need. **Do not** put these in the app or the repo.

| Source | File | Keys | Powers | Verify |
|---|---|---|---|---|
| Gerrit | `~/.config/gerrit-cli/.env` | `GERRIT_USER`, `GERRIT_PASS` (HTTP password) | Lustre Landed/Backports; git-over-HTTPS fetch | `gc search 'status:merged limit:1' >/dev/null && echo ok` |
| Jira | `~/.jira-tool.json` | `instances.cloud.{server,auth.email,auth.token}` (EX/DDN) + LU PAT | tickets; EMF Incoming; Confluence; `jira.versions` | `jira get LU-1 >/dev/null && echo ok` |
| Maloo | `~/.config/maloo-tool/.env` | `MALOO_USER` (**email!**), `MALOO_PASS` | Lustre Build stability | `maloo sessions lustre-b_es6_0 --days 1 >/dev/null && echo ok` |
| GitHub | `gh` keyring | `gh auth login` | all EMF reports | `gh auth status` and `gh api repos/whamcloud/exascaler-management-framework --jq .full_name` |

**Critical gotcha:** `MALOO_USER` must be the **email address**
(`name@ddn.com`), not the short login — the short form returns HTTP 401.

The single Atlassian **cloud** token in `~/.jira-tool.json` authenticates Jira
Cloud, Confluence, and the EMF `fixVersion` date lookups — no separate secret.

---

## 5. Configuration (optional — defaults work out of the box)

All behaviour has baked-in defaults (`lustre_reporter/config.py`). Override only
to enable Slack, change the port, or retarget publishing:

```bash
cp config.example.json config.local.json   # git-ignored; edit as needed
```

`config.example.json` documents every key. You only need `config.local.json` to:
enable the **Slack daily report** (`slack.enabled=true` + `slack.webhook_url`);
change `emf.confluence` / `emf.release_lines`; or override `port`, `lustre_clone`,
etc. Nested dict keys are shallow-merged (an override replaces the whole subtree).

**Never commit `config.local.json`** — it carries the Slack webhook and is
git-ignored on purpose.

---

## 6. Run — choose ONE

### 6a. Foreground (dev)
```bash
./scripts/run.sh                 # or: ./scripts/run.sh --port 9999 --open
```
Runs in the terminal; `Ctrl-C` to stop. First run self-signs a cert into `certs/`.

### 6b. Daemon (recommended; autostarts at login on macOS)
```bash
./scripts/exa_reporter_daemon.sh start      # install LaunchAgent + run
./scripts/exa_reporter_daemon.sh status     # loaded? PID? port listening?
./scripts/exa_reporter_daemon.sh restart    # after any code/config change
./scripts/exa_reporter_daemon.sh logs 40    # tail stdout/stderr
./scripts/exa_reporter_daemon.sh stop|uninstall
```
launchd label `com.ddn.exa-reporter`; logs in `~/Library/Logs/com.ddn.exa-reporter.*.log`.
**The daemon loads Python at start** — restart it after editing any `.py` (static
files are served from disk and need no restart).

### 6c. Installed macOS `.app`
```bash
./scripts/make-macos-app.sh      # -> ~/Applications/Lustre Reporter.app
./scripts/make-dmg.sh            # -> dist/*.dmg (drag-to-install)
```

**Verify (any mode):**
```bash
curl -sk https://localhost:9835/api/config | python3 -c "import sys,json;d=json.load(sys.stdin);print('branches',[b['key'] for b in d['branches']],'emf',d['emf_enabled'])"
```
**Expect:** `branches ['es6', 'es7'] emf True`
**On failure:** `... port ... already in use` → another instance is running (don't
run 6a and 6b on the same port); or the server didn't start → check
`./scripts/exa_reporter_daemon.sh logs`. `curl` needs `-k` (self-signed TLS).

---

## 7. Verify the reports respond

```bash
for p in "stability?branch=es6&days=30" "landed?days=7" "backports?days=120" \
         "emf/stability?days=30" "emf/landed" "emf/coming"; do
  printf '%-28s ' "$p"; curl -sk "https://localhost:9835/api/$p" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok' if d.get('ok') or 'branches' in d or 'releases' in d else 'ERR '+str(d.get('kind'))+': '+str(d.get('error'))[:80])"
done
```
**Expect:** `ok` per line. An `ERR auth`/`ERR missing` means that source's
credentials/CLI (step 2/4) aren't set up — expected on a partial install; fix the
named source or leave that report disabled.

---

## 8. Run the test suite (should be 100%)

```bash
./scripts/test.sh
```
Bootstraps a `.venv` (Homebrew Python is PEP-668 externally-managed, so a venv is
required) with `pytest`+`pytest-cov` and runs the suite. **Expect** the tail:
`Required test coverage of 100.0% reached` and `NNN passed`. Coverage is
gated at 100% (`pyproject.toml` `fail_under = 100`); a drop fails the run.

---

## 9. Feature setup (optional)

- **Slack daily report** (09:00 America/Los_Angeles): create an Incoming Webhook,
  set `slack.enabled=true` + `slack.webhook_url` in `config.local.json`, restart
  the daemon, then test once: `python3 -m lustre_reporter --slack-now` → Expect
  `{"ok": true, ...}`.
- **EMF Confluence publishing** (twice daily; the "exa" folder): needs `gh` +
  the Atlassian cloud token. Test once: `python3 -m lustre_reporter --publish-now`
  (publishes Lustre + EMF) → Expect each result `ok: true`.

---

## 10. Troubleshooting (symptom → cause → fix)

- **`/api/stability` → `ERR auth` "HTTP 401" (Maloo)** → `MALOO_USER` is the short
  login → set it to the **email** in `~/.config/maloo-tool/.env`, retry.
- **`/api/landed` (tag mode) shows a "⚠ may be stale" note** → no remote reachable;
  the fetch falls back to the local clone. Ensure Gerrit HTTP creds are current
  (`GERRIT_PASS` gets rotated) or the clone at `lustre_clone` exists.
- **EMF endpoints → `ERR` about `gh`** → `gh auth status` must show read access to
  `whamcloud/exascaler-management-framework`; and `gh` must be on the daemon's
  `PATH` (it uses `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`).
- **Port already in use** → `lsof -nP -iTCP:9835 -sTCP:LISTEN`; stop the other
  instance or set `LUSTRE_REPORTER_PORT` / `--port`.
- **Browser "not secure" warning** → expected (self-signed localhost cert); accept
  once, or use `curl -k`.

---

## 11. Never do

- Commit `config.local.json`, `certs/`, `.venv/`, `dist/`, or `__pycache__/`.
- Type credentials into the web UI — they live in the CLI env files (step 4).
- Run the daemon and `run.sh` on the same port simultaneously.
- Push code without `./scripts/test.sh` passing at 100%.
