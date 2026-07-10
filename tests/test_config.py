import json

import pytest

from lustre_reporter import config as cfgmod
from lustre_reporter.config import Config, load_config


def test_defaults_and_branch_lookup():
    c = Config()
    assert [b.key for b in c.branches] == ["es6", "es7"]
    assert c.branch("es7").gerrit_branch == "b_es7_0"
    with pytest.raises(KeyError):
        c.branch("nope")


def test_cloud_routing_case_insensitive():
    c = Config()
    assert c.is_cloud_project("EX") and c.is_cloud_project("ddn")
    assert not c.is_cloud_project("LU")
    assert c.jira_browse_base("DDN") == c.jira_cloud_base
    assert c.jira_browse_base("LU") == c.jira_lu_base


def test_cert_dir_env_override(monkeypatch):
    monkeypatch.setenv("LUSTRE_REPORTER_CERT_DIR", "/tmp/certz")
    assert Config().cert_dir == "/tmp/certz"


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("LUSTRE_REPORTER_CONFIG", raising=False)
    monkeypatch.setattr(cfgmod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfgmod, "APP_SUPPORT", tmp_path / "absent")
    assert load_config().port == 9835


def test_load_config_overrides(monkeypatch, tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "port": 9999,
        "backport_scan_days": 50,
        "lustre_clone": "/somewhere",
        "cloud_projects": ["FOO"],
        "branches": [{"key": "esX", "label": "X", "gerrit_project": "p",
                      "gerrit_branch": "b", "maloo_trigger_job": "j",
                      "ping_name": "N", "ping_email": "e"}],
        "masters": [{"key": "m", "label": "M", "gerrit_project": "pm"}],
        "git_fetch": {"use_origin": False, "remotes": ["gh://{branch}"]},
        "confluence": {"enabled": False},
        "slack": {"enabled": True, "webhook_url": "http://hook"},
        "emf": {"enabled": False, "release_branch": "7.0.0"},
    }))
    monkeypatch.setenv("LUSTRE_REPORTER_CONFIG", str(p))
    c = load_config()
    assert c.port == 9999 and c.backport_scan_days == 50 and c.lustre_clone == "/somewhere"
    assert c.cloud_projects == ("FOO",)
    assert [b.key for b in c.branches] == ["esX"]
    assert [m.key for m in c.masters] == ["m"]
    # dict fields merge (unspecified keys keep defaults)
    assert c.git_fetch["use_origin"] is False and c.git_fetch["use_gerrit_https"] is True
    assert c.git_fetch["remotes"] == ["gh://{branch}"]
    assert c.confluence["enabled"] is False and c.confluence["space_id"] == "1075183618"
    assert c.slack["enabled"] is True and c.slack["webhook_url"] == "http://hook"
    assert c.slack["hour"] == 9  # unspecified key keeps default
    assert c.emf["enabled"] is False and c.emf["release_branch"] == "7.0.0"
    assert c.emf["jira_project"] == "EX"  # unspecified key keeps default
    assert c.emf["confluence"]["space_id"] == "1075183618"  # nested defaults kept
    assert [ln["key"] for ln in c.emf["release_lines"]] == ["main", "gcp"]


def test_load_config_invalid_json(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not valid")
    monkeypatch.setenv("LUSTRE_REPORTER_CONFIG", str(p))
    with pytest.raises(SystemExit):
        load_config()


def test_config_candidates_env_first(monkeypatch):
    monkeypatch.setenv("LUSTRE_REPORTER_CONFIG", "/x/y.json")
    assert str(cfgmod._config_candidates()[0]) == "/x/y.json"


def test_load_config_scalar_only(monkeypatch, tmp_path):
    # only a scalar override -> the list/dict fields keep defaults (false arcs)
    p = tmp_path / "c.json"
    p.write_text('{"port": 1234}')
    monkeypatch.setenv("LUSTRE_REPORTER_CONFIG", str(p))
    c = load_config()
    assert c.port == 1234 and [b.key for b in c.branches] == ["es6", "es7"]
    assert c.cloud_projects == ("EX", "DDN", "EHT", "GCP", "IME")
