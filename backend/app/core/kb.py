"""Modular knowledge base (§33) with versioning (§35, §19 of the demo brief).

Four independent branches — PCs, laptops, sales rules, restrictions.  Editing one
branch cannot change the behaviour of another, because retrieval is scoped by
branch and every article carries its own on/off switch and revision history.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now
from ..models import AuditLog, KBArticle, KBRevision

BRANCHES = {
    "pcs": "БЗ ПК",
    "laptops": "БЗ Ноутбуки",
    "sales_rules": "БЗ Правил",
    "restrictions": "БЗ Запретов",
}


def list_articles(db: Session, branch: str | None = None) -> list[KBArticle]:
    stmt = select(KBArticle)
    if branch:
        stmt = stmt.where(KBArticle.branch == branch)
    return list(db.execute(stmt.order_by(KBArticle.branch, KBArticle.id)).scalars().all())


def create(db: Session, branch: str, slug: str, title: str, body: str, tags: list[str] | None = None,
           actor: str = "admin") -> KBArticle:
    article = KBArticle(
        branch=branch,
        slug=slug,
        title=title,
        body=body,
        tags=tags or [],
        enabled=True,
        version=1,
        created_at=now(),
        updated_at=now(),
    )
    db.add(article)
    db.flush()
    db.add(
        KBRevision(
            article_id=article.id, version=1, title=title, body=body,
            enabled=True, author=actor, created_at=now(),
        )
    )
    db.add(
        AuditLog(
            actor=actor, entity="kb", entity_id=str(article.id), field="create",
            old_value="", new_value=f"{BRANCHES.get(branch, branch)} / {title}", created_at=now(),
        )
    )
    db.flush()
    return article


def update(db: Session, article_id: int, patch: dict, actor: str = "admin") -> KBArticle | None:
    article = db.get(KBArticle, article_id)
    if not article:
        return None

    changes: list[tuple[str, str, str]] = []
    for field_name in ("title", "body", "enabled", "tags"):
        if field_name in patch and getattr(article, field_name) != patch[field_name]:
            changes.append(
                (field_name, str(getattr(article, field_name))[:400], str(patch[field_name])[:400])
            )
            setattr(article, field_name, patch[field_name])

    if not changes:
        return article

    article.version += 1
    article.updated_at = now()
    db.add(
        KBRevision(
            article_id=article.id,
            version=article.version,
            title=article.title,
            body=article.body,
            enabled=article.enabled,
            author=actor,
            created_at=now(),
        )
    )
    for field_name, old, new in changes:
        db.add(
            AuditLog(
                actor=actor, entity="kb", entity_id=str(article.id), field=field_name,
                old_value=old, new_value=new, created_at=now(),
            )
        )
    db.flush()
    return article


def revisions(db: Session, article_id: int) -> list[KBRevision]:
    stmt = (
        select(KBRevision)
        .where(KBRevision.article_id == article_id)
        .order_by(KBRevision.version.desc())
    )
    return list(db.execute(stmt).scalars().all())


def restore(db: Session, article_id: int, version: int, actor: str = "admin") -> KBArticle | None:
    target = db.execute(
        select(KBRevision).where(
            KBRevision.article_id == article_id, KBRevision.version == version
        )
    ).scalars().first()
    if not target:
        return None
    return update(
        db,
        article_id,
        {"title": target.title, "body": target.body, "enabled": target.enabled},
        actor=actor,
    )


# --- retrieval ---------------------------------------------------------------

BRANCH_FOR_TASK = {
    "games": "laptops",
    "work": "laptops",
    "study": "laptops",
    "creative": "laptops",
    "dev": "laptops",
}


def retrieve(db: Session, *, tasks: list[str], signals: set[str], product_types: list[str],
             limit: int = 4) -> list[dict]:
    """Pick the enabled fragments relevant to the current turn."""
    articles = [a for a in list_articles(db) if a.enabled]
    scored: list[tuple[int, KBArticle]] = []

    wanted_branches = {"sales_rules", "restrictions"}
    if "desktop" in product_types:
        wanted_branches.add("pcs")
    if "laptop" in product_types or not product_types:
        wanted_branches.add("laptops")

    for article in articles:
        score = 0
        if article.branch in wanted_branches:
            score += 2
        tags = [t.lower() for t in (article.tags or [])]
        for task in tasks:
            if task in tags:
                score += 3
        for signal in signals:
            if signal in tags:
                score += 3
        if article.branch == "restrictions":
            score += 2  # restrictions are always relevant
        if score:
            scored.append((score, article))

    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [
        {
            "id": article.id,
            "branch": article.branch,
            "branch_label": BRANCHES.get(article.branch, article.branch),
            "title": article.title,
            "version": article.version,
            "excerpt": article.body[:400],
        }
        for _, article in scored[:limit]
    ]
