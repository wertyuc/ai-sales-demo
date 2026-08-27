from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# an isolated database per test session, before app modules import settings
_TMP = Path(tempfile.mkdtemp(prefix="ai-sales-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("SEED_ON_STARTUP", "false")
os.environ.setdefault("LLM_PROVIDER", "demo")

from app.clock import clock  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Conversation, Customer  # noqa: E402
from app.seed import run as run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        run_seed(db)
        db.commit()
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def conversation(db):
    """A fresh, empty conversation with its own customer."""
    import uuid

    customer = Customer(
        name="Тестовый клиент",
        avito_id=f"test-{uuid.uuid4().hex[:10]}",
        source="МНСГ",
    )
    db.add(customer)
    db.flush()
    row = Conversation(customer_id=customer.id, started_at=clock.now(), scenario="test")
    db.add(row)
    db.flush()
    return row
