"""Turn orchestrator.

One customer message flows through here:

    extract → merge state → score → handoff rules → inventory → build plan →
    LLM writes → response guard → persist → CRM mutations → follow-up scheduling
    → event + turn log

Everything the Logs/Debug screen shows is captured on the way through, and the
Live Intelligence panel is just a projection of the state this function writes.
"""
from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import crm as crm_adapter
from ..adapters import inventory as inventory_adapter
from ..adapters import media as media_adapter
from ..clock import now as clock_now
from ..llm.base import LLMMessage, ReplyContext
from ..llm.factory import get_provider
from ..models import Conversation, Event, Lead, Meeting, Message, Product, TurnLog
from . import crm as crm_controller
from . import followup as followup_engine
from . import guard as guard_module
from . import handoff as handoff_engine
from . import kb as kb_module
from . import managers as manager_engine
from . import meeting as meeting_controller
from . import product_expert, qualification, settings_store
from .extractor import TASK_LABELS, extract, style_profile


@dataclass
class TurnResult:
    reply: str | None = None
    messages: list[Message] = field(default_factory=list)
    log: TurnLog | None = None
    mutations: list[dict] = field(default_factory=list)
    handoff: dict = field(default_factory=dict)
    suppressed: str = ""


# --- entry points ------------------------------------------------------------


def handle_customer_message(
    db: Session, conversation: Conversation, text: str, *, mark_read: bool = True
) -> TurnResult:
    now = clock_now()
    lead = _ensure_lead(db, conversation, now)

    inbound = Message(
        role="customer",
        text=text,
        created_at=now,
        read_at=now,
        author=conversation.customer.name,
        meta={},
    )
    conversation.messages.append(inbound)
    db.add(inbound)
    conversation.last_message_at = now
    if conversation.started_at is None:
        conversation.started_at = now
    db.flush()

    db.add(
        Event(
            type="message_in",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={"chars": len(text)},
            created_at=now,
        )
    )
    followup_engine.cancel_pending(db, conversation.id, "клиент ответил")

    if mark_read:
        # the customer answering implies they read what we sent
        for message in conversation.messages:
            if message.role in ("ai", "manager") and message.read_at is None:
                message.read_at = now
        conversation.last_customer_read_at = now

    result = _run_turn(db, conversation, lead, inbound, now)
    db.flush()
    return result


def record_manager_message(db: Session, conversation: Conversation, text: str, author: str) -> Message:
    """A human wrote in the chat → the AI goes quiet for the configured window (§29)."""
    now = clock_now()
    lead = _ensure_lead(db, conversation, now)
    config = settings_store.get_section(db, "handoff")
    silence = int(config.get("ai_silence_minutes", 30))

    message = Message(
        role="manager",
        text=text,
        created_at=now,
        author=author,
        meta={},
    )
    conversation.messages.append(message)
    db.add(message)
    conversation.mode = "human"
    conversation.ai_silent_until = now + dt.timedelta(minutes=silence)
    conversation.last_message_at = now
    db.add(
        Event(
            type="human_message",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={"author": author, "ai_silent_minutes": silence},
            created_at=now,
        )
    )
    followup_engine.cancel_pending(db, conversation.id, "чат ведёт менеджер")
    db.flush()
    return message


def set_mode(db: Session, conversation: Conversation, mode: str, actor: str = "admin") -> None:
    now = clock_now()
    config = settings_store.get_section(db, "handoff")
    conversation.mode = mode
    if mode == "human":
        conversation.ai_silent_until = now + dt.timedelta(
            minutes=int(config.get("ai_silence_minutes", 30))
        )
        conversation.status = "handoff"
        followup_engine.cancel_pending(db, conversation.id, "менеджер забрал чат")
    else:
        conversation.ai_silent_until = None
        conversation.status = "active"
    db.add(
        Event(
            type="mode_changed",
            conversation_id=conversation.id,
            lead_id=conversation.lead.id if conversation.lead else None,
            payload={"mode": mode, "actor": actor},
            created_at=now,
        )
    )
    db.flush()


# --- the turn itself ---------------------------------------------------------


def _run_turn(
    db: Session, conversation: Conversation, lead: Lead, inbound: Message, now: dt.datetime
) -> TurnResult:
    configs = settings_store.get_all(db)
    qual_config = configs["qualification"]
    handoff_config = configs["handoff"]
    followup_config = configs["followup"]
    meeting_config = configs["meeting"]
    style_config = configs["ai_style"]
    sales_config = configs["sales"]

    inventory = inventory_adapter(db)
    crm = crm_adapter(db)

    # 1 — understand ----------------------------------------------------------
    extraction = extract(inbound.text)
    extraction.meta["text"] = inbound.text
    qual_state = dict(lead.qualification or {})
    changed_fields = qualification.merge(qual_state, extraction)
    lead.qualification = qual_state  # re-assigned so SQLAlchemy sees the mutation
    stats = qualification.compute(lead.qualification, qual_config)

    if extraction.meta.get("phone") and not lead.contact_phone:
        lead.contact_phone = extraction.meta["phone"]
        lead.contact_acquired = True
        lead.customer.phone = extraction.meta["phone"]
        db.add(
            Event(
                type="contact_acquired",
                conversation_id=conversation.id,
                lead_id=lead.id,
                payload={"phone": lead.contact_phone},
                created_at=now,
            )
        )

    signals = set(extraction.signals)
    if "negative" in signals:
        lead.negative = True
        lead.sentiment = "negative"
    elif lead.sentiment != "negative":
        lead.sentiment = "positive" if {"affirmative", "hot_intent"} & signals else "neutral"

    # 2 — rules ---------------------------------------------------------------
    decision = handoff_engine.evaluate(signals, stats, handoff_config)
    rules_triggered = list(decision.triggered)
    if changed_fields:
        rules_triggered.append(f"qualification_updated:{','.join(changed_fields)}")

    handoff_fresh = decision.required and not lead.handoff_required
    if decision.required:
        lead.handoff_required = True
        lead.handoff_reason = decision.reason
        lead.handoff_kind = decision.kind
        if lead.handoff_at is None:
            lead.handoff_at = now

    # 3 — is the AI even allowed to answer? -----------------------------------
    human_active = conversation.mode == "human" or (
        conversation.ai_silent_until is not None and conversation.ai_silent_until > now
    )

    if handoff_fresh:
        _perform_handoff(db, conversation, lead, decision, handoff_config, now)

    if human_active:
        _finish_state(db, lead, stats, signals, now)
        log = _write_log(
            db, conversation, inbound, None, extraction, rules_triggered, [], [], [], {},
            [], [], decision, "", provider="-", model="-", latency=0,
            verdict="SKIPPED", error="AI молчит: чат ведёт менеджер",
        )
        return TurnResult(reply=None, log=log, handoff=decision.as_dict(),
                          suppressed="human_active")

    if decision.blocks_ai:
        # AI acknowledges the handoff politely, then stops writing
        plan = {
            "handoff_notice": _handoff_notice(decision, lead),
            "service_notice": decision.kind == "service",
            "style": _style(db, conversation, style_config),
            "seed": len(conversation.messages),
        }
        reply_text = get_provider().generate(
            ReplyContext(system=_system_prompt(db, lead, plan, sales_config, [], []),
                         messages=_history(conversation), plan=plan)
        )
        outbound = _persist_reply(db, conversation, reply_text.text, now, meta={"handoff": True})
        conversation.mode = "human"
        conversation.ai_silent_until = now + dt.timedelta(
            minutes=int(handoff_config.get("ai_silence_minutes", 30))
        )
        conversation.status = "handoff"
        _finish_state(db, lead, stats, signals, now)
        log = _write_log(
            db, conversation, inbound, outbound, extraction, rules_triggered, [], [], [], {},
            [], [], decision, decision.reason, provider=reply_text.provider,
            model=reply_text.model, latency=reply_text.latency_ms, verdict="PASSED",
        )
        return TurnResult(reply=outbound.text, messages=[outbound], log=log,
                          handoff=decision.as_dict())

    # 4 — build the reply plan ------------------------------------------------
    # snapshot: if the guard blocks the reply, nothing was actually said, so the
    # dialogue state it would have advanced (address sent, meeting step, offers
    # shown) has to be rolled back.
    flow_snapshot = copy.deepcopy(lead.flow_state or {})
    plan, offers, inventory_snapshot, products_queried, unfit = _build_plan(
        db, conversation, lead, extraction, stats, signals, decision, now,
        inventory, configs,
    )

    kb_fragments = kb_module.retrieve(
        db,
        tasks=qualification.tasks_list(lead.qualification),
        signals=signals,
        product_types=sorted({o.get("type", "laptop") for o in offers}),
    )

    # 5 — write ---------------------------------------------------------------
    provider = get_provider()
    system = _system_prompt(db, lead, plan, sales_config, offers, kb_fragments)
    ctx = ReplyContext(system=system, messages=_history(conversation), plan=plan)
    generated = provider.generate(ctx)

    # 6 — guard ---------------------------------------------------------------
    guard_ctx = _guard_context(
        db, conversation, lead, offers, stats, decision, signals, sales_config,
        generated.text, unfit, referenced_ids=plan.get("_referenced_ids") or [],
    )
    report = guard_module.run(generated.text, guard_ctx)

    outbound = _persist_reply(
        db, conversation, report.text, now,
        meta={"guard": report.verdict, "offers": [o["id"] for o in offers]},
    )

    # 7 — post-effects --------------------------------------------------------
    if report.blocked:
        lead.flow_state = flow_snapshot

    if offers and not report.blocked:
        lead.selected_products = [o["id"] for o in offers]
        state = dict(lead.flow_state or {})
        state["offers_shown"] = list(
            dict.fromkeys((state.get("offers_shown") or []) + [o["id"] for o in offers])
        )
        lead.flow_state = state
        db.add(
            Event(
                type="products_offered",
                conversation_id=conversation.id,
                lead_id=lead.id,
                payload={"products": [o["sku"] for o in offers]},
                created_at=now,
            )
        )

    if plan.get("address") and not report.blocked:
        lead.invited_to_office = True

    confirmed_at = plan.get("_meeting_confirmed_at") if not report.blocked else None
    if confirmed_at:
        _create_meeting(db, conversation, lead, confirmed_at, sales_config, meeting_config, now)

    mutations = _finish_state(db, lead, stats, signals, now)
    crm.upsert_lead(lead.id, {})

    if lead.first_response_seconds is None:
        delta = (outbound.created_at - (conversation.started_at or outbound.created_at)).total_seconds()
        lead.first_response_seconds = max(0, int(delta))

    followup_engine.schedule(db, conversation, lead, 1, now, followup_config)

    log = _write_log(
        db, conversation, inbound, outbound, extraction, rules_triggered, kb_fragments,
        products_queried, inventory_snapshot, report.price_validation,
        [c.as_dict() for c in report.checks], mutations, decision,
        decision.reason if decision.required else "",
        provider=generated.provider, model=generated.model, latency=generated.latency_ms,
        verdict=report.verdict, error=generated.error,
    )

    db.add(
        Event(
            type="ai_reply",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={"guard": report.verdict, "score": lead.score, "chars": len(outbound.text)},
            created_at=now,
        )
    )
    return TurnResult(reply=outbound.text, messages=[outbound], log=log,
                      mutations=mutations, handoff=decision.as_dict())


# --- plan construction -------------------------------------------------------


def _build_plan(
    db, conversation, lead, extraction, stats, signals, decision, now, inventory, configs
):
    """Decide what this one reply should accomplish.

    A turn has a single primary job.  Stacking offers + address + questions +
    contact request into one message is what makes an assistant read like a bot,
    so the blocks below are mutually exclusive by design (§14: no "полотно").
    """
    sales_config = configs["sales"]
    style_config = configs["ai_style"]
    meeting_config = configs["meeting"]

    flow_state = dict(lead.flow_state or {})
    turn_index = len([m for m in conversation.messages if m.role == "customer"])
    plan: dict = {
        "style": _style(db, conversation, style_config),
        "seed": turn_index,
    }
    offers: list[dict] = []
    inventory_snapshot: list[dict] = []
    products_queried: list[dict] = []
    unfit: list[str] = []

    # --- greeting mirroring (§14) -------------------------------------------
    if "greeting" in signals and not flow_state.get("greeted"):
        greeting = extraction.meta.get("greeting", "здравствуйте")
        plan["greeting"] = (
            "привет" if greeting in ("привет", "хай", "ку", "здорово") else "здравствуйте"
        )
        flow_state["greeted"] = True

    # --- photo/video: manager joins, AI keeps working (§21) ------------------
    if decision.involve_only and decision.code == "photo":
        plan["photo_notice"] = True
        first_sku = ""
        if lead.selected_products:
            first = inventory.get(lead.selected_products[0])
            first_sku = first.sku if first else ""
        media_adapter().request_upload(first_sku or "—", conversation.customer.name)

    # --- what has the customer named, now or earlier? ------------------------
    # A model named two turns ago is still the model they are asking about, so
    # interest accumulates instead of being re-derived from the latest message.
    mentioned = product_expert.find_mentioned(inventory, extraction.meta.get("text", ""))
    interest_ids = list(
        dict.fromkeys((flow_state.get("interest_ids") or []) + [i.id for i in mentioned])
    )[-5:]
    flow_state["interest_ids"] = interest_ids
    addressed = set(flow_state.get("addressed_ids") or [])

    candidates = list(mentioned)
    known_ids = {i.id for i in candidates}
    for product_id in interest_ids:
        if product_id in known_ids or product_id in addressed:
            continue
        item = inventory.get(product_id)
        if item:
            candidates.append(item)

    referenced_ids: list[int] = [i.id for i in candidates]
    for item in candidates:
        products_queried.append(
            {"sku": item.sku, "title": item.title, "reason": "упомянут клиентом"}
        )
        inventory_snapshot.append(
            {"sku": item.sku, "title": item.title, "stock": item.stock, "price": item.price}
        )

    tasks = qualification.tasks_list(lead.qualification)
    zone = stats.get("zone")
    max_offers = int(sales_config.get("max_offers", 3))

    # --- 1. out of stock (§22) ----------------------------------------------
    unavailable = [i for i in candidates if not i.in_stock and i.id not in addressed]
    if unavailable:
        item = unavailable[0]
        alternatives = product_expert.alternatives_for(
            inventory, lead.qualification, [i.id for i in candidates], limit=max_offers
        )
        plan["out_of_stock"] = {
            "sku": item.sku, "title": item.title, "alternatives": bool(alternatives),
        }
        offers = [o.as_dict() for o in alternatives]
        addressed.add(item.id)

    # --- 2. the choice does not fit the job (§17) ----------------------------
    if not offers:
        for item in candidates:
            if item.id in addressed:
                continue
            report = product_expert.mismatch_report(item, lead.qualification)
            if report:
                plan["mismatch"] = report
                unfit.append(f"{item.title} — не подходит под {report['task_label']}")
                alternatives = product_expert.alternatives_for(
                    inventory, lead.qualification, [item.id], limit=max_offers
                )
                offers = [o.as_dict() for o in alternatives]
                addressed.add(item.id)
                break

    # --- 3. proactive selection (§19) ---------------------------------------
    wants_selection = "selection_request" in signals
    can_propose = bool(tasks) and (
        qualification.budget_value(lead.qualification) is not None
        or qualification.requirements_dict(lead.qualification).get("brand")
    )
    shown = list(flow_state.get("offers_shown") or [])
    # a new round is justified when the brief actually changed
    brief_changed = bool(
        {"tasks", "budget", "requirements"} & set(extraction.fields.keys())
    )
    should_offer = not offers and (
        wants_selection or (can_propose and (not shown or brief_changed))
    )

    if should_offer:
        missing = stats["missing"]
        if wants_selection and len(missing) >= 3 and not flow_state.get("selection_intro"):
            plan["intro_selection"] = True
            flow_state["selection_intro"] = True
        if can_propose or len(missing) <= 2:
            ranked, query_info = product_expert.search_ranked(
                inventory, lead.qualification, limit=max_offers
            )
            products_queried.append({"query": query_info, "found": query_info.get("found", 0)})
            if query_info.get("widened") == "brand":
                plan["widened_brand"] = True
            # don't repeat an identical shortlist
            if not (shown and [o.item.id for o in ranked] == shown):
                offers = [o.as_dict() for o in ranked]

    if offers:
        plan["offers"] = offers
        inventory_snapshot.extend(
            {"sku": o["sku"], "title": o["title"], "stock": o["stock"], "price": o["price"]}
            for o in offers
        )
        ranked_objects = []
        for offer in offers:
            item = inventory.get(offer["id"])
            if item:
                ranked_objects.append(
                    product_expert.Offer(item=item, score=offer["score"], why=offer["why"])
                )
        note = product_expert.differences_note(ranked_objects, lead.qualification)
        if note:
            plan["offers_note"] = note

    # --- 4. price question (§23) --------------------------------------------
    if "price_request" in signals and not offers and mentioned:
        plan["price_answer"] = [
            {"title": i.title, "price": i.price} for i in mentioned if i.in_stock
        ][:2]

    # --- 5. meeting ladder (§10) --------------------------------------------
    meeting_step = (flow_state.get("meeting") or {}).get("step", "")
    meeting_active = False

    if "address_request" in signals and meeting_step in ("", meeting_controller.STEP_DONE):
        lead.flow_state = flow_state
        plan.update(meeting_controller.start(lead, meeting_config, sales_config))
        flow_state = dict(lead.flow_state or {})
        meeting_active = True
    elif meeting_step and meeting_step != meeting_controller.STEP_DONE:
        lead.flow_state = flow_state
        step_result = meeting_controller.advance(
            lead, signals, extraction.meta, now, meeting_config
        )
        flow_state = dict(lead.flow_state or {})
        if step_result.get("meeting_prompt"):
            plan["meeting_prompt"] = step_result["meeting_prompt"]
            meeting_active = True
        if step_result.get("confirmed_at"):
            plan["_meeting_confirmed_at"] = step_result["confirmed_at"]
            plan["meeting_confirmed"] = meeting_controller.confirmation_text(
                step_result["confirmed_at"], sales_config.get("office_address", "")
            )
            meeting_active = True
        if not step_result:
            # the answer did not move the ladder — repeat the open question
            pending = meeting_controller.current_prompt(lead, meeting_config)
            if pending:
                plan["meeting_prompt"] = pending
                meeting_active = True
                if "address_request" in signals:
                    plan["address"] = True
                    plan["address_text"] = sales_config.get("office_address", "")
                    plan["hours_text"] = sales_config.get("office_hours", "")

    # invite a warm nearby customer to the office — but not in the same breath
    # as a product shortlist
    if (
        not meeting_active
        and not offers
        and not meeting_step
        and zone in ("msk", "mo")
        and stats["score"] >= 50
        and not lead.meeting_scheduled
        and not flow_state.get("office_invited")
    ):
        plan["address"] = True
        plan["address_text"] = sales_config.get("office_address", "")
        plan["hours_text"] = sales_config.get("office_hours", "")
        plan["meeting_prompt"] = "Вам удобно подъехать сегодня?"
        state = dict(lead.flow_state or {})
        state.setdefault("meeting", {})["step"] = meeting_controller.STEP_TODAY
        lead.flow_state = state
        flow_state = dict(lead.flow_state or {})
        flow_state["office_invited"] = True
        meeting_active = True

    # --- 6. acknowledgement --------------------------------------------------
    known = qualification.humanize(lead.qualification)
    fresh = [k for k in extraction.fields if known.get(k)]
    substantial = [k for k in fresh if k in ("tasks", "budget", "geo", "timeframe")]
    if len(fresh) >= 2 or (len(fresh) == 1 and substantial):
        plan["acknowledge"] = "Понял: " + ", ".join(known[k] for k in fresh[:4]) + "."

    # --- 7. questions — never twice for the same parameter (§25, §45.5) ------
    asked = set(flow_state.get("asked_fields") or [])
    if not meeting_active and not plan.get("photo_notice"):
        pending = [key for key in stats["missing"] if key not in asked]
        questions = qualification.missing_questions(pending, lead.qualification)
        if questions:
            limit = 1 if (offers or plan.get("acknowledge")) else 2
            if plan.get("intro_selection"):
                limit = 2
            chosen_fields = pending[:limit]
            plan["questions"] = questions[:limit]
            asked.update(chosen_fields)
    flow_state["asked_fields"] = sorted(asked)
    flow_state["addressed_ids"] = sorted(addressed)
    plan["_referenced_ids"] = referenced_ids

    # --- 8. region delivery --------------------------------------------------
    if zone == "region" and stats["closed_count"] >= 2 and not flow_state.get("delivery_noted"):
        plan["delivery_note"] = (
            f"По доставке: отправляем {sales_config.get('delivery_regions', '')}. "
            "Перед отправкой пришлём фото и видео именно вашего экземпляра."
        )
        flow_state["delivery_noted"] = True

    # --- 9. contact (§7) -----------------------------------------------------
    contact_asked_turn = flow_state.get("contact_asked_turn")
    contact_due = (
        not lead.contact_phone
        and not offers
        and (
            plan.get("_meeting_confirmed_at")
            or plan.get("delivery_note")
            or stats["score"] >= 50
            or "hot_intent" in signals
        )
    )
    if contact_due and (contact_asked_turn is None or turn_index - contact_asked_turn >= 3):
        plan["ask_contact"] = True
        flow_state["contact_asked_turn"] = turn_index

    if "contact_given" in signals and lead.contact_phone:
        plan["closing"] = (
            f"Записал номер {lead.contact_phone} — менеджер свяжется с вами и подтвердит детали."
        )
        plan.pop("ask_contact", None)

    # --- 10. promo + handoff notice, each said once --------------------------
    if (
        sales_config.get("promo_enabled")
        and (plan.get("_meeting_confirmed_at") or plan.get("address"))
        and not flow_state.get("promo_sent")
    ):
        plan["promo"] = sales_config.get("promo_code")
        flow_state["promo_sent"] = True

    if (
        decision.required
        and not decision.blocks_ai
        and decision.code in ("threshold", "region")
        and not flow_state.get("handoff_announced")
    ):
        plan["closing"] = (
            "Передаю ваш запрос менеджеру — он свяжется с вами в ближайшие минуты "
            "и подтвердит детали."
        )
        flow_state["handoff_announced"] = True

    lead.flow_state = flow_state
    return plan, offers, inventory_snapshot, products_queried, unfit

# --- helpers -----------------------------------------------------------------


def _ensure_lead(db: Session, conversation: Conversation, now: dt.datetime) -> Lead:
    if conversation.lead:
        return conversation.lead
    # the relationship can be stale within a transaction — check the table too
    existing = db.execute(
        select(Lead).where(Lead.conversation_id == conversation.id)
    ).scalars().first()
    if existing:
        conversation.lead = existing
        return existing
    lead = Lead(
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        qualification={},
        flow_state={},
        selected_products=[],
        created_at=now,
        updated_at=now,
    )
    db.add(lead)
    db.flush()
    conversation.lead = lead  # keep the loaded relationship in sync
    db.add(
        Event(
            type="lead_created",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={"customer": conversation.customer.name},
            created_at=now,
        )
    )
    return lead


def _style(db, conversation, style_config: dict) -> dict:
    customer_messages = [m.text for m in conversation.messages if m.role == "customer"]
    profile = style_profile(customer_messages)
    if not style_config.get("mirror_customer_style", True):
        profile["length"] = style_config.get("verbosity", "short")
        profile["formal"] = style_config.get("tone") == "formal"
    profile["emoji"] = bool(style_config.get("emoji")) or profile.get("emoji")
    profile["verbosity"] = style_config.get("verbosity", "short")
    return profile


def _history(conversation: Conversation, limit: int = 16) -> list[LLMMessage]:
    out: list[LLMMessage] = []
    for message in conversation.messages[-limit:]:
        if message.role == "customer":
            out.append(LLMMessage("user", message.text))
        elif message.role in ("ai", "manager"):
            out.append(LLMMessage("assistant", message.text))
    if not out or out[-1].role != "user":
        out.append(LLMMessage("user", "(продолжай диалог)"))
    return out


def _persist_reply(db, conversation, text: str, now: dt.datetime, meta: dict) -> Message:
    message = Message(
        role="ai",
        text=text,
        created_at=now,
        author="AI",
        meta=meta,
    )
    conversation.messages.append(message)
    db.add(message)
    conversation.last_message_at = now
    db.flush()
    return message


def _handoff_notice(decision, lead) -> str:
    if decision.kind == "critical":
        return (
            "Понимаю вопрос. Подключаю к диалогу менеджера — "
            "он ответит вам лично в ближайшие минуты."
        )
    if decision.kind == "service":
        return ""
    if decision.code == "negative":
        return (
            "Прошу прощения за неудобство. Передаю диалог менеджеру, "
            "он разберётся и свяжется с вами."
        )
    if decision.code == "phone_request":
        return (
            "Конечно, организуем звонок. Передаю ваш запрос менеджеру — "
            "он наберёт вас в ближайшее время."
        )
    return "Передаю диалог менеджеру, он продолжит с вами общение."


def _perform_handoff(db, conversation, lead, decision, handoff_config, now) -> None:
    role = "service" if decision.kind == "service" else "manager"
    manager = manager_engine.assign(db, lead, decision.reason, role=role)
    deadline = now + dt.timedelta(minutes=int(handoff_config.get("task_deadline_minutes", 5)))
    crm_adapter(db).create_task(
        lead.id,
        manager.id if manager else None,
        handoff_config.get("task_title", "Связаться с клиентом"),
        deadline,
        decision.reason,
    )
    db.add(
        Event(
            type="handoff",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={
                "kind": decision.kind,
                "code": decision.code,
                "reason": decision.reason,
                "manager": manager.name if manager else None,
                "deadline": deadline.isoformat(timespec="seconds"),
            },
            created_at=now,
        )
    )


def _create_meeting(db, conversation, lead, scheduled_at, sales_config, meeting_config, now) -> None:
    meeting = Meeting(
        lead_id=lead.id,
        scheduled_at=scheduled_at,
        address=sales_config.get("office_address", ""),
        status="scheduled",
        slot_label=scheduled_at.strftime("%d.%m %H:%M"),
        created_at=now,
        updated_at=now,
    )
    db.add(meeting)
    lead.meeting_scheduled = True
    lead.invited_to_office = True
    db.add(
        Event(
            type="meeting_scheduled",
            conversation_id=conversation.id,
            lead_id=lead.id,
            payload={"at": scheduled_at.isoformat(timespec="minutes")},
            created_at=now,
        )
    )
    followup_engine.schedule_meeting_reminders(
        db, conversation, lead, scheduled_at, now, meeting_config
    )


def _finish_state(db, lead, stats, signals, now) -> list[dict]:
    mutations = crm_controller.apply(lead, stats, signals)
    temperature = handoff_engine.temperature(
        signals,
        stats,
        {
            "handoff_kind": lead.handoff_kind,
            "negative": lead.negative,
            "timeframe": (lead.qualification or {}).get("timeframe", {}).get("value"),
            "meeting_scheduled": lead.meeting_scheduled,
            "contact_acquired": lead.contact_acquired,
        },
    )
    if temperature != lead.temperature:
        mutations.append({"field": "temperature", "from": lead.temperature, "to": temperature})
        lead.temperature = temperature

    lead.next_action = qualification.next_best_action(
        {
            "qualification": lead.qualification,
            "stats": stats,
            "handoff_required": lead.handoff_required,
            "handoff_reason": lead.handoff_reason,
            "contact_phone": lead.contact_phone,
            "meeting": lead.meeting_scheduled,
            "selected_products": lead.selected_products,
        }
    )
    lead.updated_at = now
    for mutation in mutations:
        db.add(
            Event(
                type="crm_mutation",
                conversation_id=lead.conversation_id,
                lead_id=lead.id,
                payload=mutation,
                created_at=now,
            )
        )
    db.flush()
    return mutations


def _guard_context(
    db, conversation, lead, offers, stats, decision, signals, sales_config, text, unfit,
    referenced_ids: list[int] | None = None,
) -> dict:
    """`referenced_ids` are products the backend deliberately named — the
    out-of-stock model it is declining, or the mismatch it is explaining.
    Naming them is required behaviour, so they must not read as invented stock.
    """
    product_ids = [o["id"] for o in offers]
    rows = (
        db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
        if product_ids
        else []
    )
    return {
        "offered_products": offers,
        "stock_map": {row.id: row.stock for row in rows},
        "price_map": {row.id: row.price for row in rows},
        "listing_map": {row.id: row.listing_price for row in rows},
        "sales_config": sales_config,
        "repeated_questions": guard_module.detect_repeated_questions(text, stats["closed"]),
        "human_active": conversation.mode == "human",
        "handoff": decision.as_dict(),
        "handoff_ack": True,
        "negative": lead.negative,
        "unfit_products": unfit if not offers else [],
        "unverified_claims": _detect_unlisted_products(
            db, text, product_ids + list(referenced_ids or [])
        ),
    }


def _detect_unlisted_products(db: Session, text: str, allowed_ids: list[int]) -> list[str]:
    """Flag a catalogue model named in the answer that the backend did not approve.

    Matching is on the full model string, not on token overlap: sibling models
    ("ROG Strix G15" vs "ROG Strix SCAR 17") share most of their tokens, and a
    prefix match flagged the approved offer's own neighbours.
    """
    low = text.lower()
    hits: list[str] = []
    for product in db.execute(select(Product)).scalars().all():
        if product.id in allowed_ids:
            continue
        model = product.model.lower()
        full = f"{product.brand} {product.model}".lower()
        if len(model) >= 6 and (model in low or full in low):
            hits.append(f"{product.brand} {product.model} — вне списка разрешённых кандидатов")
    return hits[:3]


def _system_prompt(db, lead, plan, sales_config, offers, kb_fragments) -> str:
    """What a real model receives.  The demo provider renders `plan` directly."""
    known = qualification.humanize(lead.qualification)
    known_lines = [f"- {qualification.FIELD_LABELS[k]}: {v}" for k, v in known.items() if v]
    unknown = [qualification.FIELD_LABELS[k] for k, v in known.items() if not v]

    offer_lines = [
        f"- {o['title']} | {o['cpu']} / {o['gpu']} / {o['ram']} ГБ / {o['storage']} | "
        f"состояние {o['condition']} | цена ОТ {o['price']} ₽ | в наличии: {o['stock']} шт."
        for o in offers
    ]
    kb_lines = [f"- [{f['branch_label']}] {f['title']}: {f['excerpt'][:200]}" for f in kb_fragments]

    parts = [
        "Ты — продавец-консультант магазина б/у ноутбуков и ПК в переписке на Авито.",
        "Пиши по-русски, живо и по делу, без канцелярита и без markdown-разметки.",
        "",
        "ЧТО УЖЕ ИЗВЕСТНО О КЛИЕНТЕ (не переспрашивай это):",
        *(known_lines or ["- пока ничего"]),
        "",
        f"ЧТО ЕЩЁ НУЖНО ВЫЯСНИТЬ: {', '.join(unknown) if unknown else 'всё закрыто'}",
        "",
    ]
    if plan.get("questions"):
        parts += ["ЗАДАЙ ИМЕННО ЭТИ ВОПРОСЫ (не больше):", *[f"- {q}" for q in plan["questions"]], ""]
    if offer_lines:
        parts += [
            "РАЗРЕШЁННЫЕ ТОВАРЫ (предлагать можно ТОЛЬКО их, характеристики и цены — дословно):",
            *offer_lines,
            "",
        ]
    else:
        parts += ["ТОВАРЫ В ЭТОМ ОТВЕТЕ НЕ ПРЕДЛАГАЕМ.", ""]
    if plan.get("mismatch"):
        mismatch = plan["mismatch"]
        parts += [
            f"ВАЖНО: {mismatch['title']} не подходит под задачу «{mismatch['task_label']}» — "
            f"{mismatch['reason']}. Объясни это честно и предложи альтернативы выше.",
            "",
        ]
    if plan.get("out_of_stock"):
        parts += [
            f"ВАЖНО: {plan['out_of_stock']['title']} нет в наличии. "
            "Прямо скажи об этом и предложи альтернативы выше. Не выдумывай причину отсутствия.",
            "",
        ]
    if plan.get("address"):
        parts += [
            f"Сообщи адрес: {plan.get('address_text')} и режим работы: {plan.get('hours_text')}.",
        ]
    if plan.get("meeting_prompt"):
        parts += [f"Задай закрытый вопрос о встрече: «{plan['meeting_prompt']}»"]
    if plan.get("meeting_confirmed"):
        parts += [f"Подтверди встречу: {plan['meeting_confirmed']}"]
    if plan.get("ask_contact"):
        parts += ["Попроси номер телефона, объяснив пользу для клиента."]
    if plan.get("promo"):
        parts += [f"Упомяни промокод {plan['promo']}."]
    if kb_lines:
        parts += ["", "ФРАГМЕНТЫ БАЗЫ ЗНАНИЙ:", *kb_lines]

    style = plan.get("style") or {}
    parts += [
        "",
        "СТИЛЬ: " + ("коротко, 1-3 предложения" if style.get("length") != "detailed"
                     else "подробно, но без воды")
        + ("; на «вы», вежливо" if style.get("formal", True) else "; неформально, на «ты»")
        + ("; можно один эмодзи" if style.get("emoji") else "; без эмодзи"),
        "",
        "ЗАПРЕЩЕНО: выдумывать наличие, цены, характеристики, дефекты, ремонт, залитие, "
        "«синий экран», «за товаром уже едет клиент»; называть цену выше цены объявления; "
        "давать личный телефон или Telegram; обещать скидки и индивидуальные условия; "
        "приписывать себе личный игровой опыт.",
        f"ЦЕНЫ всегда указывай в формате «{sales_config.get('price_prefix', 'от')} X ₽».",
    ]
    return "\n".join(parts)


def _write_log(
    db, conversation, inbound, outbound, extraction, rules, kb_fragments, products_queried,
    inventory_snapshot, price_validation, safety_checks, mutations, decision, handoff_reason,
    *, provider: str, model: str, latency: int, verdict: str, error: str = "",
) -> TurnLog:
    log = TurnLog(
        conversation_id=conversation.id,
        message_id=outbound.id if outbound else None,
        created_at=clock_now(),
        customer_message=inbound.text if inbound else "",
        ai_response=outbound.text if outbound else "",
        extracted={
            key: value.get("raw") or str(value.get("value"))
            for key, value in extraction.fields.items()
        }
        | ({"signals": sorted(extraction.signals)} if extraction.signals else {}),
        rules_triggered=rules,
        kb_fragments=kb_fragments,
        products_queried=products_queried,
        inventory_snapshot=inventory_snapshot,
        price_validation=price_validation,
        safety_checks=safety_checks,
        crm_mutations=mutations,
        handoff_reason=handoff_reason,
        provider=provider,
        model=model,
        latency_ms=latency,
        guard_verdict=verdict,
        error=error,
    )
    db.add(log)
    db.flush()
    return log
