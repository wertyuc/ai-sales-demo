"""Live Sales API: conversations, messages, AI/Human mode, demo scenarios, clock."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import ALLOWED_SPEEDS, clock
from ..core import pipeline, settings_store
from ..core.scenarios import SCENARIOS, by_key
from ..db import get_db
from ..llm.factory import provider_info
from ..models import Conversation, Customer, FollowUp, Message, TurnLog
from ..security import require_user
from ..views import conversation_summary, intelligence, message_row

router = APIRouter(prefix="/api/live", tags=["live"], dependencies=[Depends(require_user)])

PALETTE = ("#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#ef4444", "#14b8a6")


class SendMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class NewConversation(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    source: str = "МНСГ"
    first_message: str | None = None


class ModeChange(BaseModel):
    mode: str = Field(pattern="^(ai|human)$")


class SpeedChange(BaseModel):
    speed: int


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)) -> dict:
    config = settings_store.get_section(db, "qualification")
    rows = db.execute(
        select(Conversation).order_by(Conversation.last_message_at.desc().nullslast())
    ).scalars().all()
    return {
        "items": [conversation_summary(db, row, config) for row in rows],
        "clock": clock.state(),
        "provider": provider_info(),
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    return {
        "conversation": conversation_summary(db, conversation),
        "messages": [message_row(m) for m in conversation.messages],
        "intelligence": intelligence(db, conversation),
        "clock": clock.state(),
    }


@router.post("/conversations")
def create_conversation(payload: NewConversation, db: Session = Depends(get_db)) -> dict:
    count = db.execute(select(Customer)).scalars().all().__len__()
    customer = Customer(
        name=payload.name,
        avito_id=f"avito-demo-{count + 1}-{int(clock.now().timestamp())}",
        nickname=payload.name.lower(),
        source=payload.source,
        avatar_color=PALETTE[count % len(PALETTE)],
    )
    db.add(customer)
    db.flush()
    conversation = Conversation(
        customer_id=customer.id,
        channel="avito",
        mode="ai",
        status="active",
        scenario="manual",
        started_at=clock.now(),
    )
    db.add(conversation)
    db.flush()

    if payload.first_message:
        pipeline.handle_customer_message(db, conversation, payload.first_message)
    db.commit()
    db.refresh(conversation)
    return {
        "conversation": conversation_summary(db, conversation),
        "messages": [message_row(m) for m in conversation.messages],
        "intelligence": intelligence(db, conversation),
    }


@router.post("/conversations/{conversation_id}/messages")
def send_customer_message(
    conversation_id: int, payload: SendMessage, db: Session = Depends(get_db)
) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    result = pipeline.handle_customer_message(db, conversation, payload.text.strip())
    db.commit()
    db.refresh(conversation)
    return {
        "reply": result.reply,
        "suppressed": result.suppressed,
        "handoff": result.handoff,
        "conversation": conversation_summary(db, conversation),
        "messages": [message_row(m) for m in conversation.messages],
        "intelligence": intelligence(db, conversation),
        "log_id": result.log.id if result.log else None,
    }


@router.post("/conversations/{conversation_id}/manager-message")
def send_manager_message(
    conversation_id: int, payload: SendMessage, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    pipeline.record_manager_message(db, conversation, payload.text.strip(), user.display_name or "Менеджер")
    db.commit()
    db.refresh(conversation)
    return {
        "conversation": conversation_summary(db, conversation),
        "messages": [message_row(m) for m in conversation.messages],
        "intelligence": intelligence(db, conversation),
    }


@router.post("/conversations/{conversation_id}/mode")
def change_mode(
    conversation_id: int, payload: ModeChange, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    pipeline.set_mode(db, conversation, payload.mode, actor=user.username)
    db.commit()
    db.refresh(conversation)
    return {"conversation": conversation_summary(db, conversation),
            "intelligence": intelligence(db, conversation)}


@router.post("/conversations/{conversation_id}/read")
def toggle_read_behaviour(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    """Flip whether the demo customer reads outgoing messages (drives §12 rules)."""
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    conversation.customer_reads_messages = not conversation.customer_reads_messages
    if conversation.customer_reads_messages:
        now = clock.now()
        for message in conversation.messages:
            if message.role in ("ai", "manager") and message.read_at is None:
                message.read_at = now
        conversation.last_customer_read_at = now
    db.commit()
    return {"reads": conversation.customer_reads_messages}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Диалог не найден")
    for row in db.execute(
        select(FollowUp).where(FollowUp.conversation_id == conversation_id)
    ).scalars().all():
        db.delete(row)
    for row in db.execute(
        select(TurnLog).where(TurnLog.conversation_id == conversation_id)
    ).scalars().all():
        db.delete(row)
    if conversation.lead:
        db.delete(conversation.lead)
    db.delete(conversation)
    db.commit()
    return {"ok": True}


# --- scenarios ---------------------------------------------------------------


@router.get("/scenarios")
def list_scenarios() -> dict:
    return {
        "items": [
            {k: v for k, v in scenario.items() if k != "messages"} | {
                "steps": len(scenario["messages"])
            }
            for scenario in SCENARIOS
        ]
    }


@router.post("/scenarios/{key}")
def run_scenario(key: str, db: Session = Depends(get_db)) -> dict:
    scenario = by_key(key)
    if not scenario:
        raise HTTPException(404, "Сценарий не найден")

    count = len(db.execute(select(Customer)).scalars().all())
    customer = Customer(
        name=f"{scenario['customer']} (демо)",
        avito_id=f"avito-scenario-{key}-{int(clock.now().timestamp())}",
        nickname=scenario["customer"].lower(),
        source="МНСГ",
        avatar_color=PALETTE[count % len(PALETTE)],
    )
    db.add(customer)
    db.flush()
    conversation = Conversation(
        customer_id=customer.id,
        channel="avito",
        mode="ai",
        status="active",
        scenario=key,
        started_at=clock.now(),
    )
    db.add(conversation)
    db.flush()

    steps = []
    for text in scenario["messages"]:
        result = pipeline.handle_customer_message(db, conversation, text)
        steps.append({"customer": text, "ai": result.reply, "suppressed": result.suppressed})
    db.commit()
    db.refresh(conversation)
    return {
        "conversation_id": conversation.id,
        "steps": steps,
        "conversation": conversation_summary(db, conversation),
        "messages": [message_row(m) for m in conversation.messages],
        "intelligence": intelligence(db, conversation),
    }


# --- demo clock --------------------------------------------------------------


@router.get("/clock")
def get_clock() -> dict:
    return clock.state()


@router.post("/clock/speed")
def set_speed(payload: SpeedChange) -> dict:
    if payload.speed not in ALLOWED_SPEEDS:
        raise HTTPException(400, f"Допустимые скорости: {ALLOWED_SPEEDS}")
    clock.set_speed(payload.speed)
    return clock.state()


@router.post("/clock/jump")
def jump(minutes: int = 60) -> dict:
    clock.jump(max(-1440, min(minutes, 10080)))
    return clock.state()
