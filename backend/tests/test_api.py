"""HTTP-level checks against the real app, including foreign-key integrity.

SQLite only enforces foreign keys when asked (`PRAGMA foreign_keys=ON`, set in
`app.db`). Without it these deletes pass locally and fail on Postgres, which is
exactly how the conversation-delete bug reached the deployed demo.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Conversation, Event, FollowUp, Lead, Meeting, Task, TurnLog


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        test_client.post(
            "/api/auth/login",
            json={"username": settings.admin_username, "password": settings.admin_password},
        )
        yield test_client


def test_foreign_keys_are_enforced():
    """Guards the guard: if this pragma regresses, delete bugs go unnoticed."""
    if not settings.is_sqlite:
        pytest.skip("Postgres enforces foreign keys natively")
    with SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_health_needs_no_auth():
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/system/health").status_code == 200


def test_protected_endpoints_reject_anonymous():
    with TestClient(app) as anonymous:
        for path in ("/api/live/conversations", "/api/crm/board", "/api/control/settings"):
            assert anonymous.get(path).status_code == 401, path


def test_bad_password_is_rejected():
    with TestClient(app) as anonymous:
        response = anonymous.post(
            "/api/auth/login", json={"username": "admin", "password": "definitely-wrong"}
        )
        assert response.status_code == 401


def test_conversation_lifecycle_including_delete(client):
    """Create → talk → hand off → delete, with no orphaned rows left behind."""
    created = client.post(
        "/api/live/conversations",
        json={
            "name": "Удаляемый клиент",
            "source": "МНСГ",
            "first_message": "Здравствуйте, игровой ноут до 100 тысяч, я в Москве, сегодня",
        },
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation"]["id"]

    # produce dependent rows: handoff creates a task and events; the ladder a meeting
    client.post(
        f"/api/live/conversations/{conversation_id}/messages",
        json={"text": "Позвоните мне пожалуйста"},
    )

    with SessionLocal() as db:
        lead = db.execute(
            select(Lead).where(Lead.conversation_id == conversation_id)
        ).scalars().first()
        assert lead is not None
        lead_id = lead.id
        assert db.execute(select(Task).where(Task.lead_id == lead_id)).scalars().first()
        assert db.execute(
            select(Event).where(Event.conversation_id == conversation_id)
        ).scalars().first()

    response = client.delete(f"/api/live/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True

    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id) is None
        assert db.get(Lead, lead_id) is None
        for model, column in (
            (Event, Event.conversation_id),
            (FollowUp, FollowUp.conversation_id),
            (TurnLog, TurnLog.conversation_id),
        ):
            assert not db.execute(
                select(model).where(column == conversation_id)
            ).scalars().all(), f"{model.__name__} rows survived the delete"
        assert not db.execute(select(Task).where(Task.lead_id == lead_id)).scalars().all()
        assert not db.execute(select(Meeting).where(Meeting.lead_id == lead_id)).scalars().all()
        assert not db.execute(select(Event).where(Event.lead_id == lead_id)).scalars().all()


def test_delete_of_missing_conversation_is_404(client):
    assert client.delete("/api/live/conversations/99999").status_code == 404


def test_scenario_endpoint_runs_the_pipeline(client):
    response = client.post("/api/live/scenarios/out_of_stock")
    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) == 2
    reply = " ".join(step["ai"] or "" for step in body["steps"]).lower()
    assert "нет в наличии" in reply
    client.delete(f"/api/live/conversations/{body['conversation_id']}")


def test_control_center_update_is_audited(client):
    before = client.get("/api/control/settings").json()["sections"]["qualification"]
    original = before["handoff_threshold"]
    try:
        updated = client.put(
            "/api/control/settings/qualification", json={"values": {"handoff_threshold": 55}}
        )
        assert updated.status_code == 200
        assert updated.json()["values"]["handoff_threshold"] == 55

        audit = client.get("/api/control/audit").json()["items"]
        entry = next(row for row in audit if row["field"] == "handoff_threshold")
        assert entry["old"] == str(original)
        assert entry["new"] == "55"
    finally:
        client.put(
            "/api/control/settings/qualification",
            json={"values": {"handoff_threshold": original}},
        )


def test_unknown_settings_section_is_404(client):
    assert client.put("/api/control/settings/nope", json={"values": {}}).status_code == 404


def test_clock_speed_is_validated(client):
    assert client.post("/api/live/clock/speed", json={"speed": 7}).status_code == 400
    assert client.post("/api/live/clock/speed", json={"speed": 60}).status_code == 200


def test_inventory_stock_change_is_reflected(client):
    items = client.get("/api/inventory").json()["items"]
    target = next(item for item in items if item["stock"] > 0)
    try:
        response = client.post(f"/api/inventory/{target['id']}/stock", json={"stock": 0})
        assert response.status_code == 200
        assert response.json()["stock"] == 0
    finally:
        client.post(f"/api/inventory/{target['id']}/stock", json={"stock": target["stock"]})


def test_kb_edit_creates_a_revision(client):
    article = client.get("/api/kb").json()["items"][0]
    original_body = article["body"]
    try:
        updated = client.put(f"/api/kb/{article['id']}", json={"body": original_body + "\nтест"})
        assert updated.status_code == 200
        assert updated.json()["version"] == article["version"] + 1

        revisions = client.get(f"/api/kb/{article['id']}/revisions").json()["items"]
        assert revisions[0]["version"] == article["version"] + 1

        restored = client.post(
            f"/api/kb/{article['id']}/restore/{article['version']}"
        )
        assert restored.status_code == 200
    finally:
        client.put(f"/api/kb/{article['id']}", json={"body": original_body})
