from urllib.parse import unquote

from lustre_reporter.sources import teams


def test_backport_message_with_tickets():
    m = teams.backport_message("Li Xi", "b_es6_0", "LU-1 pcc: fix",
                               "http://p/1", ["LU-1 http://j/LU-1"])
    assert "Hi Li Xi, please consider this patch for backport to b_es6_0" in m
    assert "LU-1 pcc: fix" in m
    assert "http://p/1" in m
    assert "Ticket: LU-1 http://j/LU-1" in m
    assert m.rstrip().endswith("Thanks!")


def test_backport_message_no_tickets_no_name():
    m = teams.backport_message("", "b_es7_0", "subj", "url", [])
    assert m.startswith("Hi there, ")
    assert "Ticket:" not in m


def test_compose_urls_and_encoding():
    r = teams.compose("a@b.com", "Name", "b_es6_0", "subj", "http://p/1", ["LU-1 http://j"])
    assert r["reviewer"] == "Name" and r["email"] == "a@b.com"
    assert r["teams_url"].startswith(
        "https://teams.microsoft.com/l/chat/0/0?users=a%40b.com&message=")
    assert r["mailto_url"].startswith("mailto:a@b.com?subject=")
    message_enc = r["teams_url"].split("&message=", 1)[1]
    assert "backport to b_es6_0" in unquote(message_enc)
