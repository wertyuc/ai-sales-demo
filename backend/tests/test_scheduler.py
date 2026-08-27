"""Follow-up ladder and reminders, driven through the scheduler tick.

These exercise the rules from §12/§13 by moving the demo clock rather than
waiting: the tick is a pure function of "what time is it now".
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.clock import clock
from app.core import settings_store
from app.core.pipeline import handle_customer_message
from app.models import FollowUp, Message, Task
from app.scheduler import tick


def _pending(db, conversation_id: int) -> FollowUp | None:
    return db.execute(
        select(FollowUp).where(
            FollowUp.conversation_id == conversation_id,
            FollowUp.kind == "followup",
            FollowUp.status == "scheduled",
        )
    ).scalars().first()


def _sent_followups(db, conversation_id: int) -> list[FollowUp]:
    return list(
        db.execute(
            select(FollowUp).where(
                FollowUp.conversation_id == conversation_id,
                FollowUp.kind == "followup",
                FollowUp.status == "sent",
            )
        ).scalars().all()
    )


def _advance_to(followup: FollowUp) -> None:
    """Jump the demo clock just past a scheduled touch."""
    clock.set_now(followup.due_at + dt.timedelta(seconds=5))


def _run_tick(db) -> dict:
    """Tick, then flush.

    The test session runs with autoflush=False, so `refresh()` before a flush
    would silently drop everything the tick just wrote.
    """
    result = tick(db)
    db.flush()
    return result


def _followup_messages(db, conversation_id: int) -> list[Message]:
    return list(
        db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.kind.in_(("followup", "reminder")),
            ).order_by(Message.id)
        ).scalars().all()
    )


def test_read_and_silent_gets_the_fifteen_minute_touch(db, conversation):
    """§12 — прочёл и не ответил → первое касание через 15 минут."""
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, ищу игровой ноут до 90 тысяч")
        conversation.customer_reads_messages = True

        followup = _pending(db, conversation.id)
        assert followup is not None
        assert followup.rule == "first_delay"

        _advance_to(followup)
        # the tick is global, so assert on this conversation rather than on the
        # aggregate counters — the seeded demo chats have touches of their own
        _run_tick(db)

        assert followup.status == "sent"
        assert (followup.payload or {}).get("unread") is False

        sent_messages = _followup_messages(db, conversation.id)
        assert len(sent_messages) == 1
        assert sent_messages[0].role == "ai"

        # the ladder continues: a second touch is queued
        assert _pending(db, conversation.id) is not None
    finally:
        clock.set_now(start)


def test_unread_touch_is_postponed_then_stops_after_the_limit(db, conversation):
    """§12 — не читает: перенос, затем максимум N касаний и тишина."""
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, интересует ноутбук до 70 тысяч")
        conversation.customer_reads_messages = False  # customer never opens the chat

        config = settings_store.get_section(db, "followup")
        limit = int(config["max_unread_touches"])

        followup = _pending(db, conversation.id)
        assert followup.attempt == 1
        _advance_to(followup)

        # first pass only postpones — the 15-minute rule requires a read receipt
        _run_tick(db)
        assert followup.status == "scheduled"
        assert followup.attempt == 2, "the tier must advance, or this loops forever"

        # from here the touches actually go out, but only up to the limit
        for _ in range(limit + 3):
            pending = _pending(db, conversation.id)
            if pending is None:
                break
            _advance_to(pending)
            _run_tick(db)

        sent = _sent_followups(db, conversation.id)
        assert len(sent) <= limit, "AI must stop touching a customer who never reads"
        assert all((row.payload or {}).get("unread") for row in sent)

        blocked = db.execute(
            select(FollowUp).where(
                FollowUp.conversation_id == conversation.id, FollowUp.status == "blocked"
            )
        ).scalars().first()
        assert blocked is not None
        assert conversation.lead.ignored is True
        assert conversation.lead.quality == "ignored"
    finally:
        clock.set_now(start)


def test_customer_reply_cancels_the_touch(db, conversation):
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, ищу ноутбук до 80 тысяч")
        followup = _pending(db, conversation.id)
        _advance_to(followup)

        handle_customer_message(db, conversation, "Да, всё ещё актуально, я в Москве")
        _run_tick(db)

        assert followup.status == "cancelled"
        assert "ответил" in followup.note
    finally:
        clock.set_now(start)


def test_manager_takeover_cancels_pending_touches(db, conversation):
    """§29 — после подключения человека AI не шлёт follow-up."""
    from app.core import pipeline

    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, нужен ноутбук до 60 тысяч")
        followup = _pending(db, conversation.id)
        assert followup is not None

        pipeline.record_manager_message(db, conversation, "Здравствуйте, это Алексей", "Алексей")
        assert followup.status == "cancelled"

        assert _pending(db, conversation.id) is None
    finally:
        clock.set_now(start)


def test_touches_respect_the_priority_windows(db, conversation):
    """§13 — со второго касания отправка попадает в 12:30-14:30 или 17:00-20:00."""
    start = clock.now()
    try:
        # start the conversation at a time whose +1h lands outside both windows
        clock.set_now(dt.datetime.combine(start.date(), dt.time(8, 0)))
        handle_customer_message(db, conversation, "Здравствуйте, ищу ноутбук до 75 тысяч")
        conversation.customer_reads_messages = True

        first = _pending(db, conversation.id)
        _advance_to(first)
        _run_tick(db)

        second = _pending(db, conversation.id)
        assert second is not None
        windows = settings_store.get_section(db, "followup")["windows"]
        assert second.due_at.strftime("%H:%M") >= windows[0].split("-")[0], (
            f"второе касание в {second.due_at} вне приоритетных окон {windows}"
        )
    finally:
        clock.set_now(start)


def test_meeting_reminders_fire(db, conversation):
    """§11 — напоминания о встрече уходят клиенту."""
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Игровой ноут до 100 тысяч, я в Москве, себе")
        handle_customer_message(db, conversation, "Куда приехать?")
        handle_customer_message(db, conversation, "Да, сегодня удобно")
        handle_customer_message(db, conversation, "Вторая половина, в 18:00")
        assert conversation.lead.meeting_scheduled is True

        reminders = db.execute(
            select(FollowUp).where(
                FollowUp.conversation_id == conversation.id,
                FollowUp.kind == "meeting_reminder",
                FollowUp.status == "scheduled",
            )
        ).scalars().all()
        assert reminders, "напоминания должны быть запланированы"

        earliest = min(reminders, key=lambda row: row.due_at)
        before = len(_followup_messages(db, conversation.id))
        _advance_to(earliest)
        _run_tick(db)

        assert earliest.status == "sent"
        after = _followup_messages(db, conversation.id)
        assert len(after) > before
        assert after[-1].kind == "reminder"
    finally:
        clock.set_now(start)


def test_expired_task_becomes_overdue(db, conversation):
    """§28.6 — задача с дедлайном 5 минут помечается просроченной."""
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, интересует ноутбук")
        handle_customer_message(db, conversation, "Позвоните мне пожалуйста")

        task = db.execute(
            select(Task).where(Task.lead_id == conversation.lead.id)
        ).scalars().first()
        assert task is not None and task.status == "open"

        clock.set_now(task.deadline_at + dt.timedelta(minutes=1))
        _run_tick(db)

        assert task.status == "overdue"
    finally:
        clock.set_now(start)


def test_followup_text_differs_between_tiers(db, conversation):
    """Повторные касания не должны быть одинаковыми."""
    start = clock.now()
    try:
        handle_customer_message(db, conversation, "Здравствуйте, ищу ноутбук до 95 тысяч")
        conversation.customer_reads_messages = True

        texts: list[str] = []
        for _ in range(3):
            pending = _pending(db, conversation.id)
            if pending is None:
                break
            _advance_to(pending)
            _run_tick(db)
            sent = _followup_messages(db, conversation.id)
            if sent:
                texts.append(sent[-1].text)

        assert len(texts) >= 2
        assert len(set(texts)) == len(texts), "тексты касаний повторяются"
    finally:
        clock.set_now(start)


def test_message_carries_the_guard_verdict(db, conversation):
    """Вердикт Response Guard доступен интерфейсу на самом сообщении (§21)."""
    handle_customer_message(db, conversation, "Игровой ноут до 100 тысяч, Москва, сегодня")
    ai_messages = [m for m in conversation.messages if m.role == "ai"]
    assert ai_messages
    assert ai_messages[-1].meta.get("guard") in (
        "PASSED",
        "PASSED_WITH_WARNINGS",
        "FAILED",
    )


def test_scheduler_tick_reports_counters(db):
    """Тик отдаёт согласованную сводку и не падает на пустой очереди."""
    result = _run_tick(db)
    assert set(result) >= {"sent", "blocked", "postponed", "cancelled", "tasks_overdue"}
    assert all(isinstance(value, int) and value >= 0 for value in result.values())


def test_message_count_grows_only_by_scheduler_sends(db, conversation):
    """Тик без наступивших сроков не пишет клиенту."""
    handle_customer_message(db, conversation, "Здравствуйте, нужен ноутбук до 50 тысяч")
    before = len(_followup_messages(db, conversation.id))
    _run_tick(db)  # this conversation's touch is not due yet
    assert len(_followup_messages(db, conversation.id)) == before
