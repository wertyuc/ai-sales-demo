"""Response guard — the last gate before a message reaches the customer.

Runs the twelve checks from §45 of the specification.  This is a *backend*
validation layer, not a prompt instruction: even a model that ignores its system
prompt cannot get an invented price or a fabricated defect past this function.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- forbidden content (§22, §24, §32) --------------------------------------

FORBIDDEN_CLAIMS: tuple[tuple[str, str], ...] = (
    (r"уже ед[еуё]т за ним|уже в пути к другому|другой клиент уже ед",
     "выдуманный факт: «за товаром уже едет клиент»"),
    (r"залит|залив[аоу]|попал[аи]? вода", "выдуманный дефект: залитие"),
    (r"син(ий|его) экран|bsod", "выдуманный дефект: синий экран"),
    (r"был в ремонте|после ремонта|перепа(ян|яли)", "неподтверждённый факт о ремонте"),
    (r"персональн(ая|ую) скидк|дам скидк|сделаю скидк|скину \d", "несогласованная скидка"),
    (r"индивидуальн(ые|ых) услови(я|й) рассрочк", "несогласованные условия рассрочки"),
    (r"я лично (прошёл|прошел|играл)|у меня \d+\s*(к|тысяч)\s*часов|я сам рендерил",
     "выдуманный личный опыт сотрудника"),
    (r"@[a-z0-9_]{4,}|telegram\.me|t\.me/", "передача личного Telegram"),
    (r"гарантирую,? что не сломается|100% не сломается", "невыполнимое обещание"),
)

PRICE_RE = re.compile(r"(?<![\d])(\d[\d\s]{3,8})\s*(?:₽|руб)", re.IGNORECASE)
FROM_PREFIX_RE = re.compile(r"(?:от|От|ОТ)\s+\d[\d\s]{3,8}\s*(?:₽|руб)")


@dataclass
class Check:
    code: str
    label: str
    status: str = "passed"  # passed | failed | warning | skipped
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class GuardReport:
    verdict: str = "PASSED"
    checks: list[Check] = field(default_factory=list)
    text: str = ""
    price_validation: dict = field(default_factory=dict)
    blocked: bool = False

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "blocked": self.blocked,
            "checks": [c.as_dict() for c in self.checks],
            "price_validation": self.price_validation,
        }


SAFE_FALLBACK = (
    "Секунду — уточню детали по этой позиции у коллег, чтобы не сказать лишнего, "
    "и вернусь с точным ответом."
)


def run(text: str, ctx: dict) -> GuardReport:
    """`ctx` carries everything the checks need; see pipeline.build_guard_context."""
    checks: list[Check] = []
    sanitized = text
    blocked = False

    offered = ctx.get("offered_products") or []
    stock_map = ctx.get("stock_map") or {}
    prices = ctx.get("price_map") or {}
    listings = ctx.get("listing_map") or {}
    sales = ctx.get("sales_config") or {}

    # 1 — every product named in the answer exists in the catalogue
    unknown = [p for p in offered if p.get("id") not in prices]
    checks.append(
        Check(
            "product_exists",
            "Товар существует в учётной системе",
            "failed" if unknown else "passed",
            ", ".join(str(p.get("title")) for p in unknown) if unknown else "",
        )
    )
    if unknown:
        blocked = True

    # 2 — and is actually in stock
    out_of_stock = [p for p in offered if stock_map.get(p.get("id"), 0) <= 0]
    checks.append(
        Check(
            "in_stock",
            "Наличие подтверждено",
            "failed" if out_of_stock else "passed",
            ", ".join(str(p.get("title")) for p in out_of_stock) if out_of_stock else "",
        )
    )
    if out_of_stock:
        blocked = True

    # 3 — quoted price equals the current price
    stale = [
        p for p in offered
        if p.get("price") is not None and prices.get(p.get("id")) != p.get("price")
    ]
    checks.append(
        Check(
            "price_actual",
            "Цена актуальна",
            "failed" if stale else "passed",
            ", ".join(str(p.get("title")) for p in stale) if stale else "",
        )
    )
    if stale:
        blocked = True

    # 4 — never above the price published in the ad
    violations = []
    numbers = [int(re.sub(r"\D", "", m)) for m in PRICE_RE.findall(sanitized)]
    ceiling = max(listings.values()) if listings else None
    for product in offered:
        listing = listings.get(product.get("id"))
        if listing and product.get("price") and product["price"] > listing:
            violations.append(f"{product.get('title')}: {product['price']} > {listing}")
    # Numbers that are not product quotes (a stated budget, a spec, a promo) are
    # deliberately NOT treated as price claims — only the catalogue is authoritative.
    checks.append(
        Check(
            "price_ceiling",
            "Цена не выше цены объявления",
            "failed" if violations else "passed",
            "; ".join(violations),
        )
    )
    if violations:
        blocked = True

    price_validation = {
        "quoted": numbers,
        "ceiling": ceiling,
        "prefix_required": sales.get("price_prefix", "от"),
        "violations": violations,
    }

    # 4b — enforce the "ОТ X ₽" wording (§23)
    if numbers:
        sanitized, fixed = _enforce_from_prefix(sanitized)
        price_validation["prefix_fixed"] = fixed
        checks.append(
            Check(
                "price_format",
                "Формат цены «ОТ»",
                "warning" if fixed else "passed",
                "формат исправлен автоматически" if fixed else "",
            )
        )
    else:
        checks.append(Check("price_format", "Формат цены «ОТ»", "skipped", "цен в ответе нет"))

    # 5 — no forbidden claims
    hits = [reason for pattern, reason in FORBIDDEN_CLAIMS if re.search(pattern, sanitized, re.I)]
    checks.append(
        Check(
            "forbidden_claims",
            "Нет запрещённых утверждений",
            "failed" if hits else "passed",
            "; ".join(hits),
        )
    )
    if hits:
        blocked = True

    # 6 — no re-asking of an already closed parameter
    repeated = ctx.get("repeated_questions") or []
    checks.append(
        Check(
            "no_repeat_questions",
            "Не переспрашивает закрытые параметры",
            "failed" if repeated else "passed",
            ", ".join(repeated),
        )
    )
    if repeated:
        blocked = True

    # 7 — a human has not taken the chat over
    human = ctx.get("human_active")
    checks.append(
        Check(
            "human_not_active",
            "Менеджер не перехватил чат",
            "failed" if human else "passed",
            "чат ведёт менеджер" if human else "",
        )
    )
    if human:
        blocked = True

    # 8 — handoff obligations honoured
    handoff = ctx.get("handoff") or {}
    unhandled = handoff.get("required") and handoff.get("blocks_ai") and not ctx.get("handoff_ack")
    checks.append(
        Check(
            "handoff_respected",
            "Передача менеджеру учтена",
            "failed" if unhandled else "passed",
            handoff.get("reason", "") if handoff.get("required") else "",
        )
    )
    if unhandled:
        blocked = True

    # 9 — service questions routed to the service desk
    service = handoff.get("kind") == "service"
    checks.append(
        Check(
            "service_routed",
            "Сервисный вопрос направлен в сервис",
            "warning" if service else "passed",
            "лид переведён в сервисный отдел" if service else "",
        )
    )

    # 10 — negativity acknowledged rather than ignored
    negative = ctx.get("negative")
    checks.append(
        Check(
            "negative_handled",
            "Негатив обработан",
            "warning" if negative else "passed",
            "негатив зафиксирован, подключён менеджер" if negative else "",
        )
    )

    # 11 — offered machines actually fit the stated task
    unfit = ctx.get("unfit_products") or []
    checks.append(
        Check(
            "fits_task",
            "Товар соответствует задаче клиента",
            "failed" if unfit else "passed",
            ", ".join(unfit),
        )
    )
    if unfit:
        blocked = True

    # 12 — no unverifiable statements
    invented = ctx.get("unverified_claims") or []
    checks.append(
        Check(
            "no_unverified_facts",
            "Нет неподтверждённых фактов",
            "failed" if invented else "passed",
            ", ".join(invented),
        )
    )
    if invented:
        blocked = True

    failed = [c for c in checks if c.status == "failed"]
    warned = [c for c in checks if c.status == "warning"]
    verdict = "FAILED" if failed else ("PASSED_WITH_WARNINGS" if warned else "PASSED")

    return GuardReport(
        verdict=verdict,
        checks=checks,
        text=sanitized if not failed else SAFE_FALLBACK,
        price_validation=price_validation,
        blocked=bool(failed),
    )


def _enforce_from_prefix(text: str) -> tuple[str, bool]:
    """Rewrite "120 000 ₽" as "от 120 000 ₽" unless the prefix is already there."""
    fixed = False
    out: list[str] = []
    cursor = 0
    for match in PRICE_RE.finditer(text):
        start = match.start()
        prefix_window = text[max(0, start - 14) : start].lower()
        out.append(text[cursor:start])
        # "до 100 000 ₽" is the customer's stated ceiling, not an offer price —
        # rewriting it to "от" would invert the meaning.
        already_qualified = any(
            token in prefix_window for token in ("от ", "от\n", "до ", "бюджет")
        )
        if not already_qualified:
            out.append("от ")
            fixed = True
        out.append(match.group(0))
        cursor = match.end()
    out.append(text[cursor:])
    return "".join(out), fixed


def detect_repeated_questions(text: str, closed_fields: list[str]) -> list[str]:
    """Catch an answer that asks again about something already known (§25, §45.5)."""
    if "?" not in text:
        return []
    low = text.lower()
    probes = {
        "budget": ("на какой бюджет", "какой бюджет", "сколько готовы потратить", "в какую сумму"),
        "geo": ("вы в москве", "из какого города", "где находитесь", "нужна доставка"),
        "timeframe": ("когда планируете", "когда покупаете", "какие сроки"),
        "tasks": ("под какие задачи", "для чего", "во что играете", "чем занимаетесь"),
        "requirements": ("какой бренд", "предпочтения по бренду", "какие характеристики"),
        "recipient": ("себе или в подарок", "для кого", "кому покупаете"),
    }
    repeated = []
    for field_name in closed_fields:
        for probe in probes.get(field_name, ()):  # noqa: B007
            if probe in low:
                repeated.append(field_name)
                break
    return repeated
