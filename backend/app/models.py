"""Database model.

One graph of entities shared by every screen of the suite: a message written in
Live Sales mutates the same Lead row that CRM renders and Analytics counts.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# --- vocabularies (kept as plain strings: no enum migrations in a demo) ------

QUALIFICATION_FIELDS = ("budget", "geo", "timeframe", "tasks", "requirements", "recipient")

LEAD_STAGES = ("new", "qualification", "arrives_1_3_days", "arrives_1_2_weeks", "deal", "lost")
LEAD_STAGE_LABELS = {
    "new": "Новый лид",
    "qualification": "Квалификация",
    "arrives_1_3_days": "Приедет 1-3 дня",
    "arrives_1_2_weeks": "Приезд 1-2 недели",
    "deal": "Сделка",
    "lost": "Потерян",
}

DEAL_DIRECTIONS = ("none", "delivery_region", "delivery_msk", "office")
DEAL_DIRECTION_LABELS = {
    "none": "—",
    "delivery_region": "Доставка регион",
    "delivery_msk": "Доставка МСК-МО",
    "office": "Ждём в офисе",
}

TEMPERATURES = ("COLD", "WARM", "HOT", "CRITICAL")


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="rop")  # rop | manager | head
    display_name: Mapped[str] = mapped_column(String(128), default="")


class Manager(Base, TimestampMixin):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default="manager")  # manager | service
    on_shift: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str] = mapped_column(String(16), default="#6366f1")
    assigned_total: Mapped[int] = mapped_column(Integer, default=0)
    last_assigned_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(16))  # laptop | desktop
    brand: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32))  # gaming | office | workstation | ultrabook
    cpu: Mapped[str] = mapped_column(String(96))
    gpu: Mapped[str] = mapped_column(String(96))
    ram: Mapped[int] = mapped_column(Integer)  # GB
    storage: Mapped[str] = mapped_column(String(64))
    screen: Mapped[str] = mapped_column(String(96), default="")
    condition: Mapped[str] = mapped_column(String(8))  # A+ | A | B
    price: Mapped[int] = mapped_column(Integer)  # actual "from" price, RUB
    listing_price: Mapped[int] = mapped_column(Integer)  # price shown in the ad (ceiling)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    suitability: Mapped[dict] = mapped_column(JSON, default=dict)  # task -> 0..100
    gpu_score: Mapped[int] = mapped_column(Integer, default=0)
    cpu_score: Mapped[int] = mapped_column(Integer, default=0)
    portability: Mapped[int] = mapped_column(Integer, default=50)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    avito_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(32), default="МНСГ")  # Avito account / segment
    avatar_color: Mapped[str] = mapped_column(String(16), default="#64748b")

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="customer")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(32), default="avito")
    mode: Mapped[str] = mapped_column(String(16), default="ai")  # ai | human
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|handoff|closed
    ai_silent_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_message_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_customer_read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    customer_reads_messages: Mapped[bool] = mapped_column(Boolean, default=True)
    scenario: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )
    lead: Mapped["Lead"] = relationship(back_populates="conversation", uselist=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # customer | ai | manager | system
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    author: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="chat")  # chat|followup|reminder
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Lead(Base, TimestampMixin):
    """The CRM card.  Structured qualification state lives here, not in the prompt."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), unique=True)

    stage: Mapped[str] = mapped_column(String(32), default="new")
    direction: Mapped[str] = mapped_column(String(32), default="none")
    temperature: Mapped[str] = mapped_column(String(16), default="COLD")

    # structured qualification: field -> {"value": ..., "raw": str, "source": str}
    qualification: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[int] = mapped_column(Integer, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, default=0)

    sentiment: Mapped[str] = mapped_column(String(16), default="neutral")
    contact_phone: Mapped[str] = mapped_column(String(32), default="")
    selected_products: Mapped[list] = mapped_column(JSON, default=list)  # product ids
    next_action: Mapped[str] = mapped_column(String(255), default="")

    handoff_required: Mapped[bool] = mapped_column(Boolean, default=False)
    handoff_reason: Mapped[str] = mapped_column(String(255), default="")
    handoff_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    handoff_kind: Mapped[str] = mapped_column(String(32), default="")  # manager|service|critical

    manager_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # transient dialogue state (meeting negotiation, asked questions, offers shown)
    flow_state: Mapped[dict] = mapped_column(JSON, default=dict)

    # analytics flags, written by the pipeline and the scheduler
    contact_acquired: Mapped[bool] = mapped_column(Boolean, default=False)
    invited_to_office: Mapped[bool] = mapped_column(Boolean, default=False)
    meeting_scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    arrived: Mapped[bool] = mapped_column(Boolean, default=False)
    sold: Mapped[bool] = mapped_column(Boolean, default=False)
    sale_amount: Mapped[int] = mapped_column(Integer, default=0)
    negative: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    lost: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[str] = mapped_column(String(24), default="pending")
    first_response_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="lead")
    customer: Mapped[Customer] = relationship()
    manager: Mapped[Manager | None] = relationship()


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    deadline_at: Mapped[dt.datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), default="open")  # open|done|overdue
    reason: Mapped[str] = mapped_column(String(255), default="")

    lead: Mapped[Lead] = relationship()
    manager: Mapped[Manager | None] = relationship()


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    scheduled_at: Mapped[dt.datetime] = mapped_column(DateTime)
    address: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), default="scheduled")  # scheduled|arrived|missed
    slot_label: Mapped[str] = mapped_column(String(64), default="")

    lead: Mapped[Lead] = relationship()


class FollowUp(Base, TimestampMixin):
    """A scheduled outbound touch, executed by the virtual-clock scheduler."""

    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # followup | meeting_reminder
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    due_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(24), default="scheduled")
    rule: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    conversation: Mapped[Conversation] = relationship()


class Event(Base):
    """Append-only business timeline; Analytics and Insights read from here."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(48), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)


class TurnLog(Base):
    """Everything that happened while producing one AI answer (Logs / Debug screen)."""

    __tablename__ = "turn_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    customer_message: Mapped[str] = mapped_column(Text, default="")
    ai_response: Mapped[str] = mapped_column(Text, default="")
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    rules_triggered: Mapped[list] = mapped_column(JSON, default=list)
    kb_fragments: Mapped[list] = mapped_column(JSON, default=list)
    products_queried: Mapped[list] = mapped_column(JSON, default=list)
    inventory_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    price_validation: Mapped[dict] = mapped_column(JSON, default=dict)
    safety_checks: Mapped[list] = mapped_column(JSON, default=list)
    crm_mutations: Mapped[list] = mapped_column(JSON, default=list)
    handoff_reason: Mapped[str] = mapped_column(String(255), default="")
    followup_event: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    guard_verdict: Mapped[str] = mapped_column(String(24), default="PASSED")
    error: Mapped[str] = mapped_column(Text, default="")


class Setting(Base, TimestampMixin):
    """Control Center values — one JSON blob per config section."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class KBArticle(Base, TimestampMixin):
    __tablename__ = "kb_articles"
    __table_args__ = (UniqueConstraint("branch", "slug", name="uq_kb_branch_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    branch: Mapped[str] = mapped_column(String(32), index=True)
    slug: Mapped[str] = mapped_column(String(96))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list] = mapped_column(JSON, default=list)


class KBRevision(Base):
    __tablename__ = "kb_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("kb_articles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    author: Mapped[str] = mapped_column(String(64), default="admin")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="admin")
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    field: Mapped[str] = mapped_column(String(96), default="")
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
