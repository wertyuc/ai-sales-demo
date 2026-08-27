"""Serialisation helpers: ORM rows → the JSON shapes the UI expects."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as clock_now
from .core import settings_store
from .core.crm import QUALITY_LABELS
from .core.handoff import hot_signal_labels
from .core.qualification import FIELD_LABELS, compute, humanize, next_best_action
from .models import (
    DEAL_DIRECTION_LABELS,
    LEAD_STAGE_LABELS,
    Conversation,
    FollowUp,
    Lead,
    Manager,
    Meeting,
    Message,
    Product,
    Task,
    TurnLog,
)


def iso(value: dt.datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def message_row(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "author": message.author,
        "kind": message.kind,
        "created_at": iso(message.created_at),
        "read_at": iso(message.read_at),
        "meta": message.meta or {},
    }


def conversation_summary(db: Session, conversation: Conversation, config: dict | None = None) -> dict:
    config = config or settings_store.get_section(db, "qualification")
    lead = conversation.lead
    stats = compute(lead.qualification or {}, config) if lead else {"score": 0, "closed_count": 0}
    last = conversation.messages[-1] if conversation.messages else None
    unread = sum(
        1 for m in conversation.messages if m.role in ("ai", "manager") and not m.read_at
    )
    return {
        "id": conversation.id,
        "customer": {
            "id": conversation.customer.id,
            "name": conversation.customer.name,
            "avito_id": conversation.customer.avito_id,
            "source": conversation.customer.source,
            "color": conversation.customer.avatar_color,
            "phone": conversation.customer.phone,
        },
        "mode": conversation.mode,
        "status": conversation.status,
        "scenario": conversation.scenario,
        "score": stats.get("score", 0),
        "closed_count": stats.get("closed_count", 0),
        "temperature": lead.temperature if lead else "COLD",
        "stage": lead.stage if lead else "new",
        "stage_label": LEAD_STAGE_LABELS.get(lead.stage if lead else "new", ""),
        "handoff_required": bool(lead and lead.handoff_required),
        "handoff_reason": lead.handoff_reason if lead else "",
        "handoff_kind": lead.handoff_kind if lead else "",
        "manager": lead.manager.name if lead and lead.manager else None,
        "last_message": (last.text[:90] if last else ""),
        "last_message_role": last.role if last else "",
        "last_message_at": iso(conversation.last_message_at),
        "unread_outbound": unread,
        "ai_silent_until": iso(conversation.ai_silent_until),
        "message_count": len(conversation.messages),
    }


def intelligence(db: Session, conversation: Conversation) -> dict:
    """The right-hand Live Intelligence panel."""
    config = settings_store.get_section(db, "qualification")
    lead = conversation.lead
    if lead is None:
        return {"available": False}

    stats = compute(lead.qualification or {}, config)
    readable = humanize(lead.qualification or {})
    fields = [
        {
            "key": key,
            "label": FIELD_LABELS[key],
            "value": readable.get(key, ""),
            "closed": key in stats["closed"],
            "weight": next(
                (f.get("weight") for f in config.get("fields", []) if f["key"] == key), 0
            ),
        }
        for key in FIELD_LABELS
    ]

    products = []
    if lead.selected_products:
        rows = db.execute(
            select(Product).where(Product.id.in_(lead.selected_products))
        ).scalars().all()
        products = [
            {
                "id": row.id,
                "sku": row.sku,
                "title": f"{row.brand} {row.model}",
                "price": row.price,
                "condition": row.condition,
                "stock": row.stock,
            }
            for row in rows
        ]

    meeting = db.execute(
        select(Meeting).where(Meeting.lead_id == lead.id).order_by(Meeting.id.desc())
    ).scalars().first()
    task = db.execute(
        select(Task).where(Task.lead_id == lead.id).order_by(Task.id.desc())
    ).scalars().first()

    now = clock_now()
    signals = set((lead.flow_state or {}).get("signals") or [])

    return {
        "available": True,
        "lead_id": lead.id,
        "fields": fields,
        "score": stats["score"],
        "closed_count": stats["closed_count"],
        "total_fields": stats["total"],
        "qualified": stats["qualified"],
        "threshold": config.get("handoff_threshold", 80),
        "temperature": lead.temperature,
        "sentiment": lead.sentiment,
        "stage": lead.stage,
        "stage_label": LEAD_STAGE_LABELS.get(lead.stage, lead.stage),
        "direction": lead.direction,
        "direction_label": DEAL_DIRECTION_LABELS.get(lead.direction, "—"),
        "contact_phone": lead.contact_phone,
        "delivery": DEAL_DIRECTION_LABELS.get(lead.direction, "—"),
        "products": products,
        "next_action": lead.next_action or next_best_action(
            {
                "qualification": lead.qualification,
                "stats": stats,
                "handoff_required": lead.handoff_required,
                "handoff_reason": lead.handoff_reason,
                "contact_phone": lead.contact_phone,
                "meeting": lead.meeting_scheduled,
                "selected_products": lead.selected_products,
            }
        ),
        "handoff": {
            "required": lead.handoff_required,
            "reason": lead.handoff_reason,
            "kind": lead.handoff_kind,
            "at": iso(lead.handoff_at),
            "manager": lead.manager.name if lead.manager else None,
        },
        "hot_signals": hot_signal_labels(signals),
        "meeting": (
            {
                "at": iso(meeting.scheduled_at),
                "label": meeting.slot_label,
                "status": meeting.status,
                "address": meeting.address,
            }
            if meeting
            else None
        ),
        "task": (
            {
                "title": task.title,
                "deadline": iso(task.deadline_at),
                "status": task.status,
                "seconds_left": int((task.deadline_at - now).total_seconds()),
                "manager": task.manager.name if task.manager else None,
            }
            if task
            else None
        ),
        "quality": lead.quality,
        "quality_label": QUALITY_LABELS.get(lead.quality, lead.quality),
    }


def lead_card(db: Session, lead: Lead) -> dict:
    config = settings_store.get_section(db, "qualification")
    stats = compute(lead.qualification or {}, config)
    readable = humanize(lead.qualification or {})
    products = []
    if lead.selected_products:
        rows = db.execute(
            select(Product).where(Product.id.in_(lead.selected_products))
        ).scalars().all()
        products = [
            {"id": r.id, "sku": r.sku, "title": f"{r.brand} {r.model}", "price": r.price}
            for r in rows
        ]
    meeting = db.execute(
        select(Meeting).where(Meeting.lead_id == lead.id).order_by(Meeting.id.desc())
    ).scalars().first()
    task = db.execute(
        select(Task).where(Task.lead_id == lead.id).order_by(Task.id.desc())
    ).scalars().first()
    return {
        "id": lead.id,
        "conversation_id": lead.conversation_id,
        "customer": {
            "name": lead.customer.name,
            "avito_id": lead.customer.avito_id,
            "phone": lead.contact_phone or lead.customer.phone,
            "source": lead.customer.source,
            "color": lead.customer.avatar_color,
        },
        "stage": lead.stage,
        "stage_label": LEAD_STAGE_LABELS.get(lead.stage, lead.stage),
        "direction": lead.direction,
        "direction_label": DEAL_DIRECTION_LABELS.get(lead.direction, "—"),
        "temperature": lead.temperature,
        "score": stats["score"],
        "closed_count": stats["closed_count"],
        "qualification": readable,
        "budget": readable.get("budget", ""),
        "location": readable.get("geo", ""),
        "needs": readable.get("tasks", ""),
        "timeframe": readable.get("timeframe", ""),
        "recipient": readable.get("recipient", ""),
        "products": products,
        "manager": lead.manager.name if lead.manager else None,
        "manager_color": lead.manager.color if lead.manager else None,
        "next_action": lead.next_action,
        "handoff_required": lead.handoff_required,
        "handoff_reason": lead.handoff_reason,
        "notes": lead.notes,
        "quality": lead.quality,
        "quality_label": QUALITY_LABELS.get(lead.quality, lead.quality),
        "contact_acquired": lead.contact_acquired,
        "meeting_scheduled": lead.meeting_scheduled,
        "arrived": lead.arrived,
        "sold": lead.sold,
        "meeting": {"at": iso(meeting.scheduled_at), "status": meeting.status} if meeting else None,
        "task": (
            {"title": task.title, "deadline": iso(task.deadline_at), "status": task.status}
            if task
            else None
        ),
        "created_at": iso(lead.created_at),
        "updated_at": iso(lead.updated_at),
    }


def product_row(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "type": product.type,
        "brand": product.brand,
        "model": product.model,
        "title": f"{product.brand} {product.model}",
        "category": product.category,
        "cpu": product.cpu,
        "gpu": product.gpu,
        "ram": product.ram,
        "storage": product.storage,
        "screen": product.screen,
        "condition": product.condition,
        "price": product.price,
        "listing_price": product.listing_price,
        "stock": product.stock,
        "description": product.description,
        "tags": product.tags or [],
        "suitability": product.suitability or {},
        "gpu_score": product.gpu_score,
        "cpu_score": product.cpu_score,
        "portability": product.portability,
    }


def followup_row(db: Session, followup: FollowUp) -> dict:
    conversation = db.get(Conversation, followup.conversation_id)
    now = clock_now()
    return {
        "id": followup.id,
        "conversation_id": followup.conversation_id,
        "customer": conversation.customer.name if conversation else "—",
        "customer_color": conversation.customer.avatar_color if conversation else "#64748b",
        "kind": followup.kind,
        "attempt": followup.attempt,
        "rule": followup.rule,
        "note": followup.note,
        "status": followup.status,
        "due_at": iso(followup.due_at),
        "sent_at": iso(followup.sent_at),
        "seconds_left": int((followup.due_at - now).total_seconds()),
        "unread": bool((followup.payload or {}).get("unread")),
    }


def log_row(log: TurnLog, conversation: Conversation | None) -> dict:
    return {
        "id": log.id,
        "conversation_id": log.conversation_id,
        "customer": conversation.customer.name if conversation else "—",
        "created_at": iso(log.created_at),
        "customer_message": log.customer_message,
        "ai_response": log.ai_response,
        "extracted": log.extracted or {},
        "rules_triggered": log.rules_triggered or [],
        "kb_fragments": log.kb_fragments or [],
        "products_queried": log.products_queried or [],
        "inventory_snapshot": log.inventory_snapshot or [],
        "price_validation": log.price_validation or {},
        "safety_checks": log.safety_checks or [],
        "crm_mutations": log.crm_mutations or [],
        "handoff_reason": log.handoff_reason,
        "followup_event": log.followup_event,
        "provider": log.provider,
        "model": log.model,
        "latency_ms": log.latency_ms,
        "guard_verdict": log.guard_verdict,
        "error": log.error,
    }


def manager_row(db: Session, manager: Manager) -> dict:
    open_tasks = db.execute(
        select(Task).where(Task.manager_id == manager.id, Task.status == "open")
    ).scalars().all()
    leads = db.execute(select(Lead).where(Lead.manager_id == manager.id)).scalars().all()
    return {
        "id": manager.id,
        "name": manager.name,
        "role": manager.role,
        "on_shift": manager.on_shift,
        "color": manager.color,
        "assigned_total": manager.assigned_total,
        "open_tasks": len(open_tasks),
        "leads": len(leads),
        "last_assigned_at": iso(manager.last_assigned_at),
    }
