"""Configuration for Lustre Reporter.

Sensible defaults are baked in so the app runs out of the box. Anything can
be overridden by dropping a ``config.local.json`` next to this package (it is
git-ignored) with the same shape as ``config.example.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
# Writable per-user location used when installed as a macOS .app bundle
# (the bundle's Resources dir is read-only). Overridable via env.
APP_SUPPORT = Path(
    os.environ.get("LUSTRE_REPORTER_HOME")
    or Path.home() / "Library" / "Application Support" / "Lustre Reporter"
)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9835


@dataclass(frozen=True)
class Branch:
    """An ExaScaler release branch we track and report on."""

    key: str  # short id used in the API/UI, e.g. "es6"
    label: str  # human label, e.g. "ExaScaler 6"
    gerrit_project: str  # e.g. "ex/lustre-release"
    gerrit_branch: str  # e.g. "b_es6_0"
    maloo_trigger_job: str  # Maloo trigger_job / Jenkins job, e.g. "lustre-b_es6_0"
    ping_name: str  # reviewer to ping for backports, e.g. "Li Xi"
    ping_email: str  # their address for the Teams deep link, e.g. "lixi@ddn.com"


@dataclass(frozen=True)
class MasterRepo:
    """A 'master' we scan for backport candidates."""

    key: str  # e.g. "community"
    label: str  # e.g. "Community master (fs/lustre-release)"
    gerrit_project: str  # e.g. "fs/lustre-release"
    gerrit_branch: str = "master"


@dataclass
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    # Web bases for building clickable links.
    gerrit_web_base: str = "https://review.whamcloud.com"
    # LU tickets live on the Whamcloud Jira; EX/DDN/etc. on the DDN cloud Jira.
    jira_lu_base: str = "https://jira.whamcloud.com/browse"
    jira_cloud_base: str = "https://ime-ddn.atlassian.net/browse"

    # Jira project prefixes that route to the DDN *cloud* instance (jira -I cloud).
    cloud_projects: tuple[str, ...] = ("EX", "DDN", "EHT", "GCP", "IME")

    branches: list[Branch] = field(
        default_factory=lambda: [
            Branch(
                key="es6",
                label="ExaScaler 6",
                gerrit_project="ex/lustre-release",
                gerrit_branch="b_es6_0",
                maloo_trigger_job="lustre-b_es6_0",
                ping_name="Li Xi",
                ping_email="lixi@ddn.com",
            ),
            Branch(
                key="es7",
                label="ExaScaler 7",
                gerrit_project="ex/lustre-release",
                gerrit_branch="b_es7_0",
                maloo_trigger_job="lustre-b_es7_0",
                ping_name="Marc-Andre Vef",
                ping_email="mvef@ddn.com",
            ),
        ]
    )

    masters: list[MasterRepo] = field(
        default_factory=lambda: [
            MasterRepo(
                key="community",
                label="Community master (fs/lustre-release)",
                gerrit_project="fs/lustre-release",
            ),
            MasterRepo(
                key="exa",
                label="ExaScaler master (ex/lustre-release)",
                gerrit_project="ex/lustre-release",
            ),
        ]
    )

    # How many days of master history to scan for backport candidates by default.
    backport_scan_days: int = 120
    # Cap on candidates enriched with a live Jira/commit lookup per request.
    enrich_limit: int = 60
    # Directory holding the self-signed TLS cert/key. Env override lets the
    # installed .app keep certs in a writable location outside the bundle.
    cert_dir: str = field(default_factory=lambda: (
        os.environ.get("LUSTRE_REPORTER_CERT_DIR") or str(REPO_ROOT / "certs")))
    # Local ex/lustre-release checkout, used to resolve each branch's most
    # recent release tag for the "since last tag" landed filter.
    lustre_clone: str = "~/work/src/lustre/lustre-release"

    # How to refresh the clone before reading tags — tried in order, then the
    # local copy as-is. Put a GitHub mirror URL (may use {branch}) in "remotes"
    # to pull from GitHub first; Gerrit HTTPS needs no SSH key.
    git_fetch: dict = field(default_factory=lambda: {
        "remotes": [],
        "use_gerrit_https": True,
        "use_origin": True,
    })

    # Auto-publish the per-branch "landed patches" QA changelog to Confluence
    # (twice daily at 00:00 / 12:00 America/Los_Angeles when run as the daemon).
    confluence: dict = field(default_factory=lambda: {
        "enabled": True,
        "auto_publish": True,
        "site": "https://ime-ddn.atlassian.net",
        "space_id": "1075183618",
        "parent_id": "3692101696",
        "title_template": "ExaScaler Landed Patches — {label} ({gerrit_branch})",
        "max_builds": 5,
    })

    # Daily Slack report (build-stability trend + landed-since-last-tag), posted
    # at slack.hour America/Los_Angeles. Provide a webhook_url, or bot_token+channel.
    slack: dict = field(default_factory=lambda: {
        "enabled": False,
        "webhook_url": "",
        "bot_token": "",
        "channel": "",
        "hour": 9,
        "days": 14,
    })

    # EMF (EXAScaler Management Framework) reporting — GitHub + Jira driven.
    # Build stability from a GitHub Actions workflow; "landed" from CalVer
    # GitHub releases; "coming" forecast from EX Jira items + fixVersion dates.
    emf: dict = field(default_factory=lambda: {
        "enabled": True,
        "repo": "whamcloud/exascaler-management-framework",
        "release_branch": "6.3.8",
        "nightly_workflow": "nightly-build-6_3_x.yml",
        "stability_days": 30,
        "jira_project": "EX",
        # Upcoming fixVersions to forecast; empty => auto (unreleased EX versions
        # that carry a date no more than `coming_grace_days` in the past — this
        # drops ancient never-closed versions like 2018 "ES5.0").
        "track_versions": [],
        "coming_grace_days": 30,
        # P(item lands in its target release) by days-to-release band × status
        # tier. First band whose max_days >= days_remaining wins (overdue => 0).
        "risk_bands": [
            {"max_days": 0, "todo": 0.02, "progress": 0.30, "review": 0.75},
            {"max_days": 4, "todo": 0.05, "progress": 0.45, "review": 0.85},
            {"max_days": 10, "todo": 0.10, "progress": 0.60, "review": 0.90},
            {"max_days": 30, "todo": 0.35, "progress": 0.75, "review": 0.92},
            {"max_days": 9999, "todo": 0.60, "progress": 0.85, "review": 0.95},
        ],
        # Jira status name -> tier used by risk_bands (else falls back by category).
        "status_tiers": {
            "review": ["In Review", "Awaiting Verification", "Test"],
            "progress": ["In Progress"],
            "todo": ["To Do", "Open", "Reopened", "Need Information", "Blocked External"],
        },
    })

    def branch(self, key: str) -> Branch:
        for b in self.branches:
            if b.key == key:
                return b
        raise KeyError(f"unknown branch key: {key!r}")

    def jira_browse_base(self, project_prefix: str) -> str:
        """Return the correct Jira browse base for a project prefix."""
        return (
            self.jira_cloud_base
            if project_prefix.upper() in self.cloud_projects
            else self.jira_lu_base
        )

    def is_cloud_project(self, project_prefix: str) -> bool:
        return project_prefix.upper() in self.cloud_projects


_OVERRIDE_SCALARS = ("host", "port", "gerrit_web_base", "jira_lu_base",
                     "jira_cloud_base", "backport_scan_days", "enrich_limit",
                     "cert_dir", "lustre_clone")


def _apply_overrides(cfg: Config, data: dict[str, Any]) -> None:
    """Shallow-merge simple scalar overrides; rebuild list-of-dataclass fields."""
    for key in _OVERRIDE_SCALARS:
        if key in data:
            setattr(cfg, key, data[key])
    if "cloud_projects" in data:
        cfg.cloud_projects = tuple(data["cloud_projects"])
    if "branches" in data:
        cfg.branches = [Branch(**b) for b in data["branches"]]
    if "masters" in data:
        cfg.masters = [MasterRepo(**m) for m in data["masters"]]
    if isinstance(data.get("git_fetch"), dict):
        cfg.git_fetch.update(data["git_fetch"])
    if isinstance(data.get("confluence"), dict):
        cfg.confluence.update(data["confluence"])
    if isinstance(data.get("slack"), dict):
        cfg.slack.update(data["slack"])
    if isinstance(data.get("emf"), dict):
        cfg.emf.update(data["emf"])


def _config_candidates() -> list[Path]:
    """config.local.json search order: explicit env, source tree, then the
    per-user Application Support dir (used by the installed app)."""
    paths: list[Path] = []
    env = os.environ.get("LUSTRE_REPORTER_CONFIG")
    if env:
        paths.append(Path(env))
    paths.append(REPO_ROOT / "config.local.json")
    paths.append(APP_SUPPORT / "config.local.json")
    return paths


def load_config() -> Config:
    cfg = Config()
    for path in _config_candidates():
        if path.exists():
            try:
                _apply_overrides(cfg, json.loads(path.read_text()))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise SystemExit(f"Invalid {path}: {exc}") from exc
            break
    return cfg
