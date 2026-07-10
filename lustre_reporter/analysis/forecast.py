"""Risk-weighted "what's coming" forecast for an upcoming EMF release.

Each open work item (a Jira issue) has a status; each release has a date. The
probability an item lands in its release depends on how advanced it is (status
tier: review > progress > todo) and how much runway remains (days-to-release
band). Summing those probabilities gives an expected landing count per release.

Bands and tiers are config (``cfg.emf.risk_bands`` / ``status_tiers``); the
defaults encode the user's rule for the 5–10-day window and taper either side.
"""

from __future__ import annotations

from datetime import date


def days_until(release_date: object, *, today: date | None = None) -> int | None:
    """Whole days from today to an ISO release date; None if missing/unparseable."""
    if not release_date:
        return None
    try:
        rd = date.fromisoformat(str(release_date)[:10])
    except ValueError:
        return None
    return (rd - (today or date.today())).days


def band_for(days: int, bands: list[dict]) -> dict | None:
    """First band whose ``max_days`` >= ``days`` (ascending); last band otherwise."""
    ordered = sorted(bands, key=lambda b: b["max_days"])
    for b in ordered:
        if days <= b["max_days"]:
            return b
    return ordered[-1] if ordered else None


def tier_for(status: object, tiers: dict) -> str | None:
    """Map a Jira status name to a risk tier key, or None if unmapped."""
    if not status:
        return None
    low = str(status).strip().lower()
    for tier, names in tiers.items():
        if any(low == str(n).lower() for n in names):
            return tier
    return None


def score_item(status: object, days: int | None, *, bands: list[dict], tiers: dict) -> float | None:
    """Probability (0..1) an item in ``status`` lands with ``days`` of runway."""
    tier = tier_for(status, tiers)
    if tier is None or days is None:
        return None
    band = band_for(days, bands)
    return band.get(tier) if band else None


def forecast(items: list[dict], release_date: object, *,
             bands: list[dict], tiers: dict, today: date | None = None) -> dict:
    """Bucket items by tier and sum landing probabilities for one release.

    Returns {release_date, days, total, scored, expected, tiers{tier:{count,expected}},
    items[]} where each item gains ``tier`` and ``probability`` fields.
    """
    days = days_until(release_date, today=today)
    groups: dict[str, list] = {"review": [], "progress": [], "todo": [], "other": []}
    out_items = []
    expected = 0.0
    for it in items:
        tier = tier_for(it.get("status"), tiers) or "other"
        prob = score_item(it.get("status"), days, bands=bands, tiers=tiers)
        row = {**it, "tier": tier, "probability": prob}
        out_items.append(row)
        groups[tier].append(row)
        if prob is not None:
            expected += prob
    out_items.sort(key=lambda r: (r["probability"] is None, -(r["probability"] or 0)))
    tier_summary = {
        t: {"count": len(rows),
            "expected": round(sum(r["probability"] for r in rows
                                  if r["probability"] is not None), 2)}
        for t, rows in groups.items()
    }
    scored = [r for r in out_items if r["probability"] is not None]
    return {
        "release_date": (str(release_date)[:10] if release_date else None),
        "days": days,
        "total": len(items),
        "scored": len(scored),
        "expected": round(expected, 1),
        "tiers": tier_summary,
        "items": out_items,
    }
