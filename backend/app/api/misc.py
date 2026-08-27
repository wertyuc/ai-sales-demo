"""Inventory, follow-ups, analytics, insights, control center, KB, logs, auth."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import ACTIVE
from ..clock import clock
from ..clock import now as clock_now
from ..config import settings
from ..core import analytics as analytics_module
from ..core import insights as insights_module
from ..core import kb as kb_module
from ..core import settings_store
from ..db import get_db
from ..llm.factory import provider_info
from ..models import AuditLog, Conversation, FollowUp, Product, TurnLog, User
from ..scheduler import stats as scheduler_stats
from ..seed import verify_password
from ..security import clear_session, current_user, issue_session, require_user
from ..views import followup_row, log_row, product_row

# --- auth --------------------------------------------------------------------

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str


@auth_router.post("/login")
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.execute(select(User).where(User.username == payload.username)).scalars().first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    issue_session(response, user)
    return {"username": user.username, "role": user.role, "display_name": user.display_name}


@auth_router.post("/logout")
def logout(response: Response) -> dict:
    clear_session(response)
    return {"ok": True}


@auth_router.get("/me")
def me(user: User | None = Depends(current_user)) -> dict:
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
    }


# --- inventory ---------------------------------------------------------------

inventory_router = APIRouter(
    prefix="/api/inventory", tags=["inventory"], dependencies=[Depends(require_user)]
)


class StockChange(BaseModel):
    stock: int = Field(ge=0, le=99)


@inventory_router.get("")
def list_products(
    q: str = "", category: str = "", type: str = "", in_stock: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(select(Product).order_by(Product.sku)).scalars().all()
    items = [product_row(row) for row in rows]
    if q:
        low = q.lower()
        items = [
            item for item in items
            if low in item["title"].lower() or low in item["sku"].lower()
            or low in item["cpu"].lower() or low in item["gpu"].lower()
        ]
    if category:
        items = [item for item in items if item["category"] == category]
    if type:
        items = [item for item in items if item["type"] == type]
    if in_stock:
        items = [item for item in items if item["stock"] > 0]
    return {
        "items": items,
        "total": len(rows),
        "in_stock": sum(1 for row in rows if row.stock > 0),
        "out_of_stock": sum(1 for row in rows if row.stock == 0),
        "categories": sorted({row.category for row in rows}),
        "types": sorted({row.type for row in rows}),
        "adapters": ACTIVE,
    }


@inventory_router.post("/{product_id}/stock")
def set_stock(
    product_id: int, payload: StockChange, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не найден")
    old = product.stock
    product.stock = payload.stock
    db.add(AuditLog(actor=user.username, entity="product", entity_id=product.sku, field="stock",
                    old_value=str(old), new_value=str(payload.stock), created_at=clock_now()))
    db.commit()
    return product_row(product)


# --- follow-ups --------------------------------------------------------------

followups_router = APIRouter(
    prefix="/api/followups", tags=["followups"], dependencies=[Depends(require_user)]
)


@followups_router.get("")
def list_followups(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(FollowUp).order_by(FollowUp.due_at)).scalars().all()
    items = [followup_row(db, row) for row in rows]
    return {
        "items": items,
        "scheduled": [i for i in items if i["status"] == "scheduled"],
        "sent": [i for i in items if i["status"] == "sent"],
        "blocked": [i for i in items if i["status"] in ("blocked", "cancelled")],
        "rules": settings_store.get_section(db, "followup"),
        "clock": clock.state(),
        "scheduler": scheduler_stats(),
    }


@followups_router.post("/{followup_id}/cancel")
def cancel_followup(followup_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(FollowUp, followup_id)
    if not row:
        raise HTTPException(404, "Касание не найдено")
    row.status = "cancelled"
    row.note = "отменено вручную"
    db.commit()
    return followup_row(db, row)


@followups_router.post("/{followup_id}/run-now")
def run_now(followup_id: int, db: Session = Depends(get_db)) -> dict:
    """Pull a scheduled touch to the present so it fires on the next tick."""
    row = db.get(FollowUp, followup_id)
    if not row:
        raise HTTPException(404, "Касание не найдено")
    row.due_at = clock_now() - dt.timedelta(seconds=1)
    db.commit()
    return followup_row(db, row)


# --- analytics ---------------------------------------------------------------

analytics_router = APIRouter(
    prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(require_user)]
)


@analytics_router.get("/overview")
def overview(days: int = 30, db: Session = Depends(get_db)) -> dict:
    return analytics_module.overview(db, days=max(1, min(days, 180)))


@analytics_router.get("/daily")
def daily(db: Session = Depends(get_db)) -> dict:
    return analytics_module.daily_report(db)


@analytics_router.get("/operational")
def operational(db: Session = Depends(get_db)) -> dict:
    return analytics_module.operational(db)


@analytics_router.get("/insights")
def insights(db: Session = Depends(get_db)) -> dict:
    return insights_module.generate(db)


# --- control center ----------------------------------------------------------

control_router = APIRouter(
    prefix="/api/control", tags=["control"], dependencies=[Depends(require_user)]
)


class SectionPatch(BaseModel):
    values: dict


@control_router.get("/settings")
def get_settings_sections(db: Session = Depends(get_db)) -> dict:
    return {
        "sections": settings_store.get_all(db),
        "labels": settings_store.SECTION_LABELS,
        "defaults": settings_store.DEFAULTS,
        "provider": provider_info(),
        "adapters": ACTIVE,
    }


@control_router.put("/settings/{section}")
def update_section(
    section: str, payload: SectionPatch, db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    try:
        value = settings_store.update_section(db, section, payload.values, actor=user.username)
    except KeyError:
        raise HTTPException(404, "Раздел настроек не найден") from None
    db.commit()
    return {"section": section, "values": value}


@control_router.post("/settings/{section}/reset")
def reset_section(
    section: str, db: Session = Depends(get_db), user=Depends(require_user)
) -> dict:
    try:
        value = settings_store.reset_section(db, section, actor=user.username)
    except KeyError:
        raise HTTPException(404, "Раздел настроек не найден") from None
    db.commit()
    return {"section": section, "values": value}


@control_router.get("/audit")
def audit(limit: int = 200, db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "at": row.created_at.isoformat(timespec="seconds"),
                "actor": row.actor,
                "entity": row.entity,
                "entity_id": row.entity_id,
                "field": row.field,
                "old": row.old_value,
                "new": row.new_value,
            }
            for row in rows
        ]
    }


# --- knowledge base ----------------------------------------------------------

kb_router = APIRouter(prefix="/api/kb", tags=["kb"], dependencies=[Depends(require_user)])


class KBCreate(BaseModel):
    branch: str
    slug: str
    title: str
    body: str = ""
    tags: list[str] = []


class KBPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    enabled: bool | None = None
    tags: list[str] | None = None


@kb_router.get("")
def list_kb(branch: str = "", db: Session = Depends(get_db)) -> dict:
    rows = kb_module.list_articles(db, branch or None)
    return {
        "branches": [{"key": key, "label": label} for key, label in kb_module.BRANCHES.items()],
        "items": [
            {
                "id": row.id,
                "branch": row.branch,
                "branch_label": kb_module.BRANCHES.get(row.branch, row.branch),
                "slug": row.slug,
                "title": row.title,
                "body": row.body,
                "enabled": row.enabled,
                "version": row.version,
                "tags": row.tags or [],
                "updated_at": row.updated_at.isoformat(timespec="seconds"),
            }
            for row in rows
        ],
    }


@kb_router.post("")
def create_kb(payload: KBCreate, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
    if payload.branch not in kb_module.BRANCHES:
        raise HTTPException(400, "Неизвестная ветка БЗ")
    article = kb_module.create(
        db, payload.branch, payload.slug, payload.title, payload.body, payload.tags,
        actor=user.username,
    )
    db.commit()
    return {"id": article.id, "version": article.version}


@kb_router.put("/{article_id}")
def update_kb(
    article_id: int, payload: KBPatch, db: Session = Depends(get_db), user=Depends(require_user)
) -> dict:
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    article = kb_module.update(db, article_id, patch, actor=user.username)
    if not article:
        raise HTTPException(404, "Статья не найдена")
    db.commit()
    return {"id": article.id, "version": article.version, "enabled": article.enabled}


@kb_router.get("/{article_id}/revisions")
def kb_revisions(article_id: int, db: Session = Depends(get_db)) -> dict:
    rows = kb_module.revisions(db, article_id)
    return {
        "items": [
            {
                "version": row.version,
                "title": row.title,
                "body": row.body,
                "enabled": row.enabled,
                "author": row.author,
                "at": row.created_at.isoformat(timespec="seconds"),
            }
            for row in rows
        ]
    }


@kb_router.post("/{article_id}/restore/{version}")
def kb_restore(
    article_id: int, version: int, db: Session = Depends(get_db), user=Depends(require_user)
) -> dict:
    article = kb_module.restore(db, article_id, version, actor=user.username)
    if not article:
        raise HTTPException(404, "Версия не найдена")
    db.commit()
    return {"id": article.id, "version": article.version}


# --- logs --------------------------------------------------------------------

logs_router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_user)])


@logs_router.get("")
def list_logs(
    conversation_id: int | None = None, limit: int = 80, db: Session = Depends(get_db)
) -> dict:
    stmt = select(TurnLog).order_by(TurnLog.id.desc()).limit(min(limit, 300))
    if conversation_id:
        stmt = (
            select(TurnLog)
            .where(TurnLog.conversation_id == conversation_id)
            .order_by(TurnLog.id.desc())
            .limit(min(limit, 300))
        )
    rows = db.execute(stmt).scalars().all()
    conversations = {
        row.id: row for row in db.execute(select(Conversation)).scalars().all()
    }
    return {
        "items": [log_row(row, conversations.get(row.conversation_id)) for row in rows],
        "provider": provider_info(),
        "scheduler": scheduler_stats(),
    }


# --- system ------------------------------------------------------------------

system_router = APIRouter(prefix="/api/system", tags=["system"])


@system_router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(select(Product).limit(1))
    return {
        "status": "ok",
        "environment": settings.environment,
        "clock": clock.state(),
        "provider": provider_info(),
    }


@system_router.get("/info", dependencies=[Depends(require_user)])
def info(db: Session = Depends(get_db)) -> dict:
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "database": "postgres" if not settings.is_sqlite else "sqlite",
        "provider": provider_info(),
        "adapters": ACTIVE,
        "scheduler": scheduler_stats(),
        "clock": clock.state(),
        "operational": analytics_module.operational(db),
    }
