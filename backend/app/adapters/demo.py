"""Demo implementations of the four integration boundaries.

They are backed by the local database instead of Avito / Bitrix24 / МойСклад /
Яндекс.Диск, but they honour the same contracts, so the pipeline code that runs
in the demo is the code that will run against the real APIs.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now
from ..models import Conversation, Lead, Manager, Message, Product, Task
from .base import AvitoAdapter, CRMAdapter, InventoryAdapter, InventoryItem, InventoryQuery, MediaAdapter


def _to_item(product: Product) -> InventoryItem:
    return InventoryItem(
        id=product.id,
        sku=product.sku,
        brand=product.brand,
        model=product.model,
        type=product.type,
        category=product.category,
        cpu=product.cpu,
        gpu=product.gpu,
        ram=product.ram,
        storage=product.storage,
        screen=product.screen,
        condition=product.condition,
        price=product.price,
        listing_price=product.listing_price,
        stock=product.stock,
        description=product.description,
        tags=list(product.tags or []),
        suitability=dict(product.suitability or {}),
        gpu_score=product.gpu_score,
        cpu_score=product.cpu_score,
        portability=product.portability,
    )


class DemoInventoryAdapter(InventoryAdapter):
    """Reads the `products` table.  Stands in for МойСклад."""

    name = "DemoInventoryAdapter"

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: InventoryQuery) -> list[InventoryItem]:
        stmt = select(Product)
        if query.only_in_stock:
            stmt = stmt.where(Product.stock > 0)
        if query.budget_max:
            # a 7% overshoot is still worth showing as an "чуть выше бюджета" option
            stmt = stmt.where(Product.price <= int(query.budget_max * 1.07))
        if query.budget_min:
            stmt = stmt.where(Product.price >= query.budget_min)
        if query.brand:
            stmt = stmt.where(Product.brand == query.brand)
        if query.type:
            stmt = stmt.where(Product.type == query.type)
        if query.conditions:
            stmt = stmt.where(Product.condition.in_(query.conditions))
        rows = self.db.execute(stmt).scalars().all()
        return [_to_item(row) for row in rows][: max(query.limit, 1) * 4]

    def get(self, product_id: int) -> InventoryItem | None:
        product = self.db.get(Product, product_id)
        return _to_item(product) if product else None

    def check_stock(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        rows = self.db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
        return {row.id: row.stock for row in rows}

    def find_by_text(self, text: str) -> list[InventoryItem]:
        """Loose model lookup, used when the customer names a specific machine."""
        low = text.lower()
        rows = self.db.execute(select(Product)).scalars().all()
        hits = []
        for row in rows:
            haystack = f"{row.brand} {row.model}".lower()
            tokens = [t for t in haystack.replace("-", " ").split() if len(t) > 2]
            if sum(1 for t in tokens if t in low) >= 2:
                hits.append(_to_item(row))
        return hits


class DemoCRMAdapter(CRMAdapter):
    """Writes to the local `leads` / `tasks` tables.  Stands in for Bitrix24."""

    name = "DemoCRMAdapter"

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_lead(self, lead_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        lead = self.db.get(Lead, lead_id)
        if not lead:
            return {"ok": False, "reason": "lead not found"}
        applied: dict[str, Any] = {}
        for key, value in payload.items():
            if hasattr(lead, key) and getattr(lead, key) != value:
                setattr(lead, key, value)
                applied[key] = value
        self.db.flush()
        return {"ok": True, "applied": applied}

    def move_stage(self, lead_id: int, stage: str, reason: str = "") -> dict[str, Any]:
        lead = self.db.get(Lead, lead_id)
        if not lead or lead.stage == stage:
            return {"ok": False, "stage": getattr(lead, "stage", None)}
        previous = lead.stage
        lead.stage = stage
        self.db.flush()
        return {"ok": True, "from": previous, "to": stage, "reason": reason}

    def create_task(
        self, lead_id: int, manager_id: int | None, title: str, deadline: dt.datetime, reason: str
    ) -> dict[str, Any]:
        task = Task(
            lead_id=lead_id,
            manager_id=manager_id,
            title=title,
            deadline_at=deadline,
            reason=reason,
            status="open",
            created_at=now(),
            updated_at=now(),
        )
        self.db.add(task)
        self.db.flush()
        return {"ok": True, "task_id": task.id, "deadline": deadline.isoformat()}

    def assign_manager(self, lead_id: int, manager_id: int) -> dict[str, Any]:
        lead = self.db.get(Lead, lead_id)
        manager = self.db.get(Manager, manager_id)
        if not lead or not manager:
            return {"ok": False}
        lead.manager_id = manager_id
        manager.assigned_total += 1
        manager.last_assigned_at = now()
        self.db.flush()
        return {"ok": True, "manager": manager.name}


class MockAvitoAdapter(AvitoAdapter):
    """In-app messenger.  Stands in for the Avito Messenger API."""

    name = "MockAvitoAdapter"

    def __init__(self, db: Session) -> None:
        self.db = db

    def send_message(self, conversation_id: int, text: str) -> dict[str, Any]:
        return {"ok": True, "conversation_id": conversation_id, "chars": len(text)}

    def mark_read(self, conversation_id: int, message_id: int) -> None:
        message = self.db.get(Message, message_id)
        if message and message.read_at is None:
            message.read_at = now()
            self.db.flush()

    def read_state(self, conversation_id: int) -> dict[str, Any]:
        conversation = self.db.get(Conversation, conversation_id)
        if not conversation:
            return {"reads": False}
        unread = [m for m in conversation.messages if m.role in ("ai", "manager") and not m.read_at]
        return {
            "reads": conversation.customer_reads_messages,
            "unread_outbound": len(unread),
            "last_read_at": conversation.last_customer_read_at,
        }


class DemoMediaAdapter(MediaAdapter):
    """Stands in for Яндекс.Диск: knows *that* assets exist, never invents them."""

    name = "DemoMediaAdapter"

    def list_assets(self, sku: str) -> list[dict[str, Any]]:
        return [
            {"sku": sku, "kind": "photo", "count": 6, "path": f"/AI-Sales-Demo/{sku}/photo"},
            {"sku": sku, "kind": "video", "count": 1, "path": f"/AI-Sales-Demo/{sku}/video"},
        ]

    def request_upload(self, sku: str, requested_by: str) -> dict[str, Any]:
        return {
            "ok": True,
            "sku": sku,
            "requested_by": requested_by,
            "note": "Менеджер выгрузит фото/видео из Яндекс.Диска",
        }
