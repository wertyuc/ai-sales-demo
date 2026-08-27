"""CRM API: kanban board, lead cards, managers, tasks, meetings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now as clock_now
from ..core import managers as manager_engine
from ..core.crm import QUALITY_LABELS
from ..db import get_db
from ..models import (
    DEAL_DIRECTION_LABELS,
    DEAL_DIRECTIONS,
    LEAD_STAGE_LABELS,
    LEAD_STAGES,
    AuditLog,
    Lead,
    Manager,
    Meeting,
    Task,
)
from ..security import require_user
from ..views import iso, lead_card, manager_row

router = APIRouter(prefix="/api/crm", tags=["crm"], dependencies=[Depends(require_user)])


class StageChange(BaseModel):
    stage: str


class DirectionChange(BaseModel):
    direction: str


class NotesChange(BaseModel):
    notes: str


class ShiftChange(BaseModel):
    on_shift: bool


class OutcomeChange(BaseModel):
    arrived: bool | None = None
    sold: bool | None = None
    sale_amount: int | None = None


@router.get("/board")
def board(db: Session = Depends(get_db)) -> dict:
    leads = db.execute(select(Lead).order_by(Lead.updated_at.desc())).scalars().all()
    cards = [lead_card(db, lead) for lead in leads]
    columns = [
        {
            "key": stage,
            "label": LEAD_STAGE_LABELS[stage],
            "cards": [card for card in cards if card["stage"] == stage],
        }
        for stage in LEAD_STAGES
    ]
    return {
        "columns": columns,
        "directions": [
            {"key": key, "label": DEAL_DIRECTION_LABELS[key]} for key in DEAL_DIRECTIONS
        ],
        "quality_labels": QUALITY_LABELS,
        "total": len(cards),
    }


@router.get("/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db)) -> dict:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Лид не найден")
    history = db.execute(
        select(AuditLog).where(AuditLog.entity == "lead", AuditLog.entity_id == str(lead_id))
        .order_by(AuditLog.created_at.desc())
    ).scalars().all()
    card = lead_card(db, lead)
    card["history"] = [
        {
            "at": iso(row.created_at),
            "actor": row.actor,
            "field": row.field,
            "old": row.old_value,
            "new": row.new_value,
        }
        for row in history
    ]
    return card


@router.post("/leads/{lead_id}/stage")
def move_stage(
    lead_id: int, payload: StageChange, db: Session = Depends(get_db), user=Depends(require_user)
) -> dict:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Лид не найден")
    if payload.stage not in LEAD_STAGES:
        raise HTTPException(400, "Неизвестный этап")
    old = lead.stage
    lead.stage = payload.stage
    db.add(AuditLog(actor=user.username, entity="lead", entity_id=str(lead_id), field="stage",
                    old_value=old, new_value=payload.stage, created_at=clock_now()))
    db.commit()
    return lead_card(db, lead)


@router.post("/leads/{lead_id}/direction")
def change_direction(
    lead_id: int, payload: DirectionChange, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Лид не найден")
    if payload.direction not in DEAL_DIRECTIONS:
        raise HTTPException(400, "Неизвестное направление")
    old = lead.direction
    lead.direction = payload.direction
    db.add(AuditLog(actor=user.username, entity="lead", entity_id=str(lead_id), field="direction",
                    old_value=old, new_value=payload.direction, created_at=clock_now()))
    db.commit()
    return lead_card(db, lead)


@router.post("/leads/{lead_id}/notes")
def set_notes(
    lead_id: int, payload: NotesChange, db: Session = Depends(get_db), user=Depends(require_user)
) -> dict:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Лид не найден")
    old = lead.notes
    lead.notes = payload.notes[:4000]
    db.add(AuditLog(actor=user.username, entity="lead", entity_id=str(lead_id), field="notes",
                    old_value=old[:200], new_value=lead.notes[:200], created_at=clock_now()))
    db.commit()
    return lead_card(db, lead)


@router.post("/leads/{lead_id}/outcome")
def set_outcome(
    lead_id: int, payload: OutcomeChange, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """Mark a visit or a sale — closes the loop for the funnel metrics."""
    from ..models import Event

    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Лид не найден")
    now = clock_now()
    if payload.arrived is not None:
        lead.arrived = payload.arrived
        meeting = db.execute(
            select(Meeting).where(Meeting.lead_id == lead_id).order_by(Meeting.id.desc())
        ).scalars().first()
        if meeting:
            meeting.status = "arrived" if payload.arrived else "scheduled"
        db.add(Event(type="arrived", conversation_id=lead.conversation_id, lead_id=lead.id,
                     payload={"arrived": payload.arrived}, created_at=now))
    if payload.sold is not None:
        lead.sold = payload.sold
        if payload.sold:
            lead.stage = "deal"
            lead.sale_amount = payload.sale_amount or lead.sale_amount or 0
            db.add(Event(type="sale", conversation_id=lead.conversation_id, lead_id=lead.id,
                         payload={"amount": lead.sale_amount}, created_at=now))
    db.add(AuditLog(actor=user.username, entity="lead", entity_id=str(lead_id), field="outcome",
                    old_value="", new_value=str(payload.model_dump()), created_at=now))
    db.commit()
    return lead_card(db, lead)


# --- managers ----------------------------------------------------------------


@router.get("/managers")
def list_managers(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Manager).order_by(Manager.id)).scalars().all()
    return {
        "items": [manager_row(db, row) for row in rows],
        "history": manager_engine.assignment_history(db),
        "on_shift": [m.name for m in manager_engine.on_shift(db)],
    }


@router.post("/managers/{manager_id}/shift")
def set_shift(
    manager_id: int, payload: ShiftChange, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    manager = db.get(Manager, manager_id)
    if not manager:
        raise HTTPException(404, "Менеджер не найден")
    old = manager.on_shift
    manager.on_shift = payload.on_shift
    db.add(AuditLog(actor=user.username, entity="manager", entity_id=str(manager_id),
                    field="on_shift", old_value=str(old), new_value=str(payload.on_shift),
                    created_at=clock_now()))
    db.commit()
    return manager_row(db, manager)


# --- tasks & meetings --------------------------------------------------------


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)) -> dict:
    now = clock_now()
    rows = db.execute(select(Task).order_by(Task.deadline_at)).scalars().all()
    return {
        "items": [
            {
                "id": task.id,
                "lead_id": task.lead_id,
                "customer": task.lead.customer.name if task.lead and task.lead.customer else "—",
                "title": task.title,
                "reason": task.reason,
                "status": task.status,
                "manager": task.manager.name if task.manager else None,
                "manager_color": task.manager.color if task.manager else None,
                "deadline": iso(task.deadline_at),
                "seconds_left": int((task.deadline_at - now).total_seconds()),
            }
            for task in rows
        ]
    }


@router.post("/tasks/{task_id}/done")
def complete_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Задача не найдена")
    task.status = "done"
    db.commit()
    return {"ok": True, "status": task.status}


@router.get("/meetings")
def list_meetings(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Meeting).order_by(Meeting.scheduled_at)).scalars().all()
    return {
        "items": [
            {
                "id": meeting.id,
                "lead_id": meeting.lead_id,
                "customer": meeting.lead.customer.name if meeting.lead else "—",
                "at": iso(meeting.scheduled_at),
                "label": meeting.slot_label,
                "status": meeting.status,
                "address": meeting.address,
            }
            for meeting in rows
        ]
    }
