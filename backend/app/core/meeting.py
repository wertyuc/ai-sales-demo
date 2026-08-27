"""Meeting controller (§10, §11).

Implements the closed-question ladder from the specification:

    "куда приехать?" → адрес + режим работы + "удобно сегодня?"
      да  → первая/вторая половина → конкретное время
      нет → будни/выходные → день недели → время

The negotiation state lives on `Lead.flow_state`, so the AI never loses its place
in the ladder and never re-asks a step the customer already answered.
"""
from __future__ import annotations

import datetime as dt

from ..clock import parse_hhmm

WEEKDAY_NAMES = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAY_TOKENS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4,
    "суббот": 5, "воскресен": 6,
}

STEP_NONE = ""
STEP_TODAY = "asked_today"
STEP_DAY_PART = "asked_day_part"
STEP_TIME = "asked_time"
STEP_WEEK_PART = "asked_week_part"
STEP_WEEKDAY = "asked_weekday"
STEP_DONE = "confirmed"


def flow(lead) -> dict:
    """A copy of the meeting sub-state; persist changes through `_save`."""
    meeting = (lead.flow_state or {}).get("meeting")
    return dict(meeting) if isinstance(meeting, dict) else {}


def _save(lead, meeting_state: dict) -> None:
    state = dict(lead.flow_state or {})
    state["meeting"] = meeting_state
    lead.flow_state = state


def start(lead, config: dict, sales: dict) -> dict:
    """Customer asked where to come — send address, hours, and the first closed question."""
    state = flow(lead)
    state["step"] = STEP_TODAY
    _save(lead, state)
    return {
        "address": True,
        "address_text": sales.get("office_address", ""),
        "hours_text": sales.get("office_hours", ""),
        "meeting_prompt": "Вам удобно подъехать сегодня?",
    }


def advance(lead, signals: set[str], meta: dict, now: dt.datetime, config: dict) -> dict:
    """Move one step down the ladder based on what the customer just answered."""
    state = flow(lead)
    step = state.get("step", STEP_NONE)
    result: dict = {}

    if step == STEP_TODAY:
        if "affirmative" in signals or meta.get("day_part"):
            state["date"] = now.date().isoformat()
            if meta.get("day_part"):
                state["day_part"] = meta["day_part"]
                state["step"] = STEP_TIME
                result["meeting_prompt"] = _time_prompt(meta["day_part"], config)
            else:
                state["step"] = STEP_DAY_PART
                result["meeting_prompt"] = (
                    "Отлично! Вам удобнее в первой половине дня или во второй?"
                )
        elif "negative_answer" in signals or "week_part_answer" in signals:
            state["step"] = STEP_WEEK_PART
            if meta.get("week_part"):
                state["week_part"] = meta["week_part"]
                state["step"] = STEP_WEEKDAY
                result["meeting_prompt"] = _weekday_prompt(meta["week_part"], now)
            else:
                result["meeting_prompt"] = "Хорошо. Вам удобнее в будни или в выходные?"

    elif step == STEP_DAY_PART:
        if meta.get("day_part"):
            state["day_part"] = meta["day_part"]
            state["step"] = STEP_TIME
            result["meeting_prompt"] = _time_prompt(meta["day_part"], config)
        elif meta.get("time"):
            pass  # falls through to the time handler below

    elif step == STEP_WEEK_PART:
        if meta.get("week_part"):
            state["week_part"] = meta["week_part"]
            state["step"] = STEP_WEEKDAY
            result["meeting_prompt"] = _weekday_prompt(meta["week_part"], now)

    elif step == STEP_WEEKDAY:
        weekday = _match_weekday(meta.get("text", ""))
        if weekday is not None:
            target = _next_weekday(now, weekday)
            state["date"] = target.date().isoformat()
            state["step"] = STEP_TIME
            result["meeting_prompt"] = (
                f"Записал на {WEEKDAY_NAMES[weekday]}. В какое время вам удобно?"
            )

    # a concrete time closes the ladder from any step
    if meta.get("time") and step in (STEP_DAY_PART, STEP_TIME, STEP_WEEKDAY, STEP_TODAY):
        state["time"] = meta["time"]
        if not state.get("date"):
            state["date"] = now.date().isoformat()
        state["step"] = STEP_DONE
        result.pop("meeting_prompt", None)
        result["confirmed_at"] = _combine(state, now, config)

    _save(lead, state)
    return result


def _time_prompt(day_part: str, config: dict) -> str:
    if day_part == "morning":
        return (
            f"Принял, первая половина дня. Мы открываемся в {config.get('office_open', '10:00')} — "
            "во сколько вас ждать?"
        )
    return (
        f"Принял, вторая половина. Работаем до {config.get('office_close', '21:00')} — "
        "на какое время вас записать?"
    )


def _weekday_prompt(week_part: str, now: dt.datetime) -> str:
    if week_part == "weekend":
        return "Хорошо, в выходные. Суббота или воскресенье вам удобнее?"
    return "Хорошо, в будни. Какой день недели вам подходит?"


def _match_weekday(text: str) -> int | None:
    low = (text or "").lower()
    for token, index in WEEKDAY_TOKENS.items():
        if token in low:
            return index
    return None


def _next_weekday(now: dt.datetime, weekday: int) -> dt.datetime:
    delta = (weekday - now.weekday()) % 7
    delta = delta or 7
    return now + dt.timedelta(days=delta)


def _combine(state: dict, now: dt.datetime, config: dict) -> dt.datetime:
    date_str = state.get("date") or now.date().isoformat()
    time_str = state.get("time") or (
        "12:00" if state.get("day_part") == "morning" else "17:00"
    )
    try:
        date = dt.date.fromisoformat(date_str)
    except ValueError:
        date = now.date()
    scheduled = dt.datetime.combine(date, parse_hhmm(time_str, (12, 0)))
    if scheduled <= now:
        scheduled += dt.timedelta(days=1)
    return scheduled


def current_prompt(lead, config: dict) -> str:
    """The question the ladder is currently waiting on.

    Used when the customer replies with something that does not advance the
    booking — the assistant repeats the open question instead of going silent.
    """
    state = flow(lead)
    step = state.get("step", "")
    if step == STEP_TODAY:
        return "Вам удобно подъехать сегодня?"
    if step == STEP_DAY_PART:
        return "Вам удобнее в первой половине дня или во второй?"
    if step == STEP_WEEK_PART:
        return "Вам удобнее в будни или в выходные?"
    if step == STEP_WEEKDAY:
        return "Какой день недели вам подходит?"
    if step == STEP_TIME:
        return _time_prompt(state.get("day_part", "afternoon"), config)
    return ""


def confirmation_text(scheduled: dt.datetime, address: str) -> str:
    return (
        f"Записал вас на {scheduled.strftime('%d.%m')} в {scheduled.strftime('%H:%M')}, "
        f"адрес: {address}. Перед визитом напомню."
    )


def reminder_plan(scheduled: dt.datetime, config: dict) -> list[tuple[dt.datetime, str, str]]:
    """(when, rule, text) triples for the three reminders required by §11."""
    plan: list[tuple[dt.datetime, str, str]] = []
    if config.get("reminder_day_before", True):
        plan.append(
            (
                scheduled - dt.timedelta(days=1),
                "day_before",
                f"Напоминаю о встрече завтра в {scheduled.strftime('%H:%M')}. "
                "Всё в силе?",
            )
        )
    morning_hour = int(config.get("reminder_morning_hour", 9))
    morning = dt.datetime.combine(scheduled.date(), dt.time(morning_hour, 0))
    if morning < scheduled:
        plan.append(
            (
                morning,
                "morning",
                f"Доброе утро! Ждём вас сегодня в {scheduled.strftime('%H:%M')}.",
            )
        )
    hours_before = int(config.get("reminder_hours_before", 1))
    plan.append(
        (
            scheduled - dt.timedelta(hours=hours_before),
            "hour_before",
            f"Через час ждём вас — {scheduled.strftime('%H:%M')}. Если планы поменялись, напишите.",
        )
    )
    return plan
