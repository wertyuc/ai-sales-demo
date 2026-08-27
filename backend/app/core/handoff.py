"""Handoff controller and lead-temperature detection (§9, §26, §27).

Every rule is individually switchable from the Control Center, and each decision
carries a human-readable reason so the UI can show *why* a chat was escalated.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HandoffDecision:
    required: bool = False
    kind: str = ""  # manager | service | critical
    reason: str = ""
    code: str = ""
    blocks_ai: bool = False  # True = AI stops writing; False = manager joins alongside
    involve_only: bool = False
    triggered: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "required": self.required,
            "kind": self.kind,
            "reason": self.reason,
            "code": self.code,
            "blocks_ai": self.blocks_ai,
            "involve_only": self.involve_only,
            "triggered": self.triggered,
        }


REASONS = {
    "ai_suspicion": "Клиент заподозрил, что общается с AI",
    "negative": "Зафиксирован негатив клиента",
    "phone_request": "Клиент просит позвонить",
    "service": "Сервисный вопрос: гарантия / ремонт",
    "threshold": "Квалификация ≥ порога автопередачи",
    "region": "Регион + закрыто ≥ {n} пунктов квалификации",
    "photo": "Клиент запросил фото/видео — нужна выгрузка материалов",
}


def evaluate(signals: set[str], stats: dict, config: dict) -> HandoffDecision:
    """Rules are ordered by severity; the first blocking match wins."""
    decision = HandoffDecision()
    triggered: list[str] = []

    # 1. critical — the customer suspects automation (§26.6)
    if "ai_suspicion" in signals and config.get("ai_suspicion", True):
        triggered.append("ai_suspicion")
        return HandoffDecision(
            required=True,
            kind="critical",
            reason=REASONS["ai_suspicion"],
            code="ai_suspicion",
            blocks_ai=True,
            triggered=triggered,
        )

    # 2. negative sentiment (§26.1)
    if "negative" in signals and config.get("negative", True):
        triggered.append("negative")
        return HandoffDecision(
            required=True,
            kind="manager",
            reason=REASONS["negative"],
            code="negative",
            blocks_ai=True,
            triggered=triggered,
        )

    # 3. service questions go to the service desk, not to sales (§27)
    if "service_question" in signals and config.get("service_questions", True):
        triggered.append("service")
        return HandoffDecision(
            required=True,
            kind="service",
            reason=REASONS["service"],
            code="service",
            blocks_ai=True,
            triggered=triggered,
        )

    # 4. explicit call request (§26.2)
    if "phone_request" in signals and config.get("phone_request", True):
        triggered.append("phone_request")
        return HandoffDecision(
            required=True,
            kind="manager",
            reason=REASONS["phone_request"],
            code="phone_request",
            blocks_ai=True,
            triggered=triggered,
        )

    # 5. qualification threshold (§26.4)
    if stats.get("over_threshold") and config.get("qualification_threshold", True):
        triggered.append("threshold")
        return HandoffDecision(
            required=True,
            kind="manager",
            reason=REASONS["threshold"],
            code="threshold",
            blocks_ai=False,
            triggered=triggered,
        )

    # 6. region rule (§26.5)
    if stats.get("region_rule") and config.get("region_rule", True):
        triggered.append("region")
        return HandoffDecision(
            required=True,
            kind="manager",
            reason=REASONS["region"].format(n=stats.get("closed_count", 4)),
            code="region",
            blocks_ai=False,
            triggered=triggered,
        )

    # 7. photo/video: manager joins, AI keeps qualifying (§21, §26.3)
    if "photo_request" in signals and config.get("photo_video", True):
        triggered.append("photo")
        return HandoffDecision(
            required=True,
            kind="manager",
            reason=REASONS["photo"],
            code="photo",
            blocks_ai=False,
            involve_only=True,
            triggered=triggered,
        )

    decision.triggered = triggered
    return decision


HOT_SIGNALS = ("hot_intent", "address_request", "contact_given", "pickup_intent")


def temperature(signals: set[str], stats: dict, lead_flags: dict) -> str:
    """COLD → WARM → HOT → CRITICAL (§9, §11 of the demo brief)."""
    if lead_flags.get("handoff_kind") == "critical" or "ai_suspicion" in signals:
        return "CRITICAL"
    if lead_flags.get("negative"):
        return "CRITICAL"

    heat = 0
    zone = stats.get("zone")
    score = stats.get("score", 0)

    if zone in ("msk", "mo"):
        heat += 2
    elif zone == "region":
        heat += 1
    if score >= 80:
        heat += 3
    elif score >= 60:
        heat += 2
    elif score >= 40:
        heat += 1

    for signal in HOT_SIGNALS:
        if signal in signals:
            heat += 2
    if lead_flags.get("timeframe") in ("today", "tomorrow"):
        heat += 2
    if lead_flags.get("meeting_scheduled"):
        heat += 3
    if lead_flags.get("contact_acquired"):
        heat += 1

    if heat >= 7:
        return "HOT"
    if heat >= 3:
        return "WARM"
    return "COLD"


def hot_signal_labels(signals: set[str]) -> list[str]:
    labels = {
        "hot_intent": "готов купить / приехать",
        "address_request": "спрашивает адрес",
        "contact_given": "оставил контакт",
        "pickup_intent": "готов забрать лично",
        "delivery_intent": "обсуждает доставку",
        "price_request": "спрашивает цену",
        "selection_request": "просит подбор",
    }
    return [labels[s] for s in signals if s in labels]
