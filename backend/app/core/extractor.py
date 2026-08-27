"""Deterministic extraction of qualification fields and behavioural signals.

This layer runs on *every* customer message, with or without an LLM key.  When a
real model is configured it refines the result (see `llm_extract`), but the rules
below are always the floor — so the demo never depends on a network call to keep
the qualification panel moving.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- geography ---------------------------------------------------------------

MOSCOW_TOKENS = ("москв", "мск", "в мск", "столиц")
# stems, so that declined forms ("в Химках", "из Мытищ") still match;
# the value is the display name, since a stem reads badly in the UI ("Понял: Химк")
MO_TOKENS: dict[str, str] = {
    "подмосков": "Московская область",
    "московская область": "Московская область",
    "мо ": "Московская область",
    "химк": "Химки",
    "балаших": "Балашиха",
    "мытищ": "Мытищи",
    "люберц": "Люберцы",
    "одинцов": "Одинцово",
    "красногорск": "Красногорск",
    "королёв": "Королёв",
    "королев": "Королёв",
    "домодедов": "Домодедово",
    "подольск": "Подольск",
    "реутов": "Реутов",
    "зеленоград": "Зеленоград",
    "щёлков": "Щёлково",
    "щелков": "Щёлково",
    "видное": "Видное",
    "долгопрудн": "Долгопрудный",
    "пушкино": "Пушкино",
}
# stem -> display name (a stem shown to the customer reads as a typo: "Казан")
REGION_CITIES: dict[str, str] = {
    "казан": "Казань", "новосибирск": "Новосибирск", "екатеринбург": "Екатеринбург",
    "нижний новгород": "Нижний Новгород", "новгород": "Нижний Новгород", "самар": "Самара", "омск": "Омск",
    "челябинск": "Челябинск", "ростов": "Ростов-на-Дону", "уфа": "Уфа",
    "красноярск": "Красноярск", "воронеж": "Воронеж", "пермь": "Пермь",
    "волгоград": "Волгоград", "краснодар": "Краснодар", "саратов": "Саратов",
    "тюмень": "Тюмень", "тольятти": "Тольятти", "ижевск": "Ижевск", "барнаул": "Барнаул",
    "ульяновск": "Ульяновск", "иркутск": "Иркутск", "хабаровск": "Хабаровск",
    "владивосток": "Владивосток", "ярославл": "Ярославль", "махачкал": "Махачкала",
    "томск": "Томск", "оренбург": "Оренбург", "кемеров": "Кемерово",
    "новокузнецк": "Новокузнецк", "рязан": "Рязань", "астрахан": "Астрахань",
    "пенз": "Пенза", "липецк": "Липецк", "тула": "Тула", "киров": "Киров",
    "чебоксар": "Чебоксары", "калининград": "Калининград", "брянск": "Брянск",
    "курск": "Курск", "иванов": "Иваново", "магнитогорск": "Магнитогорск",
    "тверь": "Тверь", "ставропол": "Ставрополь", "белгород": "Белгород", "сочи": "Сочи",
    "санкт-петербург": "Санкт-Петербург", "петербург": "Санкт-Петербург",
    "спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
}
REGION_HINTS = ("регион", "другой город", "не в москве", "из области", "не москва")

# --- tasks -------------------------------------------------------------------

TASK_PATTERNS: dict[str, tuple[str, ...]] = {
    "games": (
        "игр", "поигра", "гейм", "cyberpunk", "киберпанк", "доту", "дота", "dota", "cs2",
        "кс2", "контр-страйк", "гта", "gta", "фортнайт", "fortnite", "варзон", "warzone",
        "танки", "майнкрафт", "minecraft", "valorant", "валорант", "ведьмак", "witcher",
        "elden", "rdr2", "atomic heart", "стим", "steam", "фпс", "fps",
    ),
    "work": (
        "работ", "офис", "excel", "эксель", "документ", "1с", "1c", "бухгалт", "почт",
        "браузер", "zoom", "созвон", "таблиц", "word", "ворд",
    ),
    "study": ("учёб", "учеб", "универ", "школ", "студент", "институт", "колледж", "занят", "пары"),
    "creative": (
        "монтаж", "рендер", "видеомонтаж", "premiere", "премьер", "after effects", "фотошоп",
        "photoshop", "blender", "блендер", "3d", "3д", "моделиров", "дизайн", "автокад",
        "autocad", "solidworks", "компас", "нейросет", "stable diffusion", "обучение модел",
    ),
    "dev": (
        "программир", "разработ", "код", "docker", "докер", "виртуалк", "ide", "python",
        "джава", "java", "бэкенд", "фронтенд", "девелоп", "компиляц",
    ),
}
TASK_LABELS = {
    "games": "игры",
    "work": "работа",
    "study": "учёба",
    "creative": "графика / монтаж",
    "dev": "разработка",
}
# accusative forms, for sentences like "под игры / под работу"
TASK_LABELS_ACC = {
    "games": "игры",
    "work": "работу",
    "study": "учёбу",
    "creative": "графику и монтаж",
    "dev": "разработку",
}

# --- requirements ------------------------------------------------------------

BRANDS = {
    "asus": "ASUS", "асус": "ASUS", "rog": "ASUS", "tuf": "ASUS",
    "lenovo": "Lenovo", "леново": "Lenovo", "legion": "Lenovo", "легион": "Lenovo",
    "thinkpad": "Lenovo", "тинкпад": "Lenovo",
    "acer": "Acer", "асер": "Acer", "эйсер": "Acer", "nitro": "Acer", "predator": "Acer",
    "msi": "MSI", "мси": "MSI", "katana": "MSI", "катана": "MSI",
    "hp": "HP", "victus": "HP", "виктус": "HP", "pavilion": "HP", "omen": "HP",
    "apple": "Apple", "macbook": "Apple", "макбук": "Apple", "мак": "Apple", "эпл": "Apple",
    "dell": "Dell", "делл": "Dell", "alienware": "Dell",
    "gigabyte": "Gigabyte", "aorus": "Gigabyte",
    "huawei": "Huawei", "хуавей": "Huawei", "honor": "Honor",
}
SPEC_PATTERNS = (
    (r"rtx\s*-?\s*(\d{4})", "RTX {0}"),
    (r"gtx\s*-?\s*(\d{4})", "GTX {0}"),
    (r"rx\s*-?\s*(\d{4})", "RX {0}"),
    (r"(\d{1,3})\s*(?:гб|gb|g)\s*(?:озу|ram|оперативк|памяти)", "{0} ГБ RAM"),
    (r"(?:озу|ram|оперативк[аи])\s*(\d{1,3})\s*(?:гб|gb)", "{0} ГБ RAM"),
    (r"(\d{3})\s*(?:гц|hz)", "{0} Гц"),
    (r"i([3579])\b", "Core i{0}"),
    (r"ryzen\s*([3579])", "Ryzen {0}"),
    (r"(\d{3,4})\s*(?:гб|gb)\s*ssd", "SSD {0} ГБ"),
    (r"(\d{1,2})\s*(?:тб|tb)\s*ssd", "SSD {0} ТБ"),
)
SPEC_KEYWORDS = {
    "ssd": "SSD", "ips": "IPS", "oled": "OLED", "лёгк": "лёгкий", "легк": "лёгкий",
    "тонк": "тонкий", "автоном": "автономность", "клавиатур": "клавиатура",
    "подсветк": "подсветка", "матов": "матовый экран", "видеокарт": "дискретная видеокарта",
}

# --- recipient ---------------------------------------------------------------

GIFT_TOKENS = ("подар", "в дар", "на день рожден", "на др", "на новый год", "сюрприз")
SELF_TOKENS = ("себе", "для себя", "сам буду", "сама буду", "лично себе")
RELATIVE_TOKENS = {
    "сын": "сыну", "сыну": "сыну", "дочк": "дочери", "дочер": "дочери", "ребёнк": "ребёнку",
    "ребенк": "ребёнку", "брат": "брату", "сестр": "сестре", "жен": "жене", "муж": "мужу",
    "родител": "родителям", "пап": "папе", "мам": "маме", "друг": "другу",
    "коллег": "коллеге", "внук": "внуку", "племянник": "племяннику",
}

# --- timeframe ---------------------------------------------------------------

TIMEFRAME_PATTERNS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("прямо сейчас", "сейчас же", "в течение часа", "уже еду", "сегодня же"), "today", "сегодня"),
    (("сегодня",), "today", "сегодня"),
    (("завтра",), "tomorrow", "завтра"),
    (("послезавтра",), "3days", "послезавтра"),
    (("на этой неделе", "в течение недели", "до конца недели", "на днях", "в ближайшие дни"),
     "week", "на этой неделе"),
    (("на выходных", "в выходные", "в субботу", "в воскресенье"), "week", "на выходных"),
    (("через недел", "следующей недел", "через пару недель", "в течение двух недель"),
     "2weeks", "1-2 недели"),
    (("через месяц", "в следующем месяце", "пока смотрю", "присматрива", "не срочно",
      "определяюсь", "думаю пока"), "later", "позже / присматривается"),
)

# --- signals -----------------------------------------------------------------

NEGATIVE_TOKENS = (
    "обман", "развод", "мошен", "хамств", "ужас", "отврат", "жалоб", "верните деньги", "кинули",
    "scam", "надоел", "бесит", "грубо", "некомпетент", "не советую", "разочарован",
    "отстой", "лохотрон", "верните", "гнев", "возмущ",
)
PHONE_REQUEST_TOKENS = (
    "позвон", "наберите", "перезвон", "созвон", "по телефону", "звонок", "свяжитесь со мной",
    "давайте голосом", "call",
)
# Two sets need word boundaries rather than substrings: "ра-БОТ-ы" is not a bot,
# and "монтаж ВИДЕО" is a job description, not a request for a video.
PHOTO_REQUEST_NOISE = re.compile(r"видеомонтаж\w*|видеокарт\w*|фотошоп\w*|видеоигр\w*|монтаж\w* видео")
PHOTO_REQUEST_PATTERNS = (
    r"\bфотк\w*", r"\bфоточк\w*", r"\bвидосик\w*", r"\bснимк\w*",
    r"(?:пришл|скинь|скинуть|покаж|отправ|дайте|дай|можно|есть|будут|хочу увидеть|"
    r"посмотреть)\w*[^.!?]{0,30}\b(?:фото|видео)",
    r"\b(?:фото|видео)\w*\s+(?:товара|ноутбука|ноута|устройства|компьютера|есть|будет)",
    r"\bфото\b", r"\bфотографии\b",
)
AI_SUSPICION_PATTERNS = (
    r"\bробот\w*", r"\bбот\b", r"\bботом\b", r"\bботами\b", r"нейросет\w*", r"нейронк\w*",
    r"\bии\b", r"искусственн\w+\s+интеллект", r"автоответчик\w*", r"\bшаблон\w*",
    r"не человек", r"с человеком", r"живой человек", r"chatgpt", r"\bgpt\b",
    r"скрипт\w*\s+отвеча\w*", r"\bавтомат\w*\s+отвеча\w*",
)
SERVICE_TOKENS = (
    "гаранти", "ремонт", "сервис", "не включается", "не работает", "сломал", "неисправ",
    "брак", "почин", "обслужив", "диагностик", "battery", "не заряжа",
)
HOT_TOKENS = (
    "срочно", "прямо сейчас", "готов купить", "готова купить", "могу приехать", "приеду",
    "беру", "оформля", "наличные", "налом", "сегодня заберу", "сегодня куплю", "хочу забрать",
)
ADDRESS_TOKENS = (
    "куда приехать", "какой адрес", "где вы наход", "где находитесь", "адрес", "как доехать",
    "куда ехать", "где забрать", "где посмотреть",
)
PRICE_TOKENS = ("цена", "сколько стоит", "почём", "почем", "стоимость", "за сколько", "прайс")
DELIVERY_TOKENS = ("доставк", "отправьте", "сдэк", "почтой", "транспортн", "привезите", "курьер")
PICKUP_TOKENS = ("самовывоз", "заберу сам", "приеду сам", "заеду", "лично посмотр", "приехать")
# "можно" is deliberately absent: "Можно видео?" is a request, not agreement.
AGREE_TOKENS = ("да", "давайте", "хорошо", "ок", "окей", "подойдёт", "подойдет", "согласен",
                "удобно", "договорились", "идёт", "идет", "конечно")
DECLINE_TOKENS = ("нет", "не смогу", "не получится", "неудобно", "в другой раз", "не сегодня")

PHONE_RE = re.compile(r"(?:\+7|8|7)?[\s\-(]*(\d{3})[\s\-)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})")
GREETING_RE = re.compile(
    r"^\s*(здравствуйте|здрасте|добрый день|доброе утро|добрый вечер|привет|приветствую|здорово|хай|ку)\b",
    re.IGNORECASE,
)


@dataclass
class Extraction:
    fields: dict[str, dict] = field(default_factory=dict)
    signals: set[str] = field(default_factory=set)
    meta: dict = field(default_factory=dict)

    def add(self, key: str, value, raw: str, source: str = "rules") -> None:
        self.fields[key] = {"value": value, "raw": raw, "source": source}


def _norm(text: str) -> str:
    return " " + text.lower().replace("ё", "ё").strip() + " "


# --- budget ------------------------------------------------------------------

_BUDGET_RE_LIST = (
    # "до 100к", "до 100 000", "до 100 тысяч"
    re.compile(r"(?:до|не (?:больше|дороже|выше)|в пределах|максимум|макс|бюджет[а-я]*\s*(?:до)?)\s*"
               r"(\d[\d\s]{0,8})\s*(к\b|k\b|тыс|тр\b|т\.?р\.?|000)?"),
    # "100-120 тысяч" -> take upper bound
    re.compile(r"(\d{2,3})\s*[-–—]\s*(\d{2,3})\s*(?:к\b|тыс|т\.?р\.?)"),
    # bare "100к" / "80 тысяч" / "90тр"
    re.compile(r"(\d[\d\s]{0,8})\s*(к\b|тыс[а-я]*|тр\b|т\.?р\.?)"),
    # bare six-digit number
    re.compile(r"\b(\d{5,7})\b"),
)


def extract_budget(text: str) -> tuple[int, str] | None:
    low = text.lower().replace(" ", " ")
    if not any(ch.isdigit() for ch in low):
        return None
    # ignore pure model numbers like "rtx 4060" / "i5" / "16 гб"
    cleaned = re.sub(r"(rtx|gtx|rx|ryzen|core|i[3579])\s*-?\s*\d+", " ", low)
    cleaned = re.sub(r"\d+\s*(гб|gb|тб|tb|гц|hz|дюйм|\")", " ", cleaned)

    match = _BUDGET_RE_LIST[1].search(cleaned)
    if match:
        value = int(match.group(2)) * 1000
        return value, match.group(0).strip()

    for regex in (_BUDGET_RE_LIST[0], _BUDGET_RE_LIST[2], _BUDGET_RE_LIST[3]):
        match = regex.search(cleaned)
        if not match:
            continue
        digits = re.sub(r"\s+", "", match.group(1))
        if not digits.isdigit():
            continue
        value = int(digits)
        suffix = (match.group(2) or "") if regex.groups >= 2 else ""
        if suffix and suffix.strip() not in ("000",):
            value *= 1000
        elif value < 1000:
            value *= 1000
        if 5_000 <= value <= 1_500_000:
            return value, match.group(0).strip()
    return None


# --- geography ---------------------------------------------------------------


def extract_geo(text: str) -> tuple[str, str, str] | None:
    """Returns (zone, city, raw) where zone is msk | mo | region."""
    low = _norm(text)
    for token, city in MO_TOKENS.items():
        if token in low:
            return "mo", city, token.strip()
    for token in MOSCOW_TOKENS:
        if token in low:
            return "msk", "Москва", "Москва"
    for stem, city in REGION_CITIES.items():
        if stem in low:
            return "region", city, stem
    for hint in REGION_HINTS:
        if hint in low:
            return "region", "Регион", hint
    return None


# --- main entry point --------------------------------------------------------


def extract(text: str) -> Extraction:
    result = Extraction()
    low = _norm(text)

    # budget
    budget = extract_budget(text)
    if budget:
        result.add("budget", budget[0], budget[1])

    # geography
    geo = extract_geo(text)
    if geo:
        zone, city, raw = geo
        result.add("geo", {"zone": zone, "city": city}, raw)

    # timeframe
    for tokens, code, label in TIMEFRAME_PATTERNS:
        if any(token in low for token in tokens):
            result.add("timeframe", code, label)
            break

    # tasks
    tasks: list[str] = []
    for task, tokens in TASK_PATTERNS.items():
        if any(token in low for token in tokens):
            tasks.append(task)
    if tasks:
        result.add("tasks", tasks, ", ".join(TASK_LABELS[t] for t in tasks))

    # requirements: brand + specs
    requirements: dict = {}
    raw_bits: list[str] = []
    for token, brand in BRANDS.items():
        if re.search(rf"\b{re.escape(token)}", low):
            requirements["brand"] = brand
            raw_bits.append(brand)
            break
    specs: list[str] = []
    for pattern, template in SPEC_PATTERNS:
        match = re.search(pattern, low)
        if match:
            specs.append(template.format(*match.groups()))
    for token, label in SPEC_KEYWORDS.items():
        if token in low and label not in specs:
            specs.append(label)
    if specs:
        requirements["specs"] = specs
        raw_bits.extend(specs)
    if requirements:
        result.add("requirements", requirements, ", ".join(raw_bits))

    # recipient
    if any(token in low for token in GIFT_TOKENS):
        who = ""
        for token, label in RELATIVE_TOKENS.items():
            if token and token in low:
                who = label
                break
        result.add("recipient", {"type": "gift", "who": who}, f"подарок {who}".strip())
    elif any(token in low for token in SELF_TOKENS):
        result.add("recipient", {"type": "self", "who": ""}, "себе")
    else:
        for token, label in RELATIVE_TOKENS.items():
            if token and token in low:
                result.add("recipient", {"type": "gift", "who": label}, label)
                break

    # contact
    phone_match = PHONE_RE.search(text.replace(" ", " "))
    if phone_match and len(re.sub(r"\D", "", phone_match.group(0))) >= 10:
        digits = re.sub(r"\D", "", phone_match.group(0))[-10:]
        result.meta["phone"] = "+7" + digits
        result.signals.add("contact_given")

    # behavioural signals
    checks = (
        (NEGATIVE_TOKENS, "negative"),
        (PHONE_REQUEST_TOKENS, "phone_request"),
        (SERVICE_TOKENS, "service_question"),
        (HOT_TOKENS, "hot_intent"),
        (ADDRESS_TOKENS, "address_request"),
        (PRICE_TOKENS, "price_request"),
        (DELIVERY_TOKENS, "delivery_intent"),
        (PICKUP_TOKENS, "pickup_intent"),
    )
    for tokens, signal in checks:
        if any(token in low for token in tokens):
            result.signals.add(signal)

    # the two boundary-sensitive sets
    if any(re.search(pattern, low) for pattern in AI_SUSPICION_PATTERNS):
        result.signals.add("ai_suspicion")
    photo_text = PHOTO_REQUEST_NOISE.sub(" ", low)
    if any(re.search(pattern, photo_text) for pattern in PHOTO_REQUEST_PATTERNS):
        result.signals.add("photo_request")

    if re.search(r"подбер|подобрат|посовету|помогите выбрать|что посоветуете|какой взять", low):
        result.signals.add("selection_request")
    if GREETING_RE.match(text.strip()):
        result.signals.add("greeting")
        result.meta["greeting"] = GREETING_RE.match(text.strip()).group(1).lower()
    if re.search(r"\?", text):
        result.signals.add("question")

    # short affirmative / negative answers (used by the meeting controller).
    # The first word decides: "Да, сегодня удобно" must read as agreement.
    stripped = text.strip().lower().strip("!.,;:?…")
    first_word = re.split(r"[\s,.!?;:]+", stripped)[0] if stripped else ""
    if stripped in AGREE_TOKENS or first_word in AGREE_TOKENS:
        result.signals.add("affirmative")
    if stripped in DECLINE_TOKENS or first_word in ("нет", "неудобно"):
        result.signals.add("negative_answer")

    if "перв" in low and "половин" in low:
        result.meta["day_part"] = "morning"
        result.signals.add("day_part_answer")
    if "втор" in low and "половин" in low:
        result.meta["day_part"] = "afternoon"
        result.signals.add("day_part_answer")
    if "будн" in low:
        result.meta["week_part"] = "weekday"
        result.signals.add("week_part_answer")
    if "выходн" in low:
        result.meta["week_part"] = "weekend"
        result.signals.add("week_part_answer")

    time_match = re.search(r"(?:в|к|около|ближе к)?\s*(\d{1,2})[:.](\d{2})", text)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result.meta["time"] = f"{hour:02d}:{minute:02d}"
            result.signals.add("time_answer")
    else:
        bare = re.search(r"(?:^|\s)(?:в|к)\s*(\d{1,2})\s*(?:часов|часа|ч)?(?:\s|$)", low)
        if bare:
            hour = int(bare.group(1))
            if 8 <= hour <= 22:
                result.meta["time"] = f"{hour:02d}:00"
                result.signals.add("time_answer")

    result.meta["length"] = len(text)
    result.meta["words"] = len(text.split())
    return result


def style_profile(messages: list[str]) -> dict:
    """Mirror the customer's writing style (§14): length, tone, greeting form."""
    if not messages:
        return {"length": "short", "formal": True, "emoji": False, "avg_words": 0}
    words = [len(m.split()) for m in messages]
    avg = sum(words) / len(words)
    joined = " ".join(messages).lower()
    formal = any(t in joined for t in ("здравствуйте", "добрый день", "подскажите", "будьте добры"))
    informal = any(t in joined for t in ("привет", "хай", "здорово", "норм", "спс", "ок"))
    emoji = bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", joined))
    return {
        "length": "detailed" if avg > 18 else ("short" if avg > 4 else "very_short"),
        "formal": formal or not informal,
        "emoji": emoji,
        "avg_words": round(avg, 1),
    }
