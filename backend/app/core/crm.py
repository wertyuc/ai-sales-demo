"""CRM controller: funnel stage, deal direction and lead quality (§4, §41).

The AI does not "choose a stage" in free text — the stage is derived from the
structured state, so the Kanban board can never drift away from what was
actually agreed in the chat.
"""
from __future__ import annotations

from .qualification import geo_zone

DELIVERY_SIGNALS = ("delivery_intent",)
PICKUP_SIGNALS = ("pickup_intent", "address_request")


def derive_direction(lead, stats: dict, signals: set[str]) -> str:
    zone = stats.get("zone") or geo_zone(lead.qualification or {})
    if zone == "region":
        return "delivery_region"
    if zone in ("msk", "mo"):
        if lead.meeting_scheduled or any(s in signals for s in PICKUP_SIGNALS):
            return "office"
        if any(s in signals for s in DELIVERY_SIGNALS):
            return "delivery_msk"
        return lead.direction if lead.direction != "none" else "office"
    if any(s in signals for s in DELIVERY_SIGNALS):
        return "delivery_msk"
    return lead.direction


def derive_stage(lead, stats: dict) -> str:
    if lead.sold:
        return "deal"
    if lead.lost:
        return "lost"

    timeframe = (lead.qualification or {}).get("timeframe", {}).get("value")
    qualified = stats.get("qualified")

    if lead.meeting_scheduled or timeframe in ("today", "tomorrow", "3days"):
        if qualified or lead.meeting_scheduled:
            return "arrives_1_3_days"
    if timeframe in ("week", "2weeks") and qualified:
        return "arrives_1_2_weeks"
    if stats.get("closed_count", 0) >= 1:
        return "qualification"
    return "new"


def classify_quality(lead, stats: dict) -> str:
    """§41 — explicit, reproducible definitions so the daily report is stable."""
    if lead.negative:
        return "negative"
    if lead.ignored:
        return "ignored"
    if stats.get("closed_count", 0) >= 4 and lead.contact_acquired:
        return "quality"
    if stats.get("qualified"):
        return "qualified"
    if stats.get("closed_count", 0) == 0:
        return "pending"
    return "poor"


QUALITY_LABELS = {
    "quality": "Качественная",
    "qualified": "Квалифицированная",
    "poor": "Некачественная",
    "negative": "Негатив",
    "ignored": "Игнор",
    "pending": "В работе",
}


def apply(lead, stats: dict, signals: set[str]) -> list[dict]:
    """Recompute derived CRM fields; returns the list of mutations for the log."""
    mutations: list[dict] = []

    new_direction = derive_direction(lead, stats, signals)
    if new_direction and new_direction != lead.direction:
        mutations.append({"field": "direction", "from": lead.direction, "to": new_direction})
        lead.direction = new_direction

    new_stage = derive_stage(lead, stats)
    if new_stage != lead.stage:
        mutations.append({"field": "stage", "from": lead.stage, "to": new_stage})
        lead.stage = new_stage

    new_quality = classify_quality(lead, stats)
    if new_quality != lead.quality:
        mutations.append({"field": "quality", "from": lead.quality, "to": new_quality})
        lead.quality = new_quality

    if lead.score != stats.get("score", lead.score):
        mutations.append({"field": "score", "from": lead.score, "to": stats["score"]})
        lead.score = stats["score"]

    if lead.closed_count != stats.get("closed_count", lead.closed_count):
        mutations.append(
            {"field": "closed_count", "from": lead.closed_count, "to": stats["closed_count"]}
        )
        lead.closed_count = stats["closed_count"]

    return mutations
