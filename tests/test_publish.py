from datetime import datetime

from lustre_reporter import publish
from lustre_reporter.sources.confluence import ConfluenceError


def test_esc_and_strip():
    assert publish._esc("<a>&\"'") == "&lt;a&gt;&amp;&quot;&#x27;"
    assert publish._esc(None) == ""
    assert publish._strip_ticket("LU-1 RM-2 kernel: x") == "kernel: x"


def test_ticket_and_patch_cells(cfg):
    assert publish._ticket_cell(cfg, []) == "—"
    cell = publish._ticket_cell(cfg, [{"key": "LU-1", "project": "LU"}, {"key": "EX-2", "project": "EX"}])
    assert "jira.whamcloud.com/browse/LU-1" in cell and "ime-ddn.atlassian.net/browse/EX-2" in cell
    assert publish._patch_cell({"number": 5, "url": "http://p/5"}) == '<a href="http://p/5">#5</a>'
    assert publish._patch_cell({"number": 5}) == "#5"
    assert publish._patch_cell({}) == "—"


def test_areas_line_and_table(cfg):
    assert publish._areas_line([]) == ""
    assert "kernel ×2" in publish._areas_line([["kernel", 2]])
    assert "None." in publish._table(cfg, [])
    t = publish._table(cfg, [{"number": 1, "url": "http://p/1", "subject": "LU-1 kernel: a",
                              "owner": "Al", "date": "2026-07-09", "tickets": [{"key": "LU-1", "project": "LU"}]}])
    assert "<table>" in t and "kernel: a" in t and "Al" in t


def test_next_update_pt():
    assert publish.next_update_pt(datetime(2026, 7, 9, 10, 0)) == datetime(2026, 7, 9, 12, 0)
    assert publish.next_update_pt(datetime(2026, 7, 9, 15, 0)) == datetime(2026, 7, 10, 0, 0)


def test_now_pt_returns_datetime():
    assert isinstance(publish.now_pt(), datetime)


def test_page_title(cfg):
    t = publish._page_title({"title_template": "LR — {label} ({gerrit_branch})"}, cfg.branches[0])
    assert t == "LR — ExaScaler 6 (b_es6_0)"
    # default template
    assert "ExaScaler 6" in publish._page_title({}, cfg.branches[0])


CL = {
    "ok": True, "latest_tag": "T3", "latest_date": "2026-07-09",
    "unreleased": [{"number": 9, "url": "http://p/9", "subject": "LU-9 pcc: z", "owner": "o",
                    "date": "2026-07-08", "tickets": [{"key": "LU-9", "project": "LU"}]}],
    "unreleased_count": 1, "unreleased_areas": [["pcc", 1]],
    "builds": [
        {"tag": "T3", "prev": "T2", "date": "2026-07-09", "count": 1, "areas": [["kernel", 1]],
         "patches": [{"number": 1, "url": "http://p/1", "subject": "LU-1 kernel: a", "owner": "o",
                      "date": "2026-07-09", "tickets": [{"key": "LU-1", "project": "LU"}]}]},
        {"tag": "T2", "prev": "T1", "date": "2026-07-01", "count": 0, "areas": [], "patches": []},
    ],
    "fetch_note": None,
}


def test_build_page_html(cfg):
    html = publish.build_page_html(cfg, cfg.branches[0], CL, now=datetime(2026, 7, 9, 10, 0))
    assert "In build T3 (1)" in html
    assert "test this" not in html
    assert "Coming next — since T3 (1)" in html
    assert 'ac:name="info"' in html and 'ac:name="expand"' in html
    assert "Areas touched" in html and "browse/LU-1" in html and "http://p/1" in html
    assert "Updated 2026-07-09 10:00 PT" in html


def test_build_page_html_no_tags_and_note(cfg):
    cl = {"builds": [], "fetch_note": "⚠ stale", "latest_tag": "T",
          "unreleased": [], "unreleased_count": 0, "unreleased_areas": []}
    h = publish.build_page_html(cfg, cfg.branches[0], cl, now=datetime(2026, 7, 9, 10, 0))
    assert "No tags found" in h and "stale" in h


def test_publish_all_disabled(cfg):
    cfg.confluence = {"enabled": False}
    r = publish.publish_all(cfg)
    assert r["ok"] is False and "disabled" in r["error"]


def test_publish_all_no_space(cfg):
    cfg.confluence = {"enabled": True}
    r = publish.publish_all(cfg)
    assert r["ok"] is False and "space_id" in r["error"]


def test_publish_all_client_error(monkeypatch, cfg):
    cfg.confluence = {"enabled": True, "space_id": "1"}

    def raising(site=None):
        raise ConfluenceError("no creds")
    monkeypatch.setattr(publish, "Confluence", raising)
    r = publish.publish_all(cfg)
    assert r["ok"] is False and "no creds" in r["error"]


def _one_build_cl(ok=True):
    if not ok:
        return {"ok": False, "error": "no ref"}
    return {"ok": True, "latest_tag": "T3", "latest_date": "d", "unreleased": [],
            "unreleased_count": 0, "unreleased_areas": [],
            "builds": [{"tag": "T3", "prev": None, "date": "d", "count": 0, "areas": [], "patches": []}],
            "fetch_note": None}


def test_publish_all_mixed(monkeypatch, cfg):
    cfg.confluence = {"enabled": True, "space_id": "1", "parent_id": "2",
                      "max_builds": 5, "title_template": "T {label}"}
    monkeypatch.setattr(publish.git_tags, "build_changelog",
                        lambda clone, branch, max_builds=5, fetch_cfg=None:
                        _one_build_cl(branch == "b_es6_0"))

    class FakeClient:
        def __init__(self, *a):
            pass

        def upsert(self, space, parent, title, html):
            return {"action": "created", "id": "9", "url": "http://c/9"}
    monkeypatch.setattr(publish, "Confluence", FakeClient)
    r = publish.publish_all(cfg)
    by = {x["branch"]: x for x in r["results"]}
    assert r["ok"] is False                                  # es7 failed
    assert by["es6"]["ok"] is True and by["es6"]["action"] == "created"
    assert by["es7"]["ok"] is False and "no ref" in by["es7"]["error"]


def test_publish_all_upsert_error(monkeypatch, cfg):
    cfg.confluence = {"enabled": True, "space_id": "1"}
    monkeypatch.setattr(publish.git_tags, "build_changelog",
                        lambda *a, **k: _one_build_cl(True))

    class FakeClient:
        def __init__(self, *a):
            pass

        def upsert(self, *a):
            raise ConfluenceError("boom")
    monkeypatch.setattr(publish, "Confluence", FakeClient)
    r = publish.publish_all(cfg)
    assert r["ok"] is False and "boom" in r["results"][0]["error"]
