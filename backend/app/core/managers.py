"""Manager assignment (§28.3, §28.4).

One manager on shift takes everything; two or more share qualified leads
round-robin.  The rotation is derived from `assigned_total` + `last_assigned_at`
so it survives restarts and is visible in the assignment history.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Event, Manager


def on_shift(db: Session, role: str = "manager") -> list[Manager]:
    stmt = select(Manager).where(Manager.on_shift.is_(True), Manager.role == role)
    return list(db.execute(stmt).scalars().all())


def pick(db: Session, role: str = "manager") -> Manager | None:
    """Round-robin across everyone currently on shift."""
    candidates = on_shift(db, role)
    if not candidates:
        # nobody on shift: fall back to the least loaded person so nothing is dropped
        candidates = list(db.execute(select(Manager).where(Manager.role == role)).scalars().all())
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    candidates.sort(
        key=lambda m: (m.assigned_total, m.last_assigned_at or m.created_at, m.id)
    )
    return candidates[0]


def assign(db: Session, lead, reason: str = "", role: str = "manager") -> Manager | None:
    manager = pick(db, role)
    if manager is None:
        return None
    previous = lead.manager_id
    lead.manager_id = manager.id
    manager.assigned_total += 1
    from ..clock import now  # local import: avoids a cycle at module load

    manager.last_assigned_at = now()
    db.add(
        Event(
            type="manager_assigned",
            conversation_id=lead.conversation_id,
            lead_id=lead.id,
            payload={
                "manager_id": manager.id,
                "manager": manager.name,
                "previous_manager_id": previous,
                "reason": reason,
                "on_shift": [m.name for m in on_shift(db, role)],
                "rule": "round-robin" if len(on_shift(db, role)) > 1 else "single-on-shift",
            },
            created_at=now(),
        )
    )
    db.flush()
    return manager


def assignment_history(db: Session, limit: int = 50) -> list[dict]:
    stmt = (
        select(Event)
        .where(Event.type == "manager_assigned")
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": row.id,
            "at": row.created_at.isoformat(timespec="seconds"),
            "lead_id": row.lead_id,
            "manager": row.payload.get("manager"),
            "reason": row.payload.get("reason"),
            "rule": row.payload.get("rule"),
            "on_shift": row.payload.get("on_shift") or [],
        }
        for row in rows
    ]
