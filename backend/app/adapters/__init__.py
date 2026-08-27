"""Adapter wiring.

Change these three lines to point the whole product at real integrations.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .base import (
    AvitoAdapter,
    CRMAdapter,
    InventoryAdapter,
    InventoryItem,
    InventoryQuery,
    MediaAdapter,
)
from .demo import DemoCRMAdapter, DemoInventoryAdapter, DemoMediaAdapter, MockAvitoAdapter


def inventory(db: Session) -> DemoInventoryAdapter:
    return DemoInventoryAdapter(db)


def crm(db: Session) -> DemoCRMAdapter:
    return DemoCRMAdapter(db)


def avito(db: Session) -> MockAvitoAdapter:
    return MockAvitoAdapter(db)


def media() -> DemoMediaAdapter:
    return DemoMediaAdapter()


ACTIVE = {
    "inventory": "DemoInventoryAdapter (→ МойСклад)",
    "crm": "DemoCRMAdapter (→ Bitrix24)",
    "messenger": "MockAvitoAdapter (→ Avito Messenger API)",
    "media": "DemoMediaAdapter (→ Яндекс.Диск)",
}

__all__ = [
    "AvitoAdapter", "CRMAdapter", "InventoryAdapter", "MediaAdapter",
    "InventoryItem", "InventoryQuery", "ACTIVE",
    "inventory", "crm", "avito", "media",
]
