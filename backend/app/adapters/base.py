"""Integration boundaries.

The business logic only ever talks to these four interfaces.  Swapping
`DemoInventoryAdapter` for a real МойСклад client is a constructor change in
`adapters/__init__.py`; nothing in `core/` needs to know.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InventoryItem:
    """A normalised stock record, whatever the source system calls it."""

    id: int
    sku: str
    brand: str
    model: str
    type: str
    category: str
    cpu: str
    gpu: str
    ram: int
    storage: str
    screen: str
    condition: str
    price: int
    listing_price: int
    stock: int
    description: str = ""
    tags: list[str] = field(default_factory=list)
    suitability: dict[str, int] = field(default_factory=dict)
    gpu_score: int = 0
    cpu_score: int = 0
    portability: int = 50

    @property
    def title(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


@dataclass
class InventoryQuery:
    budget_max: int | None = None
    budget_min: int | None = None
    tasks: list[str] = field(default_factory=list)
    brand: str | None = None
    type: str | None = None
    conditions: list[str] = field(default_factory=list)
    specs: list[str] = field(default_factory=list)
    only_in_stock: bool = True
    limit: int = 12


class InventoryAdapter(abc.ABC):
    """Source of truth for availability, price and specs (МойСклад in production)."""

    name: str = "inventory"

    @abc.abstractmethod
    def search(self, query: InventoryQuery) -> list[InventoryItem]: ...

    @abc.abstractmethod
    def get(self, product_id: int) -> InventoryItem | None: ...

    @abc.abstractmethod
    def check_stock(self, product_ids: list[int]) -> dict[int, int]: ...


class CRMAdapter(abc.ABC):
    """Lead/deal lifecycle (Bitrix24 in production)."""

    name: str = "crm"

    @abc.abstractmethod
    def upsert_lead(self, lead_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abc.abstractmethod
    def move_stage(self, lead_id: int, stage: str, reason: str = "") -> dict[str, Any]: ...

    @abc.abstractmethod
    def create_task(
        self, lead_id: int, manager_id: int | None, title: str, deadline: dt.datetime, reason: str
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    def assign_manager(self, lead_id: int, manager_id: int) -> dict[str, Any]: ...


class AvitoAdapter(abc.ABC):
    """Messenger transport: inbound webhooks, outbound sends, read receipts."""

    name: str = "avito"

    @abc.abstractmethod
    def send_message(self, conversation_id: int, text: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    def mark_read(self, conversation_id: int, message_id: int) -> None: ...

    @abc.abstractmethod
    def read_state(self, conversation_id: int) -> dict[str, Any]: ...


class MediaAdapter(abc.ABC):
    """Photo/video assets for a specific unit (Яндекс.Диск in production)."""

    name: str = "media"

    @abc.abstractmethod
    def list_assets(self, sku: str) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    def request_upload(self, sku: str, requested_by: str) -> dict[str, Any]: ...
