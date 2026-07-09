from datetime import datetime

from lustre_reporter import daily_report
from lustre_reporter.cli import ToolResult


def test_next_run_pt():
    assert daily_report.next_run_pt(9, datetime(2026, 7, 9, 8, 0)) == datetime(2026, 7, 9, 9, 0)
    assert daily_report.next_run_pt(9, datetime(2026, 7, 9, 10, 0)) == datetime(2026, 7, 10, 9, 0)


def test_trend_str():
    assert daily_report._trend_str([]) == "n/a"
    assert daily_report._trend_str([{"session_pass_rate": None}]) == "n/a"
    assert "↗" in daily_report._trend_str([{"session_pass_rate": 10}, {"session_pass_rate": 20}])
    assert "↘" in daily_report._trend_str([{"session_pass_rate": 20}, {"session_pass_rate": 10}])
    assert "→" in daily_report._trend_str([{"session_pass_rate": 20}, {"session_pass_rate": 20}])
    assert "50%" in daily_report._trend_str([{"session_pass_rate": 50}])  # single value


def _wire(monkeypatch, *, stability_ok=True, changelog_ok=True, patches=None):
    if stability_ok:
        monkeypatch.setattr(daily_report.maloo, "sessions",
                            lambda job, days=14, limit=500: ToolResult(
                                ok=True, data=[{"submission": "2026-07-09", "passed": 1,
                                                "failed": 0, "aborted": 0, "total": 1}]))
    else:
        monkeypatch.setattr(daily_report.maloo, "sessions",
                            lambda job, days=14, limit=500: ToolResult(ok=False, data=None,
                                                                       error="401", kind="auth"))

    def bc(clone, branch, max_builds=1, fetch_cfg=None):
        if not changelog_ok:
            return {"ok": False, "error": "no ref"}
        return {"ok": True, "latest_tag": "T", "unreleased": patches or [], "fetch_note": None}
    monkeypatch.setattr(daily_report.git_tags, "build_changelog", bc)


def test_build_report(monkeypatch, cfg):
    _wire(monkeypatch)
    rep = daily_report.build_report(cfg, days=7)
    assert rep["days"] == 7 and len(rep["branches"]) == 2
    assert rep["branches"][0]["stability"]["ok"] and rep["branches"][0]["landed"]["ok"]


def test_build_report_default_days(monkeypatch, cfg):
    _wire(monkeypatch)
    assert daily_report.build_report(cfg)["days"] == 14   # from cfg.slack.days


def test_render_mrkdwn_with_patches(monkeypatch, cfg):
    patches = [{"number": 100, "url": "http://p/100", "subject": "LU-1 kernel: x",
                "tickets": [{"key": "LU-1", "project": "LU"}]}]
    _wire(monkeypatch, patches=patches)
    txt = daily_report.render(daily_report.build_report(cfg), cfg, flavor="mrkdwn")
    assert "*Lustre daily report" in txt
    assert "<http://p/100|#100>" in txt and "jira.whamcloud.com/browse/LU-1" in txt
    assert "kernel: x" in txt and "Landed since T (1)" in txt


def test_render_md_unavailable_states(monkeypatch, cfg):
    _wire(monkeypatch, stability_ok=False, changelog_ok=False)
    txt = daily_report.render(daily_report.build_report(cfg), cfg, flavor="md")
    assert "**Lustre daily report" in txt and txt.count("unavailable") == 4  # 2 branches x 2


def test_render_md_with_patch(monkeypatch, cfg):
    patches = [{"number": 100, "url": "http://p/100", "subject": "LU-1 kernel: x",
                "tickets": [{"key": "LU-1", "project": "LU"}]}]
    _wire(monkeypatch, patches=patches)
    txt = daily_report.render(daily_report.build_report(cfg), cfg, flavor="md")
    assert "[#100](http://p/100)" in txt and "[LU-1](" in txt


def test_render_nothing_landed(monkeypatch, cfg):
    _wire(monkeypatch, patches=[])
    txt = daily_report.render(daily_report.build_report(cfg), cfg)
    assert "nothing yet" in txt


def test_render_truncates_patches(monkeypatch, cfg):
    patches = [{"number": i, "url": f"u{i}", "subject": f"LU-{i} x", "tickets": []} for i in range(20)]
    _wire(monkeypatch, patches=patches)
    txt = daily_report.render(daily_report.build_report(cfg), cfg)
    assert "and 5 more" in txt


def test_send_daily_not_configured(cfg):
    cfg.slack = {"enabled": False}
    assert daily_report.send_daily(cfg)["ok"] is False


def test_send_daily_ok(monkeypatch, cfg):
    cfg.slack = {"enabled": True, "webhook_url": "http://hook"}
    _wire(monkeypatch)
    monkeypatch.setattr(daily_report.slack, "post", lambda scfg, text: {"ok": True})
    assert daily_report.send_daily(cfg)["ok"] is True


def test_send_daily_error(monkeypatch, cfg):
    cfg.slack = {"enabled": True, "webhook_url": "http://hook"}
    _wire(monkeypatch)
    monkeypatch.setattr(daily_report.slack, "post", lambda scfg, text: {"ok": False, "error": "boom"})
    r = daily_report.send_daily(cfg)
    assert r["ok"] is False and r["error"] == "boom"
