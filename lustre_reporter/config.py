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


def _apply_overrides(cfg: Config, data: dict[str, Any]) -> None:
    """Shallow-merge simple scalar overrides; rebuild list-of-dataclass fields."""
    for key in ("host", "port", "gerrit_web_base", "jira_lu_base",
                "jira_cloud_base", "backport_scan_days", "enrich_limit",
                "cert_dir", "lustre_clone"):
        if key in data:
            setattr(cfg, key, data[key])
    if "cloud_projects" in data:
        cfg.cloud_projects = tuple(data["cloud_projects"])
    if "branches" in data:
        cfg.branches = [Branch(**b) for b in data["branches"]]
    if "masters" in data:
        cfg.masters = [MasterRepo(**m) for m in data["masters"]]


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
