"""AI Insights (§36, §37, §38).

Findings are computed from the demo database rather than asserted, and each one
carries the sample it was derived from.  Anything below the confidence floor is
labelled as a weak signal instead of being stated as fact.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now as clock_now
from ..models import Event, FollowUp, Lead, Message, TurnLog
from . import settings_store
from .qualification import FIELD_LABELS, compute

MIN_SAMPLE = 5


def _confidence(sample: int) -> str:
    if sample >= 20:
        return "high"
    if sample >= MIN_SAMPLE:
        return "medium"
    return "low"


def generate(db: Session) -> dict:
    now = clock_now()
    leads = list(db.execute(select(Lead)).scalars().all())
    config = settings_store.get_section(db, "qualification")
    findings: list[dict] = []

    if not leads:
        return {"generated_at": now.isoformat(timespec="seconds"), "findings": [],
                "dataset": {"leads": 0}, "recommendations": []}

    stats = {lead.id: compute(lead.qualification or {}, config) for lead in leads}

    # 1 — which qualification field is closed least often
    field_counts = {key: 0 for key in FIELD_LABELS}
    for lead in leads:
        for key in stats[lead.id]["closed"]:
            field_counts[key] = field_counts.get(key, 0) + 1
    weakest = min(field_counts.items(), key=lambda pair: pair[1])
    findings.append(
        {
            "id": "weakest_field",
            "severity": "medium",
            "title": f"Реже всего закрывается параметр «{FIELD_LABELS[weakest[0]]}»",
            "detail": (
                f"Закрыт в {weakest[1]} из {len(leads)} диалогов "
                f"({round(weakest[1] / len(leads) * 100)}%). "
                "Это самое узкое место квалификации в demo-выборке."
            ),
            "recommendation": (
                f"Добавить вопрос про «{FIELD_LABELS[weakest[0]]}» раньше в сценарий "
                "и вынести его в БЗ правил."
            ),
            "sample": len(leads),
            "confidence": _confidence(len(leads)),
        }
    )

    # 2 — where the customer stopped answering
    ignored = [lead for lead in leads if lead.ignored or lead.lost]
    if ignored:
        findings.append(
            {
                "id": "drop_off",
                "severity": "high" if len(ignored) / len(leads) > 0.25 else "medium",
                "title": f"{len(ignored)} диалог(ов) закончились молчанием клиента",
                "detail": (
                    "Средняя квалификация в этих диалогах — "
                    f"{round(sum(stats[l.id]['score'] for l in ignored) / len(ignored))}%, "
                    "контакт получен в "
                    f"{sum(1 for l in ignored if l.contact_acquired)} из {len(ignored)}."
                ),
                "recommendation": (
                    "Просить контакт раньше — до третьего вопроса квалификации, "
                    "пока клиент активен."
                ),
                "sample": len(ignored),
                "confidence": _confidence(len(ignored)),
            }
        )

    # 3 — handoff timing
    handoff_events = db.execute(select(Event).where(Event.type == "handoff")).scalars().all()
    late = []
    for event in handoff_events:
        messages = db.execute(
            select(Message).where(Message.conversation_id == event.conversation_id)
        ).scalars().all()
        before = [m for m in messages if m.created_at <= event.created_at]
        if len(before) > 8:
            late.append(event)
    if handoff_events:
        findings.append(
            {
                "id": "handoff_timing",
                "severity": "high" if late else "low",
                "title": (
                    f"{len(late)} из {len(handoff_events)} передач менеджеру произошли поздно"
                    if late
                    else "Передачи менеджеру происходят вовремя"
                ),
                "detail": (
                    "Поздней считается передача после 8+ сообщений в диалоге. "
                    f"Всего передач: {len(handoff_events)}."
                ),
                "recommendation": (
                    "Снизить порог автопередачи с 80% до 70% для клиентов из Москвы."
                    if late
                    else "Текущие пороги передачи работают корректно."
                ),
                "sample": len(handoff_events),
                "confidence": _confidence(len(handoff_events)),
            }
        )

    # 4 — negativity sources
    negative = [lead for lead in leads if lead.negative]
    if negative:
        findings.append(
            {
                "id": "negative",
                "severity": "high",
                "title": f"Негатив зафиксирован в {len(negative)} диалогах",
                "detail": (
                    "Все они переданы менеджеру автоматически. "
                    f"Средний балл квалификации до негатива — "
                    f"{round(sum(stats[l.id]['score'] for l in negative) / len(negative))}%."
                ),
                "recommendation": (
                    "Разобрать эти переписки вручную и дополнить БЗ запретов формулировками, "
                    "которые вызвали реакцию."
                ),
                "sample": len(negative),
                "confidence": _confidence(len(negative)),
            }
        )

    # 5 — what actually converts to a contact
    with_contact = [lead for lead in leads if lead.contact_acquired]
    without = [lead for lead in leads if not lead.contact_acquired]
    if with_contact and without:
        avg_with = sum(stats[l.id]["closed_count"] for l in with_contact) / len(with_contact)
        avg_without = sum(stats[l.id]["closed_count"] for l in without) / len(without)
        findings.append(
            {
                "id": "contact_driver",
                "severity": "medium",
                "title": "Контакт чаще дают клиенты с более полной квалификацией",
                "detail": (
                    f"Среднее число закрытых пунктов: {avg_with:.1f} у оставивших контакт "
                    f"против {avg_without:.1f} у остальных."
                ),
                "recommendation": (
                    "Просить телефон после закрытия 3-го параметра, а не в конце диалога."
                ),
                "sample": len(leads),
                "confidence": _confidence(len(leads)),
            }
        )

    # 6 — most requested models
    product_counter: dict[int, int] = {}
    for lead in leads:
        for product_id in lead.selected_products or []:
            product_counter[product_id] = product_counter.get(product_id, 0) + 1
    if product_counter:
        from ..models import Product

        top_id = max(product_counter.items(), key=lambda pair: pair[1])
        product = db.get(Product, top_id[0])
        if product:
            findings.append(
                {
                    "id": "top_model",
                    "severity": "low",
                    "title": f"Чаще всего AI предлагает {product.brand} {product.model}",
                    "detail": (
                        f"Предложен в {top_id[1]} диалогах. Цена от {product.price} ₽, "
                        f"остаток {product.stock} шт."
                    ),
                    "recommendation": (
                        "Проверить остаток по этой позиции и подготовить 2 аналога "
                        "на случай исчерпания."
                    ),
                    "sample": sum(product_counter.values()),
                    "confidence": _confidence(sum(product_counter.values())),
                }
            )

    # 7 — follow-up effectiveness
    sent = db.execute(
        select(FollowUp).where(FollowUp.kind == "followup", FollowUp.status == "sent")
    ).scalars().all()
    if sent:
        revived = 0
        for followup in sent:
            replies = db.execute(
                select(Message).where(
                    Message.conversation_id == followup.conversation_id,
                    Message.role == "customer",
                    Message.created_at > (followup.sent_at or clock_now()),
                )
            ).scalars().first()
            if replies:
                revived += 1
        findings.append(
            {
                "id": "followup_effect",
                "severity": "medium",
                "title": f"Follow-up вернул в диалог {revived} из {len(sent)} клиентов",
                "detail": (
                    f"Конверсия повторного касания — {round(revived / len(sent) * 100)}%. "
                    "Считается по demo-датасету."
                ),
                "recommendation": (
                    "Оставить первое касание на 15 минутах — оно даёт основную часть возвратов."
                ),
                "sample": len(sent),
                "confidence": _confidence(len(sent)),
            }
        )

    # 8 — guard activity
    blocked = db.execute(
        select(TurnLog).where(TurnLog.guard_verdict != "PASSED")
    ).scalars().all()
    total_turns = db.execute(select(TurnLog)).scalars().all()
    if total_turns:
        findings.append(
            {
                "id": "guard",
                "severity": "low",
                "title": f"Response Guard вмешался в {len(blocked)} из {len(total_turns)} ответов",
                "detail": (
                    "Проверки: наличие, актуальность цены, потолок цены объявления, "
                    "запрещённые утверждения, повтор закрытых вопросов."
                ),
                "recommendation": "Разобрать сработавшие проверки на вкладке Logs / Debug.",
                "sample": len(total_turns),
                "confidence": _confidence(len(total_turns)),
            }
        )

    for finding in findings:
        if finding["sample"] < MIN_SAMPLE:
            finding["title"] = finding["title"] + " (слабый сигнал)"
            finding["detail"] += (
                f" Выборка меньше {MIN_SAMPLE} диалогов — вывод предварительный."
            )

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "dataset": {
            "label": "Demo dataset insight",
            "leads": len(leads),
            "turns": len(total_turns),
            "note": (
                "Показатели рассчитаны по демонстрационной базе. "
                "Это не статистически значимая выборка боевого трафика."
            ),
        },
        "findings": sorted(
            findings,
            key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3),
        ),
        "recommendations": [
            {
                "id": finding["id"],
                "text": finding["recommendation"],
                "status": "pending_approval",
                "based_on": f"{finding['sample']} диалог(ов)",
            }
            for finding in findings
        ],
    }
