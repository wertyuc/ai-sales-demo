"""State-based qualification engine.

The qualification state is stored on the Lead as structured JSON and updated
incrementally.  The LLM never has to re-derive it from the transcript, and the
percentage formula is configuration, not a constant baked into a prompt.
"""
from __future__ import annotations

from typing import Any

from .extractor import TASK_LABELS, Extraction

FIELD_LABELS = {
    "budget": "Бюджет",
    "geo": "География",
    "timeframe": "Срок покупки",
    "tasks": "Задачи",
    "requirements": "Бренд / характеристики",
    "recipient": "Кому покупает",
}

TIMEFRAME_LABELS = {
    "today": "сегодня",
    "tomorrow": "завтра",
    "3days": "1-3 дня",
    "week": "на этой неделе",
    "2weeks": "1-2 недели",
    "later": "позже",
}

ZONE_LABELS = {"msk": "Москва", "mo": "Московская область", "region": "Регион"}


def merge(qualification: dict[str, Any], extraction: Extraction) -> list[str]:
    """Fold newly extracted fields into the stored state. Returns changed keys."""
    changed: list[str] = []
    for key, payload in extraction.fields.items():
        existing = qualification.get(key)
        if existing and existing.get("value") == payload.get("value"):
            continue
        if key == "tasks" and existing:
            merged = sorted(set(existing.get("value") or []) | set(payload.get("value") or []))
            if merged == sorted(existing.get("value") or []):
                continue
            payload = dict(payload)
            payload["value"] = merged
            payload["raw"] = ", ".join(TASK_LABELS.get(t, t) for t in merged)
        if key == "requirements" and existing:
            merged_req = dict(existing.get("value") or {})
            incoming = payload.get("value") or {}
            specs = list(dict.fromkeys((merged_req.get("specs") or []) + (incoming.get("specs") or [])))
            merged_req.update({k: v for k, v in incoming.items() if k != "specs"})
            if specs:
                merged_req["specs"] = specs
            payload = dict(payload)
            payload["value"] = merged_req
            bits = []
            if merged_req.get("brand"):
                bits.append(merged_req["brand"])
            bits.extend(merged_req.get("specs") or [])
            payload["raw"] = ", ".join(bits)
        qualification[key] = payload
        changed.append(key)
    return changed


def enabled_fields(config: dict) -> list[dict]:
    return [f for f in config.get("fields", []) if f.get("enabled", True)]


def compute(qualification: dict, config: dict) -> dict:
    """Score the current state against the configured formula."""
    fields = enabled_fields(config)
    keys = [f["key"] for f in fields]
    closed = [k for k in keys if _is_closed(qualification.get(k))]
    missing = [k for k in keys if k not in closed]

    if config.get("formula") == "ratio" or not fields:
        score = round(len(closed) / len(keys) * 100) if keys else 0
    else:
        total_weight = sum(f.get("weight", 0) for f in fields) or 1
        got = sum(f.get("weight", 0) for f in fields if f["key"] in closed)
        score = round(got / total_weight * 100)

    zone = geo_zone(qualification)
    return {
        "score": score,
        "closed": closed,
        "missing": missing,
        "closed_count": len(closed),
        "total": len(keys),
        "qualified": len(closed) >= int(config.get("qualified_min_fields", 3)),
        "over_threshold": score >= int(config.get("handoff_threshold", 80)),
        "region_rule": (
            zone == "region" and len(closed) >= int(config.get("region_min_fields", 4))
        ),
        "zone": zone,
    }


def _is_closed(entry: Any) -> bool:
    if not entry:
        return False
    value = entry.get("value") if isinstance(entry, dict) else entry
    if value in (None, "", [], {}):
        return False
    return True


def geo_zone(qualification: dict) -> str | None:
    geo = qualification.get("geo")
    if not geo:
        return None
    value = geo.get("value") or {}
    return value.get("zone") if isinstance(value, dict) else None


def geo_city(qualification: dict) -> str:
    geo = qualification.get("geo")
    if not geo:
        return ""
    value = geo.get("value") or {}
    return value.get("city", "") if isinstance(value, dict) else str(value)


def budget_value(qualification: dict) -> int | None:
    entry = qualification.get("budget")
    if not entry:
        return None
    value = entry.get("value")
    return int(value) if isinstance(value, (int, float)) else None


def tasks_list(qualification: dict) -> list[str]:
    entry = qualification.get("tasks")
    if not entry:
        return []
    value = entry.get("value")
    return list(value) if isinstance(value, list) else []


def requirements_dict(qualification: dict) -> dict:
    entry = qualification.get("requirements")
    if not entry:
        return {}
    value = entry.get("value")
    return dict(value) if isinstance(value, dict) else {}


def recipient_info(qualification: dict) -> dict:
    entry = qualification.get("recipient")
    if not entry:
        return {}
    value = entry.get("value")
    return dict(value) if isinstance(value, dict) else {}


def is_gift(qualification: dict) -> bool:
    return recipient_info(qualification).get("type") == "gift"


def humanize(qualification: dict) -> dict[str, str]:
    """Human-readable one-liners for the Live Intelligence panel."""
    out: dict[str, str] = {}
    for key in FIELD_LABELS:
        entry = qualification.get(key)
        if not _is_closed(entry):
            out[key] = ""
            continue
        value = entry.get("value")
        if key == "budget":
            # a ceiling, not an offer price — the "ОТ" rule applies to products
            out[key] = "до {} ₽".format(f"{int(value):,}".replace(",", " "))
        elif key == "geo":
            out[key] = value.get("city") or ZONE_LABELS.get(value.get("zone"), "")
        elif key == "timeframe":
            out[key] = TIMEFRAME_LABELS.get(value, str(value))
        elif key == "tasks":
            out[key] = ", ".join(TASK_LABELS.get(t, t) for t in value)
        elif key == "requirements":
            bits = []
            if value.get("brand"):
                bits.append(value["brand"])
            bits.extend(value.get("specs") or [])
            out[key] = ", ".join(bits)
        elif key == "recipient":
            if value.get("type") == "gift":
                out[key] = f"подарок {value.get('who', '')}".strip()
            else:
                out[key] = "себе"
        else:
            out[key] = str(value)
    return out


def missing_questions(missing: list[str], qualification: dict) -> list[str]:
    """The §18 question bank, minus everything already answered."""
    bank = {
        "tasks": "Под какие задачи подбираете — игры, работа, учёба?",
        "budget": "На какой бюджет ориентируетесь?",
        "geo": "Вы в Москве или нужна доставка в регион?",
        "timeframe": "Когда планируете покупку?",
        "requirements": "Есть предпочтения по бренду или характеристикам?",
        "recipient": "Себе подбираете или в подарок?",
    }
    return [bank[k] for k in missing if k in bank]


def next_best_action(lead_state: dict) -> str:
    """One concrete recommendation for the Live Intelligence panel."""
    qual = lead_state["qualification"]
    stats = lead_state["stats"]
    if lead_state.get("handoff_required"):
        return "Передать менеджеру: " + (lead_state.get("handoff_reason") or "по правилу")
    if not lead_state.get("contact_phone") and stats["score"] >= 60:
        return "Получить контакт и назначить встречу"
    if stats["zone"] in ("msk", "mo") and stats["score"] >= 50 and not lead_state.get("meeting"):
        return "Пригласить в офис и согласовать время визита"
    if stats["zone"] == "region" and stats["closed_count"] >= 3:
        return "Уточнить детали доставки и передать менеджеру"
    if stats["missing"]:
        first = stats["missing"][0]
        return f"Закрыть параметр: {FIELD_LABELS.get(first, first)}"
    if not lead_state.get("selected_products"):
        return "Предложить 2-3 варианта из наличия"
    return "Довести до встречи или доставки"
