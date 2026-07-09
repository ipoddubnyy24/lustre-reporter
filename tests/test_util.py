from datetime import date

from lustre_reporter import util


def test_parse_tickets_basic():
    assert util.parse_tickets("LU-20388 pcc: fix") == [
        {"key": "LU-20388", "project": "LU", "number": "20388"}]


def test_parse_tickets_multiple_and_dedup():
    keys = [d["key"] for d in util.parse_tickets("EX-14806 LU-1 kernel LU-1 x EX-14806")]
    assert keys == ["EX-14806", "LU-1"]  # order-preserving + deduped


def test_parse_tickets_all_prefixes():
    for p in ["LU", "EX", "DDN", "EHT", "GCP", "IME"]:
        assert util.parse_tickets(f"{p}-5 x")[0]["project"] == p


def test_parse_tickets_no_false_positives():
    assert util.parse_tickets("UTF-8 SHA-1 REX-9 build") == []
    assert util.parse_tickets("") == []
    assert util.parse_tickets(None) == []


def test_ticket_keys():
    assert util.ticket_keys("LU-1 EX-2 LU-1") == {"LU-1", "EX-2"}


def test_days_ago_iso():
    assert util.days_ago_iso(7, today=date(2026, 7, 9)) == "2026-07-02"
    assert util.days_ago_iso(0, today=date(2026, 7, 9)) == "2026-07-09"


def test_days_ago_iso_default_today():
    # exercises the `today or date.today()` default branch
    assert len(util.days_ago_iso(1)) == 10
