"""Analytics layer (§39, §40).

Every number is computed from the same tables the Live Sales screen writes, so a
conversation played in the demo moves the dashboard immediately.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clock import now as clock_now
from ..models import Conversation, Event, FollowUp, Lead, Meeting, Message, Product, Task
from . import settings_store
from .crm import QUALITY_LABELS
from .qualification import compute


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def overview(db: Session, days: int = 30) -> dict:
    now = clock_now()
    since = now - dt.timedelta(days=days)
    config = settings_store.get_section(db, "qualification")

    leads = list(db.execute(select(Lead)).scalars().all())
    recent = [lead for lead in leads if (lead.created_at or now) >= since] or leads

    total = len(recent)
    stats_by_lead = {lead.id: compute(lead.qualification or {}, config) for lead in recent}

    qualified_3 = sum(1 for lead in recent if stats_by_lead[lead.id]["closed_count"] >= 3)
    qualified_4 = sum(1 for lead in recent if stats_by_lead[lead.id]["closed_count"] >= 4)
    over_80 = sum(1 for lead in recent if stats_by_lead[lead.id]["score"] >= 80)

    contacts = sum(1 for lead in recent if lead.contact_acquired)
    invited = sum(1 for lead in recent if lead.invited_to_office)
    meetings = sum(1 for lead in recent if lead.meeting_scheduled)
    arrived = sum(1 for lead in recent if lead.arrived)
    sales = sum(1 for lead in recent if lead.sold)
    revenue = sum(lead.sale_amount for lead in recent if lead.sold)

    delivery_msk = sum(1 for lead in recent if lead.direction == "delivery_msk")
    delivery_region = sum(1 for lead in recent if lead.direction == "delivery_region")

    handoffs = sum(1 for lead in recent if lead.handoff_required and lead.handoff_kind != "service")
    service = sum(1 for lead in recent if lead.handoff_kind == "service")
    negative = sum(1 for lead in recent if lead.negative)
    ignored = sum(1 for lead in recent if lead.ignored)
    lost = sum(1 for lead in recent if lead.lost)

    response_times = [
        lead.first_response_seconds for lead in recent if lead.first_response_seconds is not None
    ]
    avg_response = round(sum(response_times) / len(response_times), 1) if response_times else 0.0
    fast_first = sum(1 for value in response_times if value <= 120)

    return {
        "period_days": days,
        "generated_at": now.isoformat(timespec="seconds"),
        "totals": {
            "leads": total,
            "qualified_3": qualified_3,
            "qualified_4": qualified_4,
            "qualification_80": over_80,
            "contacts": contacts,
            "invited_to_office": invited,
            "meetings": meetings,
            "arrived": arrived,
            "delivery_msk": delivery_msk,
            "delivery_region": delivery_region,
            "handoffs": handoffs,
            "service_handoffs": service,
            "negative": negative,
            "ignored": ignored,
            "lost": lost,
            "sales": sales,
            "revenue": revenue,
        },
        "rates": {
            "qualification_rate": _pct(qualified_3, total),
            "contact_conversion": _pct(contacts, qualified_3),
            "lead_to_qualification": _pct(qualified_3, total),
            "qualification_to_contact": _pct(contacts, qualified_3),
            "contact_to_meeting": _pct(meetings, contacts),
            "meeting_to_arrival": _pct(arrived, meetings),
            "lead_to_sale": _pct(sales, total),
            "first_response_under_2min": _pct(fast_first, len(response_times)),
        },
        "response": {
            "avg_seconds": avg_response,
            "measured": len(response_times),
            "under_2min": fast_first,
        },
        "funnel": [
            {"key": "leads", "label": "Лиды", "value": total},
            {"key": "qualified", "label": "Квалифицированы (≥3)", "value": qualified_3},
            {"key": "contacts", "label": "Получен контакт", "value": contacts},
            {"key": "meetings", "label": "Назначена встреча", "value": meetings},
            {"key": "arrived", "label": "Пришли в офис", "value": arrived},
            {"key": "sales", "label": "Продажи", "value": sales},
        ],
        "quality": _quality_breakdown(recent),
        "temperature": _counter(recent, "temperature"),
        "stages": _counter(recent, "stage"),
        "directions": _counter(recent, "direction"),
        "sources": _sources(db, recent),
        "timeline": _timeline(db, days),
        "handoff_reasons": _handoff_reasons(db),
        "top_products": _top_products(db, recent),
    }


def _quality_breakdown(leads: list[Lead]) -> list[dict]:
    counter = Counter(lead.quality for lead in leads)
    return [
        {"key": key, "label": QUALITY_LABELS.get(key, key), "value": value}
        for key, value in counter.most_common()
    ]


def _counter(leads: list[Lead], attribute: str) -> list[dict]:
    counter = Counter(getattr(lead, attribute) for lead in leads)
    return [{"key": key, "value": value} for key, value in counter.most_common()]


def _sources(db: Session, leads: list[Lead]) -> list[dict]:
    counter: Counter = Counter()
    qualified: Counter = Counter()
    for lead in leads:
        source = lead.customer.source if lead.customer else "—"
        counter[source] += 1
        if lead.closed_count >= 3:
            qualified[source] += 1
    return [
        {
            "source": source,
            "leads": value,
            "qualified": qualified.get(source, 0),
            "rate": _pct(qualified.get(source, 0), value),
        }
        for source, value in counter.most_common()
    ]


def _timeline(db: Session, days: int) -> list[dict]:
    now = clock_now()
    since = now - dt.timedelta(days=days)
    buckets: dict[str, dict] = defaultdict(
        lambda: {"leads": 0, "qualified": 0, "handoffs": 0, "meetings": 0, "sales": 0}
    )
    events = db.execute(select(Event).where(Event.created_at >= since)).scalars().all()
    for event in events:
        key = event.created_at.date().isoformat()
        if event.type == "lead_created":
            buckets[key]["leads"] += 1
        elif event.type == "handoff":
            buckets[key]["handoffs"] += 1
        elif event.type == "meeting_scheduled":
            buckets[key]["meetings"] += 1
        elif event.type == "sale":
            buckets[key]["sales"] += 1
        elif event.type == "crm_mutation" and (event.payload or {}).get("field") == "quality":
            if (event.payload or {}).get("to") in ("qualified", "quality"):
                buckets[key]["qualified"] += 1
    return [{"date": key, **value} for key, value in sorted(buckets.items())][-30:]


def _handoff_reasons(db: Session) -> list[dict]:
    events = db.execute(select(Event).where(Event.type == "handoff")).scalars().all()
    counter = Counter((event.payload or {}).get("code", "—") for event in events)
    labels = {
        "ai_suspicion": "Подозрение на AI",
        "negative": "Негатив",
        "service": "Сервисный вопрос",
        "phone_request": "Просит позвонить",
        "threshold": "Квалификация ≥ порога",
        "region": "Регион + 4 пункта",
        "photo": "Запрос фото/видео",
    }
    return [
        {"code": code, "label": labels.get(code, code), "value": value}
        for code, value in counter.most_common()
    ]


def _top_products(db: Session, leads: list[Lead]) -> list[dict]:
    counter: Counter = Counter()
    for lead in leads:
        for product_id in lead.selected_products or []:
            counter[product_id] += 1
    if not counter:
        return []
    rows = db.execute(
        select(Product).where(Product.id.in_(list(counter.keys())))
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    out = []
    for product_id, value in counter.most_common(8):
        product = by_id.get(product_id)
        if product:
            out.append(
                {
                    "title": f"{product.brand} {product.model}",
                    "sku": product.sku,
                    "value": value,
                    "price": product.price,
                }
            )
    return out


def daily_report(db: Session, day: dt.date | None = None) -> dict:
    """The exact daily format required by §39."""
    now = clock_now()
    day = day or now.date()
    leads = [
        lead
        for lead in db.execute(select(Lead)).scalars().all()
        if (lead.created_at or now).date() == day
    ]
    config = settings_store.get_section(db, "qualification")

    by_source: dict[str, list[Lead]] = defaultdict(list)
    for lead in leads:
        by_source[lead.customer.source if lead.customer else "—"].append(lead)

    def block(predicate) -> dict:
        return {
            source: sum(1 for lead in rows if predicate(lead))
            for source, rows in by_source.items()
        }

    qualified = [
        lead for lead in leads if compute(lead.qualification or {}, config)["closed_count"] >= 3
    ]
    quality = [lead for lead in leads if lead.quality == "quality"]

    return {
        "date": day.strftime("%d.%m.%Y"),
        "leads_total": len(leads),
        "leads_by_source": {source: len(rows) for source, rows in by_source.items()},
        "handed_to_managers": sum(1 for lead in leads if lead.handoff_required),
        "qualified_total": len(qualified),
        "qualified_by_source": block(
            lambda lead: compute(lead.qualification or {}, config)["closed_count"] >= 3
        ),
        "quality_total": len(quality),
        "quality_by_source": block(lambda lead: lead.quality == "quality"),
        "poor": sum(1 for lead in leads if lead.quality == "poor"),
        "negative": sum(1 for lead in leads if lead.negative),
        "ignored": sum(1 for lead in leads if lead.ignored),
        "arrived": sum(1 for lead in leads if lead.arrived),
    }


def operational(db: Session) -> dict:
    """Small counters used by the sidebar badges."""
    now = clock_now()
    open_tasks = db.execute(select(Task).where(Task.status == "open")).scalars().all()
    overdue = [task for task in open_tasks if task.deadline_at < now]
    scheduled = db.execute(
        select(FollowUp).where(FollowUp.status == "scheduled")
    ).scalars().all()
    meetings = db.execute(
        select(Meeting).where(Meeting.status == "scheduled")
    ).scalars().all()
    handoff_chats = db.execute(
        select(Conversation).where(Conversation.status == "handoff")
    ).scalars().all()
    return {
        "open_tasks": len(open_tasks),
        "overdue_tasks": len(overdue),
        "scheduled_followups": len(scheduled),
        "upcoming_meetings": len([m for m in meetings if m.scheduled_at >= now]),
        "handoff_chats": len(handoff_chats),
        "messages": db.execute(select(func.count(Message.id))).scalar() or 0,
    }
