"""Product Expert.

Two jobs:

1. Turn the structured qualification state into an inventory query and rank what
   comes back — the model never picks products, it only explains the ones the
   backend already approved.
2. Judge fit honestly (§17): when the machine the customer is looking at cannot
   do the job they described, say so and offer something that can.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..adapters.base import InventoryAdapter, InventoryItem, InventoryQuery
from .extractor import TASK_LABELS, TASK_LABELS_ACC
from .qualification import budget_value, is_gift, requirements_dict, tasks_list

# minimum capability a task really needs, on the 0..100 scales stored per product
TASK_REQUIREMENTS: dict[str, dict[str, int]] = {
    "games": {"gpu_score": 60, "cpu_score": 45, "ram": 16},
    "creative": {"gpu_score": 50, "cpu_score": 60, "ram": 16},
    "dev": {"gpu_score": 0, "cpu_score": 60, "ram": 16},
    "work": {"gpu_score": 0, "cpu_score": 30, "ram": 8},
    "study": {"gpu_score": 0, "cpu_score": 25, "ram": 8},
}

MISMATCH_REASONS = {
    "gpu_score": "здесь нет полноценной дискретной видеокарты, тяжёлые игры на ней не пойдут",
    "cpu_score": "процессор слабоват под такие задачи, будут просадки и долгий рендер",
    "ram": "оперативной памяти для этой задачи мало",
}


@dataclass
class Offer:
    item: InventoryItem
    score: float
    why: str

    def as_dict(self) -> dict:
        return {
            "id": self.item.id,
            "sku": self.item.sku,
            "title": self.item.title,
            "price": self.item.price,
            "listing_price": self.item.listing_price,
            "condition": self.item.condition,
            "cpu": self.item.cpu,
            "gpu": self.item.gpu,
            "ram": self.item.ram,
            "storage": self.item.storage,
            "screen": self.item.screen,
            "stock": self.item.stock,
            "why": self.why,
            "score": round(self.score, 1),
        }


def build_query(qualification: dict, limit: int = 12) -> InventoryQuery:
    requirements = requirements_dict(qualification)
    tasks = tasks_list(qualification)
    query = InventoryQuery(
        budget_max=budget_value(qualification),
        tasks=tasks,
        brand=requirements.get("brand"),
        specs=requirements.get("specs") or [],
        only_in_stock=True,
        limit=limit,
    )
    if is_gift(qualification):
        query.conditions = ["A+", "A"]
    if "games" in tasks or "creative" in tasks:
        query.type = None
    return query


def suitability_for(item: InventoryItem, tasks: list[str]) -> int:
    if not tasks:
        return int(item.suitability.get("work", 60))
    return min(int(item.suitability.get(task, 50)) for task in tasks)


def shortfalls(item: InventoryItem, tasks: list[str]) -> list[str]:
    """Which hard requirement the item misses for the requested tasks."""
    missed: list[str] = []
    for task in tasks:
        needs = TASK_REQUIREMENTS.get(task)
        if not needs:
            continue
        for attribute, minimum in needs.items():
            if getattr(item, attribute, 0) < minimum and attribute not in missed:
                missed.append(attribute)
    return missed


def rank(
    items: list[InventoryItem], qualification: dict, limit: int = 3
) -> list[Offer]:
    tasks = tasks_list(qualification)
    budget = budget_value(qualification)
    requirements = requirements_dict(qualification)
    gift = is_gift(qualification)

    offers: list[Offer] = []
    for item in items:
        if not item.in_stock:
            continue
        score = float(suitability_for(item, tasks))
        if shortfalls(item, tasks):
            score -= 45
        if budget:
            if item.price <= budget:
                # reward using the budget well rather than being merely cheap
                score += 12 * (item.price / budget)
            else:
                score -= 25
        if requirements.get("brand") and item.brand == requirements["brand"]:
            score += 12
        for spec in requirements.get("specs") or []:
            haystack = f"{item.cpu} {item.gpu} {item.ram} {item.storage} {item.screen}".lower()
            if spec.lower().split()[0] in haystack:
                score += 4
        if gift and item.condition in ("A+", "A"):
            score += 8
        if item.condition == "A+":
            score += 3
        offers.append(Offer(item=item, score=score, why=""))

    offers.sort(key=lambda o: o.score, reverse=True)

    # Honesty filter (§17): if the customer named a demanding task, a machine that
    # cannot do it is not an option — it only appears when nothing better exists.
    heavy = [t for t in tasks if t in ("games", "creative", "dev")]
    if heavy:
        suitable = [o for o in offers if not shortfalls(o.item, heavy)]
        if suitable:
            # one honest option beats three where two cannot do the job
            offers = suitable

    top = _diversify(offers, limit)
    highlights = _highlights(top)
    for offer in top:
        offer.why = explain(offer.item, qualification, highlights.get(offer.item.id, ""))
    return top


def _highlights(offers: list[Offer]) -> dict[int, str]:
    """Give each shortlisted machine its own angle instead of three identical lines."""
    if len(offers) < 2:
        return {}
    labels: dict[int, str] = {}
    items = [o.item for o in offers]
    cheapest = min(items, key=lambda i: i.price)
    strongest = max(items, key=lambda i: i.gpu_score + i.cpu_score)
    lightest = max(items, key=lambda i: i.portability)
    roomiest = max(items, key=lambda i: _storage_gb(i.storage))

    if cheapest.id not in labels:
        labels[cheapest.id] = "самый доступный из подходящих"
    if strongest.id not in labels:
        labels[strongest.id] = "максимальный запас производительности"
    if lightest.id not in labels and lightest.portability >= 70:
        labels[lightest.id] = "самый лёгкий и автономный"
    if roomiest.id not in labels and _storage_gb(roomiest.storage) >= 1000:
        labels[roomiest.id] = "больше всего места под игры и проекты"
    for offer in offers:
        labels.setdefault(offer.item.id, "сбалансированный вариант")
    return labels


def _storage_gb(storage: str) -> int:
    low = storage.lower()
    digits = "".join(ch for ch in low if ch.isdigit())
    if not digits:
        return 0
    value = int(digits)
    return value * 1000 if "тб" in low or "tb" in low else value


def _diversify(offers: list[Offer], limit: int) -> list[Offer]:
    """Avoid showing three near-identical machines from the same family."""
    chosen: list[Offer] = []
    seen_models: set[str] = set()
    for offer in offers:
        key = f"{offer.item.brand}:{offer.item.model.split()[0]}"
        if key in seen_models and len(chosen) < limit:
            continue
        chosen.append(offer)
        seen_models.add(key)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for offer in offers:
            if offer not in chosen:
                chosen.append(offer)
            if len(chosen) >= limit:
                break
    return chosen[:limit]


def explain(item: InventoryItem, qualification: dict, highlight: str = "") -> str:
    tasks = tasks_list(qualification)
    budget = budget_value(qualification)
    bits: list[str] = []
    if highlight:
        bits.append(highlight)

    if "games" in tasks:
        if item.gpu_score >= 78:
            bits.append("уверенно тянет тяжёлые игры на высоких настройках")
        elif item.gpu_score >= 60:
            bits.append("комфортно играть в современные игры на средне-высоких")
        else:
            bits.append("для нетребовательных игр")
    if "creative" in tasks:
        bits.append(
            "хватает под монтаж и рендер" if item.cpu_score >= 65 else "подойдёт под лёгкую графику"
        )
    if "dev" in tasks:
        bits.append("памяти и ядер достаточно под разработку и виртуалки")
    if "work" in tasks or "study" in tasks:
        if item.portability >= 65:
            bits.append("лёгкий, удобно носить с собой")
        else:
            bits.append("спокойно закрывает офисные задачи и учёбу")

    if budget and item.price <= budget:
        bits.append(f"вписывается в бюджет ({_money(item.price)} ₽)")
    elif budget and item.price > budget:
        bits.append(f"чуть выше бюджета, но заметно мощнее ({_money(item.price)} ₽)")

    if item.condition == "A+":
        bits.append("состояние A+, внешне как новый")
    elif item.condition == "A":
        bits.append("состояние A, без заметных следов")

    if not bits:
        return item.description[:120]
    sentence = ", ".join(bits[:3])
    return sentence[0].upper() + sentence[1:]


def _money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def differences_note(offers: list[Offer], qualification: dict) -> str:
    """One sentence contrasting the shortlist for the customer's actual task."""
    if len(offers) < 2:
        return ""
    tasks = tasks_list(qualification)
    cheapest = min(offers, key=lambda o: o.item.price)
    strongest = max(offers, key=lambda o: o.item.gpu_score + o.item.cpu_score)
    if cheapest is strongest:
        return ""
    task_word = TASK_LABELS_ACC.get(tasks[0], "ваши задачи") if tasks else "ваши задачи"
    return (
        f"Разница простыми словами: {cheapest.item.title} — оптимальная цена, "
        f"{strongest.item.title} — запас производительности под {task_word} на пару лет вперёд."
    )


def search_ranked(
    inventory: InventoryAdapter,
    qualification: dict,
    limit: int = 3,
    exclude_ids: list[int] | None = None,
) -> tuple[list[Offer], dict]:
    """Rank what the catalogue can offer, widening the query if it starves.

    A brand preference must not force an unsuitable recommendation: if nothing
    from the requested brand can do the job, look at the whole catalogue and say
    so.  Returns (offers, diagnostics-for-the-log).
    """
    blocked = set(exclude_ids or [])
    tasks = tasks_list(qualification)
    heavy = [t for t in tasks if t in ("games", "creative", "dev")]
    query = build_query(qualification, limit=limit * 4)

    def run(current: InventoryQuery) -> tuple[list[Offer], int]:
        found = [i for i in inventory.search(current) if i.id not in blocked]
        return rank(found, qualification, limit=limit), len(found)

    offers, found_count = run(query)
    info = {
        "budget_max": query.budget_max,
        "tasks": query.tasks,
        "brand": query.brand,
        "conditions": query.conditions,
        "found": found_count,
        "widened": False,
    }

    def fitting(candidates: list[Offer]) -> int:
        return sum(1 for o in candidates if not shortfalls(o.item, heavy))

    # 1. a brand preference must never force an unsuitable recommendation
    if heavy and fitting(offers) == 0 and query.brand:
        query.brand = None
        widened, found_count = run(query)
        if fitting(widened):
            offers = widened
            info["widened"] = "brand"
            info["found"] = found_count

    # 2. if the budget only affords a single capable machine, look slightly
    #    above it so the customer still gets a real comparison (§19: 2-3 options)
    if heavy and 0 < fitting(offers) < 2 and query.budget_max:
        stretched = InventoryQuery(**{**query.__dict__, "budget_max": int(query.budget_max * 1.35)})
        widened, found_count = run(stretched)
        if fitting(widened) > fitting(offers):
            offers = widened
            info["widened"] = "budget"
            info["found"] = found_count

    # 3. nothing at all — drop the budget ceiling rather than return an empty list
    if not offers and query.budget_max:
        query.budget_max = None
        offers, found_count = run(query)
        info["widened"] = "budget"
        info["found"] = found_count
        info["found"] = len(found)
    return offers, info


def find_mentioned(inventory: InventoryAdapter, text: str) -> list[InventoryItem]:
    finder = getattr(inventory, "find_by_text", None)
    return finder(text) if callable(finder) else []


def mismatch_report(item: InventoryItem, qualification: dict) -> dict | None:
    """§17 / §5 of the demo brief: refuse to rubber-stamp an unsuitable choice."""
    tasks = tasks_list(qualification)
    heavy = [t for t in tasks if t in ("games", "creative", "dev")]
    if not heavy:
        return None
    missed = shortfalls(item, heavy)
    if not missed:
        return None
    return {
        "sku": item.sku,
        "title": item.title,
        "task": heavy[0],
        "task_label": TASK_LABELS.get(heavy[0], heavy[0]),
        "reason": MISMATCH_REASONS.get(missed[0], "характеристики не соответствуют задаче"),
        "missed": missed,
    }


def alternatives_for(
    inventory: InventoryAdapter, qualification: dict, exclude_ids: list[int], limit: int = 3
) -> list[Offer]:
    """Replacements for a machine that is unavailable or unsuitable.

    Uses the same widening search as a normal shortlist: proposing another
    machine that also cannot do the job would defeat the point of §17.
    """
    offers, _ = search_ranked(inventory, qualification, limit=limit, exclude_ids=exclude_ids)
    return offers
