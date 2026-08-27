"""Runtime-editable business rules (the Control Center store).

Nothing in the pipeline hardcodes a threshold: every number below is read from
the database at the moment it is needed, so changing a rule in the UI changes AI
behaviour on the very next message without a redeploy.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, Setting

# --- defaults ---------------------------------------------------------------
# Values come straight from the specification (§5.1, §6, §12, §13, §28, §29).

DEFAULTS: dict[str, dict[str, Any]] = {
    "qualification": {
        "fields": [
            {"key": "budget", "label": "Бюджет", "weight": 20, "enabled": True},
            {"key": "geo", "label": "География", "weight": 20, "enabled": True},
            {"key": "timeframe", "label": "Срок покупки", "weight": 15, "enabled": True},
            {"key": "tasks", "label": "Задачи", "weight": 20, "enabled": True},
            {"key": "requirements", "label": "Бренд / характеристики", "weight": 15, "enabled": True},
            {"key": "recipient", "label": "Кому покупает", "weight": 10, "enabled": True},
        ],
        # "weighted" uses the weights above; "ratio" is closed/total*100
        "formula": "weighted",
        "qualified_min_fields": 3,
        "handoff_threshold": 80,
        "region_min_fields": 4,
        "partial_counts": False,
    },
    "handoff": {
        "negative": True,
        "phone_request": True,
        "ai_suspicion": True,
        "region_rule": True,
        "photo_video": True,
        "qualification_threshold": True,
        "service_questions": True,
        "ai_silence_minutes": 30,
        "task_deadline_minutes": 5,
        "task_title": "Связаться с клиентом",
    },
    "followup": {
        "enabled": True,
        "require_read": True,
        "first_delay_minutes": 15,
        "second_delay_minutes": 60,
        "evening_hour": 19,
        "max_touches_per_day": 1,
        "max_unread_touches": 2,
        "windows": ["12:30-14:30", "17:00-20:00"],
        "respect_windows_from_attempt": 2,
    },
    "meeting": {
        "reminder_day_before": True,
        "reminder_morning_hour": 9,
        "reminder_hours_before": 1,
        "office_open": "10:00",
        "office_close": "21:00",
    },
    "ai_style": {
        "verbosity": "short",  # short | detailed
        "tone": "casual",  # casual | formal
        "emoji": False,
        "max_sentences": 4,
        "mirror_customer_style": True,
        "greeting_mirroring": True,
    },
    "sales": {
        "price_prefix": "от",
        "never_above_listing": True,
        "price_policy": "always",  # always | second_request
        "promo_code": "AVITO-DEMO-5",
        "promo_enabled": True,
        "office_address": "Москва, ул. Демонстрационная, 1, офис 405",
        "office_hours": "ежедневно 10:00–21:00",
        "delivery_regions": "СДЭК / Авито Доставка по РФ",
        "max_offers": 3,
        "min_offers": 2,
        "gift_conditions": ["A+", "A"],
    },
}

SECTION_LABELS = {
    "qualification": "Квалификация",
    "handoff": "Передача менеджеру",
    "followup": "Follow-up",
    "meeting": "Встречи",
    "ai_style": "Стиль AI",
    "sales": "Правила продаж",
}


def _row(db: Session, key: str) -> Setting | None:
    return db.get(Setting, key)


def ensure_defaults(db: Session) -> None:
    for key, value in DEFAULTS.items():
        if _row(db, key) is None:
            db.add(Setting(key=key, value=copy.deepcopy(value)))
    db.flush()


def get_section(db: Session, key: str) -> dict[str, Any]:
    row = _row(db, key)
    base = copy.deepcopy(DEFAULTS.get(key, {}))
    if row and isinstance(row.value, dict):
        base.update(row.value)
    return base


def get_all(db: Session) -> dict[str, dict[str, Any]]:
    return {key: get_section(db, key) for key in DEFAULTS}


def update_section(
    db: Session, key: str, patch: dict[str, Any], actor: str = "admin"
) -> dict[str, Any]:
    """Apply a partial update and write one audit row per changed field."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown settings section: {key}")

    current = get_section(db, key)
    changes: list[tuple[str, Any, Any]] = []
    for field, new_value in patch.items():
        old_value = current.get(field)
        if old_value != new_value:
            changes.append((field, old_value, new_value))
        current[field] = new_value

    row = _row(db, key)
    if row is None:
        row = Setting(key=key, value=current)
        db.add(row)
    else:
        row.value = current
    db.flush()

    for field, old_value, new_value in changes:
        db.add(
            AuditLog(
                actor=actor,
                entity=f"settings.{key}",
                entity_id=key,
                field=field,
                old_value=_render(old_value),
                new_value=_render(new_value),
            )
        )
    db.flush()
    return current


def reset_section(db: Session, key: str, actor: str = "admin") -> dict[str, Any]:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = _row(db, key)
    old = get_section(db, key)
    value = copy.deepcopy(DEFAULTS[key])
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.add(
        AuditLog(
            actor=actor,
            entity=f"settings.{key}",
            entity_id=key,
            field="*",
            old_value=_render(old),
            new_value="(значения по умолчанию)",
        )
    )
    db.flush()
    return value


def _render(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
