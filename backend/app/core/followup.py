"""Follow-up engine (§12, §13).

Ladder, straight from the specification:

    1st touch   +15 min   — only if the customer READ the message and stayed silent
    2nd touch   +1 hour
    3rd touch   evening
    then        at most once per day
    never read  → stop after `max_unread_touches`

From the second touch onward the send time is pulled into the priority windows
(12:30–14:30, 17:00–20:00).  All arithmetic uses the demo clock, so ×60 speed
demonstrates the whole ladder in under a minute.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import shift_into_windows
from ..models import Conversation, Event, FollowUp, Lead, Message

TIER_LABELS = {
    1: "через 15 минут (прочитано, без ответа)",
    2: "через 1 час",
    3: "вечером",
    4: "1 раз в сутки",
}


def next_due(attempt: int, now: dt.datetime, config: dict) -> tuple[dt.datetime, str]:
    """When the given attempt should fire, and which rule produced that time."""
    if attempt <= 1:
        due = now + dt.timedelta(minutes=int(config.get("first_delay_minutes", 15)))
        rule = "first_delay"
    elif attempt == 2:
        due = now + dt.timedelta(minutes=int(config.get("second_delay_minutes", 60)))
        rule = "second_delay"
    elif attempt == 3:
        evening_hour = int(config.get("evening_hour", 19))
        candidate = dt.datetime.combine(now.date(), dt.time(evening_hour, 0))
        due = candidate if candidate > now else candidate + dt.timedelta(days=1)
        rule = "evening"
    else:
        due = now + dt.timedelta(days=1)
        rule = "daily"

    if attempt >= int(config.get("respect_windows_from_attempt", 2)):
        windows = config.get("windows") or []
        due = shift_into_windows(due, windows)
    return due, rule


def cancel_pending(db: Session, conversation_id: int, reason: str = "customer_replied") -> int:
    stmt = select(FollowUp).where(
        FollowUp.conversation_id == conversation_id, FollowUp.status == "scheduled"
    )
    rows = list(db.execute(stmt).scalars().all())
    for row in rows:
        row.status = "cancelled"
        row.note = reason
    db.flush()
    return len(rows)


def schedule(
    db: Session,
    conversation: Conversation,
    lead: Lead | None,
    attempt: int,
    now: dt.datetime,
    config: dict,
    note: str = "",
) -> FollowUp | None:
    if not config.get("enabled", True):
        return None
    if conversation.mode == "human":
        return None
    due, rule = next_due(attempt, now, config)
    followup = FollowUp(
        conversation_id=conversation.id,
        lead_id=lead.id if lead else None,
        kind="followup",
        attempt=attempt,
        due_at=due,
        status="scheduled",
        rule=rule,
        note=note or TIER_LABELS.get(attempt, ""),
        created_at=now,
        updated_at=now,
        payload={},
    )
    db.add(followup)
    db.flush()
    return followup


def schedule_meeting_reminders(
    db: Session,
    conversation: Conversation,
    lead: Lead,
    scheduled_at: dt.datetime,
    now: dt.datetime,
    config: dict,
) -> list[FollowUp]:
    from .meeting import reminder_plan

    created: list[FollowUp] = []
    existing = db.execute(
        select(FollowUp).where(
            FollowUp.conversation_id == conversation.id,
            FollowUp.kind == "meeting_reminder",
            FollowUp.status == "scheduled",
        )
    ).scalars().all()
    for row in existing:
        row.status = "cancelled"
        row.note = "встреча перенесена"

    for when, rule, text in reminder_plan(scheduled_at, config):
        if when <= now:
            continue
        reminder = FollowUp(
            conversation_id=conversation.id,
            lead_id=lead.id,
            kind="meeting_reminder",
            attempt=1,
            due_at=when,
            status="scheduled",
            rule=rule,
            note=f"Напоминание о встрече ({rule})",
            created_at=now,
            updated_at=now,
            payload={"text": text},
        )
        db.add(reminder)
        created.append(reminder)
    db.flush()
    return created


def last_outbound(db: Session, conversation_id: int) -> Message | None:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.role.in_(("ai", "manager")))
        .order_by(Message.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def customer_replied_since(db: Session, conversation_id: int, since: dt.datetime) -> bool:
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.role == "customer",
        Message.created_at > since,
    )
    return db.execute(stmt).scalars().first() is not None


def unread_touches(db: Session, conversation_id: int) -> int:
    stmt = select(FollowUp).where(
        FollowUp.conversation_id == conversation_id,
        FollowUp.kind == "followup",
        FollowUp.status == "sent",
    )
    rows = db.execute(stmt).scalars().all()
    return sum(1 for row in rows if (row.payload or {}).get("unread"))


def touches_today(db: Session, conversation_id: int, day: dt.date) -> int:
    stmt = select(FollowUp).where(
        FollowUp.conversation_id == conversation_id,
        FollowUp.kind == "followup",
        FollowUp.status == "sent",
    )
    rows = db.execute(stmt).scalars().all()
    return sum(1 for row in rows if row.sent_at and row.sent_at.date() == day)


FOLLOWUP_TEXTS = {
    1: "Подскажите, актуален ещё подбор? Могу закрепить вариант за вами.",
    2: "Возвращаюсь к вашему запросу — остались вопросы по вариантам? "
       "Готов подобрать что-то ещё под ваш бюджет.",
    3: "Добрый вечер! Если подбор ещё актуален — напишите, "
       "я подготовлю пару вариантов из наличия на завтра.",
    4: "Напоминаю о себе: техника в наличии, условия в силе. "
       "Если планы поменялись — просто напишите, и я не буду беспокоить.",
}


def followup_text(attempt: int, lead: Lead | None) -> str:
    base = FOLLOWUP_TEXTS.get(min(attempt, 4), FOLLOWUP_TEXTS[4])
    if lead and lead.selected_products:
        return base
    return base


def log_event(db: Session, followup: FollowUp, event_type: str, payload: dict, now: dt.datetime) -> None:
    db.add(
        Event(
            type=event_type,
            conversation_id=followup.conversation_id,
            lead_id=followup.lead_id,
            payload=payload,
            created_at=now,
        )
    )
