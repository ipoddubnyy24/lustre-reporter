from datetime import date

from lustre_reporter.analysis import forecast

BANDS = [
    {"max_days": 0, "todo": 0.02, "progress": 0.30, "review": 0.75},
    {"max_days": 4, "todo": 0.05, "progress": 0.45, "review": 0.85},
    {"max_days": 10, "todo": 0.10, "progress": 0.60, "review": 0.90},
    {"max_days": 30, "todo": 0.35, "progress": 0.75, "review": 0.92},
    {"max_days": 9999, "todo": 0.60, "progress": 0.85, "review": 0.95},
]
TIERS = {"review": ["In Review", "Awaiting Verification"], "progress": ["In Progress"],
         "todo": ["To Do", "Open"]}


def test_days_until():
    assert forecast.days_until("2026-07-20", today=date(2026, 7, 10)) == 10
    assert forecast.days_until("2026-07-05", today=date(2026, 7, 10)) == -5
    assert forecast.days_until("2026-09-04T00:00:00", today=date(2026, 7, 10)) == 56
    assert forecast.days_until(None) is None
    assert forecast.days_until("not-a-date") is None


def test_days_until_default_today():
    assert isinstance(forecast.days_until("2099-01-01"), int)


def test_band_for():
    assert forecast.band_for(-3, BANDS)["max_days"] == 0
    assert forecast.band_for(0, BANDS)["max_days"] == 0
    assert forecast.band_for(4, BANDS)["max_days"] == 4
    assert forecast.band_for(5, BANDS)["max_days"] == 10
    assert forecast.band_for(10, BANDS)["max_days"] == 10
    assert forecast.band_for(11, BANDS)["max_days"] == 30
    assert forecast.band_for(500, BANDS)["max_days"] == 9999
    assert forecast.band_for(5, []) is None


def test_tier_for():
    assert forecast.tier_for("In Review", TIERS) == "review"
    assert forecast.tier_for("in progress", TIERS) == "progress"   # case-insensitive
    assert forecast.tier_for("To Do", TIERS) == "todo"
    assert forecast.tier_for("Done", TIERS) is None
    assert forecast.tier_for(None, TIERS) is None


def test_score_item():
    assert forecast.score_item("In Review", 7, bands=BANDS, tiers=TIERS) == 0.90
    assert forecast.score_item("To Do", -1, bands=BANDS, tiers=TIERS) == 0.02
    assert forecast.score_item("Done", 7, bands=BANDS, tiers=TIERS) is None       # unmapped
    assert forecast.score_item("In Review", None, bands=BANDS, tiers=TIERS) is None  # no date
    assert forecast.score_item("In Review", 7, bands=[], tiers=TIERS) is None     # no band


def test_forecast():
    items = [
        {"key": "EX-1", "status": "In Review"},
        {"key": "EX-2", "status": "In Progress"},
        {"key": "EX-3", "status": "To Do"},
        {"key": "EX-4", "status": "Done"},   # unmapped -> "other", no probability
    ]
    fc = forecast.forecast(items, "2026-07-17", bands=BANDS, tiers=TIERS, today=date(2026, 7, 10))
    assert fc["days"] == 7 and fc["total"] == 4 and fc["scored"] == 3
    assert fc["expected"] == 1.6                              # 0.90 + 0.60 + 0.10
    assert fc["release_date"] == "2026-07-17"
    assert fc["tiers"]["review"] == {"count": 1, "expected": 0.9}
    assert fc["tiers"]["other"]["count"] == 1
    assert fc["items"][0]["key"] == "EX-1"                    # sorted by probability desc
    assert fc["items"][-1]["probability"] is None            # unscored last


def test_forecast_no_date():
    fc = forecast.forecast([{"key": "X", "status": "In Review"}], None, bands=BANDS, tiers=TIERS)
    assert fc["days"] is None and fc["scored"] == 0 and fc["expected"] == 0.0
    assert fc["release_date"] is None
