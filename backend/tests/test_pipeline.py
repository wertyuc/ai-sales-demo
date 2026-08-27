"""End-to-end behaviour of a conversation turn."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.clock import clock
from app.core import pipeline, settings_store
from app.core.pipeline import handle_customer_message
from app.models import FollowUp, Product, Task


def test_happy_path_end_to_end(db, conversation):
    """create → message → qualification → product → CRM → handoff → analytics."""
    result = handle_customer_message(
        db, conversation, "Привет! Нужен игровой ноут до 100 тысяч, я в Москве, могу приехать сегодня"
    )
    lead = conversation.lead

    assert result.reply, "AI must answer"
    assert lead.score >= 60, "qualification must move on the first message"
    assert lead.closed_count >= 4
    assert lead.temperature in ("HOT", "WARM")
    assert lead.selected_products, "products must be attached to the lead"
    assert lead.stage != "new"
    assert result.log.guard_verdict in ("PASSED", "PASSED_WITH_WARNINGS")


def test_offered_products_are_real_and_in_stock(db, conversation):
    handle_customer_message(db, conversation, "Игровой ноутбук до 100 тысяч, Москва, сегодня")
    lead = conversation.lead
    for product_id in lead.selected_products:
        product = db.get(Product, product_id)
        assert product is not None, "AI may only offer catalogue items"
        assert product.stock > 0, "AI may never offer an out-of-stock item"


def test_prices_are_quoted_with_the_from_prefix(db, conversation):
    handle_customer_message(db, conversation, "Игровой ноутбук до 100 тысяч, Москва")
    reply = [m for m in conversation.messages if m.role == "ai"][-1].text
    if "₽" in reply:
        for line in reply.splitlines():
            if "₽" in line and "—" in line:
                assert "от " in line.lower(), f"price without the ОТ prefix: {line}"


def test_never_quotes_above_the_listing_price(db, conversation):
    handle_customer_message(db, conversation, "Игровой ноутбук до 200 тысяч, Москва")
    lead = conversation.lead
    for product_id in lead.selected_products:
        product = db.get(Product, product_id)
        assert product.price <= product.listing_price


def test_does_not_repeat_a_closed_question(db, conversation):
    handle_customer_message(
        db, conversation, "Я в Москве, игровой ноут до 100 тысяч, куплю сегодня, себе"
    )
    handle_customer_message(db, conversation, "Играю в Cyberpunk")
    replies = " ".join(m.text.lower() for m in conversation.messages if m.role == "ai")
    assert "на какой бюджет" not in replies
    assert "вы в москве" not in replies


def test_out_of_stock_is_declined_not_invented(db, conversation):
    dead = db.execute(select(Product).where(Product.stock == 0)).scalars().first()
    handle_customer_message(db, conversation, f"Интересует {dead.brand} {dead.model}, он есть?")
    reply = [m for m in conversation.messages if m.role == "ai"][-1].text.lower()
    assert "нет в наличии" in reply
    lead = conversation.lead
    assert dead.id not in (lead.selected_products or [])


def test_unsuitable_machine_is_refused(db, conversation):
    """§17 — do not rubber-stamp a bad choice just to make a sale."""
    handle_customer_message(db, conversation, "Хочу ASUS ZenBook, тонкий ультрабук")
    handle_customer_message(
        db, conversation, "Буду играть в Cyberpunk на высоких, бюджет 80 тысяч, я в Москве"
    )
    reply = [m for m in conversation.messages if m.role == "ai"][-1].text.lower()
    assert "не подойдёт" in reply or "не подойдет" in reply
    # and whatever it offers instead must actually be able to run games
    for product_id in conversation.lead.selected_products:
        product = db.get(Product, product_id)
        assert product.gpu_score >= 60, f"{product.model} cannot run demanding games"


# --- handoff rules -----------------------------------------------------------


def test_phone_request_triggers_handoff_and_task(db, conversation):
    handle_customer_message(db, conversation, "Здравствуйте, интересует ноутбук")
    handle_customer_message(db, conversation, "Позвоните мне пожалуйста")
    lead = conversation.lead
    assert lead.handoff_required
    assert lead.handoff_kind == "manager"
    assert conversation.mode == "human"

    task = db.execute(select(Task).where(Task.lead_id == lead.id)).scalars().first()
    assert task is not None
    deadline = int((task.deadline_at - lead.handoff_at).total_seconds() / 60)
    assert deadline == 5, "§28.6 — the deadline is five minutes"
    assert lead.manager is not None, "a manager on shift must be assigned"


def test_ai_suspicion_is_critical(db, conversation):
    handle_customer_message(db, conversation, "Ищу ноутбук для работы")
    handle_customer_message(db, conversation, "У меня ощущение, что я с роботом разговариваю")
    lead = conversation.lead
    assert lead.handoff_kind == "critical"
    assert lead.temperature == "CRITICAL"
    assert conversation.mode == "human"


def test_negative_sentiment_hands_off(db, conversation):
    handle_customer_message(db, conversation, "Сколько стоит Legion 5?")
    handle_customer_message(db, conversation, "Это отвратительное обслуживание, вы обманываете")
    lead = conversation.lead
    assert lead.negative is True
    assert lead.handoff_required


def test_service_question_goes_to_the_service_desk(db, conversation):
    handle_customer_message(db, conversation, "У меня гарантийный случай, ноутбук не включается")
    assert conversation.lead.handoff_kind == "service"


def test_region_plus_four_fields_hands_off(db, conversation):
    handle_customer_message(
        db,
        conversation,
        "Я из Казани, нужен ноутбук для работы, бюджет до 150 тысяч, куплю на этой неделе",
    )
    lead = conversation.lead
    assert lead.direction == "delivery_region"
    assert lead.handoff_required


# --- human takeover ----------------------------------------------------------


def test_manager_message_silences_the_ai(db, conversation):
    handle_customer_message(db, conversation, "Здравствуйте, нужен ноутбук")
    pipeline.record_manager_message(db, conversation, "Здравствуйте, я Алексей", "Алексей")
    assert conversation.mode == "human"
    assert conversation.ai_silent_until > clock.now()

    result = handle_customer_message(db, conversation, "Хорошо, жду")
    assert result.reply is None
    assert result.suppressed == "human_active"


def test_return_to_ai_restores_answering(db, conversation):
    handle_customer_message(db, conversation, "Здравствуйте")
    pipeline.set_mode(db, conversation, "human")
    assert handle_customer_message(db, conversation, "Ещё вопрос").reply is None
    pipeline.set_mode(db, conversation, "ai")
    assert handle_customer_message(db, conversation, "Нужен игровой ноут до 100к").reply


# --- meetings & follow-ups ---------------------------------------------------


def test_meeting_ladder_books_a_slot(db, conversation):
    handle_customer_message(db, conversation, "Игровой ноут до 100 тысяч, я в Москве, себе")
    handle_customer_message(db, conversation, "Куда приехать?")
    handle_customer_message(db, conversation, "Да, сегодня удобно")
    handle_customer_message(db, conversation, "Вторая половина, в 18:00")

    lead = conversation.lead
    assert lead.meeting_scheduled is True
    reply = [m for m in conversation.messages if m.role == "ai"][-1].text
    assert "18:00" in reply

    reminders = db.execute(
        select(FollowUp).where(
            FollowUp.conversation_id == conversation.id, FollowUp.kind == "meeting_reminder"
        )
    ).scalars().all()
    assert reminders, "§11 — meeting reminders must be scheduled"


def test_followup_is_scheduled_fifteen_minutes_out(db, conversation):
    handle_customer_message(db, conversation, "Здравствуйте, ищу ноутбук до 90 тысяч")
    followup = db.execute(
        select(FollowUp).where(
            FollowUp.conversation_id == conversation.id,
            FollowUp.kind == "followup",
            FollowUp.status == "scheduled",
        )
    ).scalars().first()
    assert followup is not None
    config = settings_store.get_section(db, "followup")
    delta = followup.due_at - conversation.last_message_at
    assert delta <= dt.timedelta(minutes=int(config["first_delay_minutes"]) + 1)


def test_customer_reply_cancels_the_pending_followup(db, conversation):
    handle_customer_message(db, conversation, "Здравствуйте, ищу ноутбук")
    handle_customer_message(db, conversation, "Бюджет 90 тысяч, Москва")
    pending = db.execute(
        select(FollowUp).where(
            FollowUp.conversation_id == conversation.id, FollowUp.status == "scheduled"
        )
    ).scalars().all()
    assert len(pending) == 1, "only the newest touch stays scheduled"


# --- configurability ---------------------------------------------------------


def test_control_center_threshold_changes_behaviour(db, conversation):
    """Changing a rule in settings must change the next answer, with no redeploy."""
    settings_store.update_section(db, "handoff", {"phone_request": False})
    handle_customer_message(db, conversation, "Здравствуйте, нужен ноутбук")
    handle_customer_message(db, conversation, "Позвоните мне")
    assert conversation.lead.handoff_kind != "manager" or not conversation.lead.handoff_required
    settings_store.update_section(db, "handoff", {"phone_request": True})
