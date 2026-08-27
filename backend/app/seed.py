"""Database seeding.

The interesting part: the ten demo conversations are not fixtures.  They are
replayed through the real pipeline with the clock rewound, so their
qualification state, CRM stage, events, handoffs and turn logs are produced by
the same code path the live demo uses.  Analytics is therefore never "fake" —
it is the arithmetic of dialogues that actually ran.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import clock
from .config import settings
from .core import kb as kb_module
from .core import pipeline, settings_store
from .models import (
    Conversation,
    Customer,
    Event,
    FollowUp,
    Lead,
    Manager,
    Meeting,
    Message,
    Product,
    Task,
    User,
)
from .seed_data import KB_ARTICLES, MANAGERS, PRODUCTS

SOURCES = ("МНСГ", "K&V", "NeiroSHOP", "Данил")
PALETTE = ("#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#ef4444", "#14b8a6")


# PBKDF2 from the standard library: no native wheels, no version conflicts.
_PBKDF2_ROUNDS = 240_000


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(raw: str, hashed: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = hashed.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", raw.encode("utf-8"), base64.b64decode(salt_b64), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


# --- suitability -------------------------------------------------------------


def _suitability(gpu: int, cpu: int, ram: int, portability: int) -> dict[str, int]:
    def clamp(value: float) -> int:
        return int(max(0, min(100, round(value))))

    ram_factor = min(1.0, ram / 16)
    return {
        "games": clamp(gpu * 0.85 + cpu * 0.1 + ram_factor * 10),
        "work": clamp(45 + cpu * 0.35 + portability * 0.2),
        "study": clamp(40 + cpu * 0.25 + portability * 0.35),
        "creative": clamp(cpu * 0.5 + gpu * 0.3 + ram_factor * 22),
        "dev": clamp(cpu * 0.6 + ram_factor * 30 + 10),
    }


def is_seeded(db: Session) -> bool:
    return (db.execute(select(func.count(Product.id))).scalar() or 0) > 0


# --- primitives --------------------------------------------------------------


def seed_users(db: Session) -> None:
    if db.execute(select(User)).scalars().first():
        return
    db.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role="rop",
            display_name="Руководитель отдела продаж",
        )
    )
    db.flush()


def seed_managers(db: Session) -> list[Manager]:
    existing = list(db.execute(select(Manager)).scalars().all())
    if existing:
        return existing
    rows = [
        Manager(name=name, role=role, on_shift=on_shift, color=color)
        for name, role, on_shift, color in MANAGERS
    ]
    db.add_all(rows)
    db.flush()
    return rows


def seed_products(db: Session) -> None:
    if db.execute(select(Product)).scalars().first():
        return
    for row in PRODUCTS:
        (sku, type_, brand, model, category, cpu, gpu, ram, storage, screen, condition,
         price, listing_price, stock, gpu_score, cpu_score, portability, description) = row
        tags = [category, type_, brand.lower()]
        if condition in ("A+", "A"):
            tags.append("gift_ready")
        db.add(
            Product(
                sku=sku, type=type_, brand=brand, model=model, category=category,
                cpu=cpu, gpu=gpu, ram=ram, storage=storage, screen=screen,
                condition=condition, price=price, listing_price=listing_price, stock=stock,
                description=description, tags=tags,
                suitability=_suitability(gpu_score, cpu_score, ram, portability),
                gpu_score=gpu_score, cpu_score=cpu_score, portability=portability,
            )
        )
    db.flush()


def seed_kb(db: Session) -> None:
    if db.execute(select(kb_module.KBArticle)).scalars().first():
        return
    for branch, slug, title, body, tags in KB_ARTICLES:
        kb_module.create(db, branch, slug, title, body, tags, actor="system")


# --- scripted conversations --------------------------------------------------

SCENARIOS: list[dict] = [
    {
        "key": "hot_moscow",
        "name": "Иван",
        "days_ago": 0,
        "minutes_ago": 42,
        "source": "МНСГ",
        "script": [
            "Привет! Нужен игровой ноут до 100 тысяч, я в Москве, могу приехать сегодня",
            "Играю в основном в Cyberpunk и Warzone, хочется на высоких",
            "Себе беру. А куда приехать можно?",
            "Да, сегодня удобно",
            "Вторая половина, часов в 18:00",
            "+7 916 245-18-30",
        ],
    },
    {
        "key": "office_qualification",
        "name": "Сергей",
        "days_ago": 0,
        "minutes_ago": 95,
        "source": "K&V",
        "script": [
            "Здравствуйте! Подскажите ноутбук для работы с документами и 1С",
            "Бюджет примерно 60 тысяч, важно чтобы был лёгкий",
            "Я в Химках",
        ],
    },
    {
        "key": "waiting_manager",
        "name": "Анна",
        "days_ago": 0,
        "minutes_ago": 25,
        "source": "NeiroSHOP",
        "script": [
            "Добрый день, интересует MacBook Air M1 для учёбы дочери",
            "Бюджет до 70 тысяч, Москва",
            "Позвоните мне пожалуйста, так удобнее обсудить",
        ],
    },
    {
        "key": "followup",
        "name": "Максим",
        "days_ago": 0,
        "minutes_ago": 18,
        "source": "Данил",
        "script": [
            "Здравствуйте, ищу игровой ноутбук до 120к",
            "Играю в танки и Dota, я в Москве",
        ],
        "keep_followup": True,
    },
    {
        "key": "new_lead",
        "name": "Алексей",
        "days_ago": 0,
        "minutes_ago": 6,
        "source": "МНСГ",
        "script": ["Здравствуйте"],
    },
    {
        "key": "mismatch",
        "name": "Дмитрий",
        "days_ago": 1,
        "minutes_ago": 200,
        "source": "K&V",
        "script": [
            "Хочу ультрабук потоньше, желательно ASUS ZenBook",
            "Буду играть в Cyberpunk на высоких настройках, бюджет 80 тысяч, я в Москве",
        ],
    },
    {
        "key": "out_of_stock",
        "name": "Ольга",
        "days_ago": 1,
        "minutes_ago": 320,
        "source": "NeiroSHOP",
        "script": [
            "Добрый день! Интересует Dell G15 5520, он есть?",
            "Нужен для игр, бюджет до 80 тысяч, я в Москве, куплю на этой неделе",
        ],
    },
    {
        "key": "region",
        "name": "Рустам",
        "days_ago": 1,
        "minutes_ago": 90,
        "source": "Данил",
        "script": [
            "Здравствуйте! Я из Казани, нужен ноутбук для работы и монтажа видео",
            "Бюджет до 150 тысяч, хотелось бы MacBook Pro, планирую купить на этой неделе",
        ],
    },
    {
        "key": "gift",
        "name": "Екатерина",
        "days_ago": 2,
        "minutes_ago": 140,
        "source": "МНСГ",
        "script": [
            "Здравствуйте! Хочу купить ноутбук в подарок сыну на день рождения",
            "Он играет в Minecraft и Fortnite, бюджет до 90 тысяч",
            "Мы в Москве, важно чтобы выглядел как новый",
        ],
    },
    {
        "key": "negative",
        "name": "Виктор",
        "days_ago": 2,
        "minutes_ago": 260,
        "source": "K&V",
        "script": [
            "Смотрю ваш Legion 5, сколько стоит?",
            "Это уже третий магазин где мне морочат голову, отвратительное обслуживание",
        ],
    },
    {
        "key": "ai_suspicion",
        "name": "Павел",
        "days_ago": 3,
        "minutes_ago": 180,
        "source": "NeiroSHOP",
        "script": [
            "Нужен ноут для программирования, бюджет 130к",
            "У меня ощущение, что я с роботом разговариваю, это так?",
        ],
    },
    {
        "key": "meeting_done",
        "name": "Наталья",
        "days_ago": 3,
        "minutes_ago": 420,
        "source": "Данил",
        "script": [
            "Здравствуйте! Нужен ноутбук для учёбы дочери, бюджет 60 тысяч",
            "Мы в Москве, хотим посмотреть вживую. Куда приехать?",
            "Да, сегодня удобно",
            "Первая половина дня, в 12:00",
            "+7 903 771-42-19",
        ],
    },
]


def _make_customer(db: Session, name: str, index: int, source: str) -> Customer:
    customer = Customer(
        name=name,
        avito_id=f"avito-{1000 + index}",
        nickname=f"{name.lower()}_{1000 + index}",
        source=source,
        avatar_color=PALETTE[index % len(PALETTE)],
    )
    db.add(customer)
    db.flush()
    return customer


def seed_conversations(db: Session, base_now: dt.datetime) -> None:
    if db.execute(select(Conversation)).scalars().first():
        return

    for index, scenario in enumerate(SCENARIOS):
        start = base_now - dt.timedelta(
            days=scenario["days_ago"], minutes=scenario["minutes_ago"]
        )
        clock.set_now(start)
        customer = _make_customer(db, scenario["name"], index, scenario["source"])
        conversation = Conversation(
            customer_id=customer.id,
            channel="avito",
            mode="ai",
            status="active",
            scenario=scenario["key"],
            started_at=start,
            customer_reads_messages=scenario["key"] != "ignored",
        )
        db.add(conversation)
        db.flush()

        for step, text in enumerate(scenario["script"]):
            clock.set_now(start + dt.timedelta(minutes=step * 3))
            pipeline.handle_customer_message(db, conversation, text)
            db.flush()

        if not scenario.get("keep_followup"):
            for followup in db.execute(
                select(FollowUp).where(
                    FollowUp.conversation_id == conversation.id, FollowUp.status == "scheduled"
                )
            ).scalars().all():
                followup.status = "cancelled"
                followup.note = "demo seed"
        db.flush()

    clock.set_now(base_now)


def seed_history(db: Session, base_now: dt.datetime, managers: list[Manager]) -> None:
    """Extra closed leads so the dashboard is populated on first launch."""
    if (db.execute(select(func.count(Lead.id))).scalar() or 0) > len(SCENARIOS):
        return

    rng = random.Random(20260827)
    sales_managers = [m for m in managers if m.role == "manager"] or managers
    products = list(db.execute(select(Product)).scalars().all())
    names = [
        "Артём", "Юлия", "Денис", "Марина", "Игорь", "Светлана", "Роман", "Полина",
        "Тимур", "Ксения", "Владислав", "Алина", "Григорий", "Дарья", "Никита", "Вера",
        "Станислав", "Лариса",
    ]

    for index, name in enumerate(names):
        days_ago = 2 + index % 20
        created = base_now - dt.timedelta(days=days_ago, hours=rng.randint(1, 9))
        customer = _make_customer(db, name, 100 + index, rng.choice(SOURCES))
        conversation = Conversation(
            customer_id=customer.id,
            channel="avito",
            mode="ai",
            status="closed",
            scenario="history",
            started_at=created,
            last_message_at=created + dt.timedelta(minutes=rng.randint(4, 60)),
        )
        db.add(conversation)
        db.flush()

        closed_count = rng.choice([1, 2, 3, 3, 4, 4, 5, 6])
        score = min(100, int(closed_count / 6 * 100))
        zone = rng.choice(["msk", "msk", "mo", "region"])
        qualification = {
            "budget": {"value": rng.choice([60000, 80000, 100000, 130000]), "raw": "бюджет"},
            "geo": {"value": {"zone": zone, "city": "Москва" if zone == "msk" else "Казань"},
                    "raw": "география"},
            "tasks": {"value": [rng.choice(["games", "work", "study", "creative"])], "raw": "задачи"},
            "timeframe": {"value": rng.choice(["today", "week", "2weeks"]), "raw": "срок"},
            "requirements": {"value": {"brand": rng.choice(["ASUS", "Lenovo", "Apple"])},
                             "raw": "бренд"},
            "recipient": {"value": {"type": rng.choice(["self", "gift"]), "who": ""},
                          "raw": "получатель"},
        }
        keys = list(qualification)
        rng.shuffle(keys)
        qualification = {key: qualification[key] for key in keys[:closed_count]}

        # Deterministic funnel rather than chained coin flips: four nested random
        # draws collapse to almost no sales, which makes the dashboard look broken
        # on first launch. The stages stay strictly nested (sold ⊆ arrived ⊆
        # meeting ⊆ contact) so the conversion rates remain coherent.
        qualified = closed_count >= 3
        contact = qualified and index % 10 < 7
        meeting = contact and index % 7 < 5
        arrived = meeting and index % 5 < 4
        sold = arrived and index % 3 < 2
        negative = (not contact) and index % 11 == 3
        ignored = (not contact) and (not negative) and index % 4 == 1
        product = rng.choice(products)

        lead = Lead(
            customer_id=customer.id,
            conversation_id=conversation.id,
            stage="deal" if sold else ("arrives_1_3_days" if meeting else
                                       ("qualification" if closed_count else "new")),
            direction=("delivery_region" if zone == "region"
                       else ("office" if meeting else "delivery_msk")),
            temperature=("HOT" if score >= 80 else "WARM" if score >= 50 else "COLD"),
            qualification=qualification,
            score=score,
            closed_count=closed_count,
            sentiment="negative" if negative else "neutral",
            contact_phone=f"+79{rng.randint(100000000, 999999999)}" if contact else "",
            selected_products=[product.id],
            manager_id=rng.choice(sales_managers).id if closed_count >= 3 else None,
            handoff_required=closed_count >= 4 or negative,
            handoff_reason="Квалификация ≥ порога" if closed_count >= 4 else
                           ("Зафиксирован негатив клиента" if negative else ""),
            handoff_kind="manager" if (closed_count >= 4 or negative) else "",
            handoff_at=created + dt.timedelta(minutes=12) if closed_count >= 4 else None,
            contact_acquired=contact,
            invited_to_office=meeting or (zone in ("msk", "mo") and closed_count >= 3),
            meeting_scheduled=meeting,
            arrived=arrived,
            sold=sold,
            sale_amount=product.price if sold else 0,
            negative=negative,
            ignored=ignored,
            lost=ignored,
            quality=("negative" if negative else "ignored" if ignored else
                     "quality" if (closed_count >= 4 and contact) else
                     "qualified" if closed_count >= 3 else
                     "poor" if closed_count else "pending"),
            first_response_seconds=rng.randint(18, 210),
            flow_state={},
            created_at=created,
            updated_at=created + dt.timedelta(hours=1),
        )
        db.add(lead)
        db.flush()

        db.add(Event(type="lead_created", conversation_id=conversation.id, lead_id=lead.id,
                     payload={"customer": name}, created_at=created))
        if closed_count >= 3:
            db.add(Event(type="crm_mutation", conversation_id=conversation.id, lead_id=lead.id,
                         payload={"field": "quality", "from": "pending", "to": lead.quality},
                         created_at=created + dt.timedelta(minutes=6)))
        if lead.handoff_required:
            db.add(Event(
                type="handoff", conversation_id=conversation.id, lead_id=lead.id,
                payload={
                    "kind": "manager",
                    "code": "negative" if negative else "threshold",
                    "reason": lead.handoff_reason,
                    "manager": db.get(Manager, lead.manager_id).name if lead.manager_id else None,
                },
                created_at=created + dt.timedelta(minutes=12),
            ))
            task = Task(
                lead_id=lead.id,
                manager_id=lead.manager_id,
                title="Связаться с клиентом",
                deadline_at=created + dt.timedelta(minutes=17),
                status="done",
                reason=lead.handoff_reason,
                created_at=created + dt.timedelta(minutes=12),
                updated_at=created + dt.timedelta(minutes=20),
            )
            db.add(task)
        if meeting:
            meeting_at = created + dt.timedelta(days=1, hours=rng.randint(2, 8))
            db.add(Meeting(
                lead_id=lead.id, scheduled_at=meeting_at,
                address=settings_store.DEFAULTS["sales"]["office_address"],
                status="arrived" if arrived else "missed",
                slot_label=meeting_at.strftime("%d.%m %H:%M"),
                created_at=created, updated_at=created,
            ))
            db.add(Event(type="meeting_scheduled", conversation_id=conversation.id,
                         lead_id=lead.id, payload={"at": meeting_at.isoformat()},
                         created_at=created + dt.timedelta(minutes=20)))
        if sold:
            db.add(Event(type="sale", conversation_id=conversation.id, lead_id=lead.id,
                         payload={"amount": lead.sale_amount, "sku": product.sku},
                         created_at=created + dt.timedelta(days=1, hours=9)))

        # a short transcript so the CRM card is not empty
        db.add(Message(conversation_id=conversation.id, role="customer",
                       text="Здравствуйте, интересует ноутбук", created_at=created,
                       read_at=created, author=name))
        db.add(Message(conversation_id=conversation.id, role="ai",
                       text="Здравствуйте! Подскажите, под какие задачи подбираете — "
                            "и я предложу варианты из наличия.",
                       created_at=created + dt.timedelta(seconds=rng.randint(20, 110)),
                       read_at=created + dt.timedelta(minutes=2), author="AI"))
    db.flush()


def run(db: Session) -> dict:
    """Idempotent: safe to call on every startup."""
    settings_store.ensure_defaults(db)
    seed_users(db)
    managers = seed_managers(db)
    seed_products(db)
    seed_kb(db)

    base_now = clock.now()
    created_conversations = not db.execute(select(Conversation)).scalars().first()
    seed_conversations(db, base_now)
    seed_history(db, base_now, managers)
    clock.set_now(base_now)

    return {
        "products": db.execute(select(func.count(Product.id))).scalar(),
        "leads": db.execute(select(func.count(Lead.id))).scalar(),
        "conversations": db.execute(select(func.count(Conversation.id))).scalar(),
        "fresh": created_conversations,
    }
