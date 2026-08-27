"""Background scheduler.

A single background thread driven by the demo clock.  Because the clock can run at
×60, the fifteen-minute follow-up rule plays out in fifteen seconds on screen
while the rule itself stays exactly as written in the specification.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as clock_now
from .config import settings
from .core import followup as followup_engine
from .core import settings_store
from .db import session_scope
from .models import Conversation, Event, FollowUp, Lead, Meeting, Message, Task

log = logging.getLogger("scheduler")

_thread: threading.Thread | None = None
_stop_event = threading.Event()
_stats = {"ticks": 0, "sent": 0, "blocked": 0, "postponed": 0, "last_run": None}


def stats() -> dict:
    return dict(_stats)


# --- one pass ----------------------------------------------------------------


def tick(db: Session) -> dict:
    now = clock_now()
    config = settings_store.get_section(db, "followup")
    result = {"sent": 0, "blocked": 0, "postponed": 0, "cancelled": 0, "tasks_overdue": 0}

    due = db.execute(
        select(FollowUp)
        .where(FollowUp.status == "scheduled", FollowUp.due_at <= now)
        .order_by(FollowUp.due_at)
        .limit(25)
    ).scalars().all()

    for followup in due:
        conversation = db.get(Conversation, followup.conversation_id)
        if conversation is None:
            followup.status = "cancelled"
            followup.note = "диалог удалён"
            continue
        lead = db.get(Lead, followup.lead_id) if followup.lead_id else conversation.lead

        if followup.kind == "meeting_reminder":
            _send(db, conversation, followup, (followup.payload or {}).get("text", ""), now,
                  kind="reminder")
            result["sent"] += 1
            continue

        outcome = _process_followup(db, conversation, lead, followup, now, config)
        result[outcome] = result.get(outcome, 0) + 1

    # overdue manager tasks (§28.6)
    for task in db.execute(
        select(Task).where(Task.status == "open", Task.deadline_at < now)
    ).scalars().all():
        task.status = "overdue"
        db.add(
            Event(
                type="task_overdue",
                lead_id=task.lead_id,
                payload={"title": task.title, "deadline": task.deadline_at.isoformat()},
                created_at=now,
            )
        )
        result["tasks_overdue"] += 1

    # meetings that came and went
    for meeting in db.execute(
        select(Meeting).where(Meeting.status == "scheduled")
    ).scalars().all():
        if meeting.scheduled_at < now - dt.timedelta(hours=3):
            meeting.status = "missed"

    return result


def _process_followup(db, conversation, lead, followup, now, config) -> str:
    if conversation.mode == "human" or (
        conversation.ai_silent_until and conversation.ai_silent_until > now
    ):
        followup.status = "cancelled"
        followup.note = "чат ведёт менеджер"
        return "cancelled"

    last = followup_engine.last_outbound(db, conversation.id)
    if last and followup_engine.customer_replied_since(db, conversation.id, last.created_at):
        followup.status = "cancelled"
        followup.note = "клиент ответил"
        return "cancelled"

    read = bool(last and last.read_at)
    if not read and last and conversation.customer_reads_messages:
        # the messenger reports a read receipt; the Live Sales screen exposes this
        # as the "клиент читает / не читает" switch that drives the §12 rules
        last.read_at = now
        conversation.last_customer_read_at = now
        read = True
    require_read = config.get("require_read", True)

    # §12 — the 15-minute touch is conditional on the message having been read.
    # The attempt is advanced with the postponement, otherwise an unread chat
    # would be rescheduled at the same tier forever and never reach the
    # "two touches then stop" limit below.
    if followup.attempt == 1 and require_read and not read:
        due, rule = followup_engine.next_due(2, now, config)
        followup.attempt = 2
        followup.due_at = due
        followup.rule = rule
        followup.note = "не прочитано — перенос на следующий интервал"
        followup_engine.log_event(
            db, followup, "followup_postponed",
            {"reason": "unread", "new_due": due.isoformat(timespec="minutes")}, now,
        )
        return "postponed"

    if not read:
        used = followup_engine.unread_touches(db, conversation.id)
        if used >= int(config.get("max_unread_touches", 2)):
            followup.status = "blocked"
            followup.note = "клиент не читает: лимит напоминаний исчерпан"
            if lead:
                lead.ignored = True
                lead.lost = True
                lead.quality = "ignored"
            followup_engine.log_event(
                db, followup, "followup_stopped", {"reason": "unread_limit", "touches": used}, now
            )
            return "blocked"

    # §12 — at most one touch per day once the ladder is exhausted
    if followup.attempt >= 4:
        if followup_engine.touches_today(db, conversation.id, now.date()) >= int(
            config.get("max_touches_per_day", 1)
        ):
            due, rule = followup_engine.next_due(4, now, config)
            followup.due_at = due
            followup.rule = rule
            followup.note = "лимит: 1 касание в сутки"
            return "postponed"

    text = followup_engine.followup_text(followup.attempt, lead)
    _send(db, conversation, followup, text, now, kind="followup", unread=not read)

    if followup.attempt < 6:
        followup_engine.schedule(
            db, conversation, lead, followup.attempt + 1, now, config,
            note=followup_engine.TIER_LABELS.get(followup.attempt + 1, "1 раз в сутки"),
        )
    return "sent"


def _send(db, conversation, followup, text: str, now, *, kind: str, unread: bool = False) -> None:
    if not text:
        followup.status = "cancelled"
        followup.note = "пустой текст"
        return
    message = Message(
        conversation_id=conversation.id,
        role="ai",
        text=text,
        created_at=now,
        author="AI",
        kind=kind,
        meta={"followup_id": followup.id, "rule": followup.rule},
    )
    db.add(message)
    conversation.last_message_at = now
    followup.status = "sent"
    followup.sent_at = now
    payload = dict(followup.payload or {})
    payload["unread"] = unread
    followup.payload = payload
    followup_engine.log_event(
        db, followup, "followup_sent",
        {"attempt": followup.attempt, "rule": followup.rule, "kind": kind, "unread": unread},
        now,
    )


# --- loop --------------------------------------------------------------------


def _loop() -> None:
    """Runs on a dedicated daemon thread.

    The tick does synchronous SQLAlchemy work; on the event loop that would stall
    every in-flight HTTP request for its duration, so it gets its own thread.
    """
    interval = max(0.25, float(settings.scheduler_tick_seconds))
    while not _stop_event.is_set():
        try:
            with session_scope() as db:
                outcome = tick(db)
            _stats["ticks"] += 1
            _stats["sent"] += outcome.get("sent", 0)
            _stats["blocked"] += outcome.get("blocked", 0)
            _stats["postponed"] += outcome.get("postponed", 0)
            _stats["last_run"] = clock_now().isoformat(timespec="seconds")
        except Exception:  # pragma: no cover - the loop must survive a bad tick
            log.exception("scheduler tick failed")
        _stop_event.wait(interval)


def start() -> None:
    global _thread
    if not settings.scheduler_enabled or _thread is not None:
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="demo-scheduler", daemon=True)
    _thread.start()
    log.info("scheduler started (tick=%ss)", settings.scheduler_tick_seconds)


async def stop() -> None:
    global _thread
    if _thread is None:
        return
    _stop_event.set()
    _thread.join(timeout=5)
    _thread = None
