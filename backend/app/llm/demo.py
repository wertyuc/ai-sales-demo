"""Deterministic provider.

Renders the reply plan produced by the pipeline into natural Russian sales copy.
No network, no key, no randomness — the same plan always yields the same text,
which is what makes the demo reproducible and the tests meaningful.
"""
from __future__ import annotations

from .base import LLMProvider, LLMResult, ReplyContext


def _variant(options: list[str], seed: int) -> str:
    return options[seed % len(options)] if options else ""


def _money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


class DemoProvider(LLMProvider):
    name = "demo"
    model = "deterministic-demo-v1"

    def generate(self, ctx: ReplyContext) -> LLMResult:
        elapsed = self._timer()
        plan = ctx.plan or {}
        style = plan.get("style") or {}
        seed = int(plan.get("seed", 0))
        formal = style.get("formal", True)
        emoji = style.get("emoji", False)
        detailed = style.get("length") == "detailed" or style.get("verbosity") == "detailed"

        parts: list[str] = []

        greeting = plan.get("greeting")
        if greeting:
            parts.append(greeting.capitalize() + "!")

        if plan.get("handoff_notice"):
            parts.append(plan["handoff_notice"])

        if plan.get("service_notice"):
            parts.append(
                "Вопрос по гарантии и сервису — передаю его в сервисный отдел, "
                "коллеги свяжутся с вами и всё подскажут."
            )

        if plan.get("acknowledge"):
            parts.append(plan["acknowledge"])

        if plan.get("out_of_stock"):
            oos = plan["out_of_stock"]
            parts.append(
                f"По {oos['title']} — этой позиции сейчас нет в наличии, "
                "не хочу вводить вас в заблуждение."
            )
            if oos.get("alternatives"):
                parts.append("Из наличия под вашу задачу есть близкие варианты:")

        if plan.get("mismatch"):
            mismatch = plan["mismatch"]
            parts.append(
                f"Сразу честно: {mismatch['title']} под {mismatch['task_label']} "
                f"не подойдёт — {mismatch['reason']}."
            )
            parts.append(
                _variant(
                    [
                        "Чтобы не потратить деньги зря, посмотрите на эти варианты:",
                        "Под эту задачу лучше подойдёт следующее:",
                    ],
                    seed,
                )
            )

        if plan.get("intro_selection"):
            parts.append(
                _variant(
                    [
                        "Сейчас задам 5-6 коротких вопросов — и подберу максимально "
                        "подходящий вариант.",
                        "Давайте я задам пару уточняющих вопросов, чтобы подобрать "
                        "именно то, что нужно.",
                    ],
                    seed,
                )
            )

        if plan.get("price_answer"):
            for row in plan["price_answer"]:
                parts.append(f"{row['title']} — от {_money(row['price'])} ₽.")

        offers = plan.get("offers") or []
        if offers:
            lines = []
            for index, offer in enumerate(offers, start=1):
                spec = f"{offer['cpu']} / {offer['gpu']} / {offer['ram']} ГБ / {offer['storage']}"
                head = f"{index}. {offer['title']} — от {_money(offer['price'])} ₽"
                if detailed:
                    lines.append(f"{head}\n   {spec}, состояние {offer['condition']}. {offer['why']}")
                else:
                    lines.append(f"{head} ({spec}, состояние {offer['condition']}) — {offer['why']}")
            parts.append("\n".join(lines))
            if plan.get("offers_note"):
                parts.append(plan["offers_note"])

        questions = plan.get("questions") or []
        if questions:
            if len(questions) == 1:
                parts.append(questions[0])
            else:
                parts.append("\n".join(f"— {q}" for q in questions))

        if plan.get("address"):
            address = plan.get("address_text", "")
            hours = plan.get("hours_text", "")
            parts.append(f"Мы находимся: {address}. Работаем {hours}.")

        if plan.get("meeting_prompt"):
            parts.append(plan["meeting_prompt"])

        if plan.get("meeting_confirmed"):
            parts.append(plan["meeting_confirmed"])

        if plan.get("photo_notice"):
            parts.append(
                "Фото и видео именно этого экземпляра подготовит менеджер — "
                "подключаю его к диалогу, материалы пришлём."
            )

        if plan.get("ask_contact"):
            parts.append(
                _variant(
                    [
                        "Оставьте, пожалуйста, ваш номер — так быстрее согласуем детали "
                        "и я закреплю за вами вариант.",
                        "Напишите номер телефона, чтобы оставаться на связи вне Авито — "
                        "пришлём подтверждение и детали.",
                    ],
                    seed,
                )
            )

        if plan.get("delivery_note"):
            parts.append(plan["delivery_note"])

        if plan.get("promo"):
            parts.append(f"И промокод на покупку: {plan['promo']}.")

        if plan.get("closing"):
            parts.append(plan["closing"])

        if not parts:
            parts.append(
                "Подскажите, пожалуйста, под какие задачи подбираете технику — "
                "и я предложу подходящие варианты из наличия."
            )

        text = "\n\n".join(p for p in parts if p)

        if not formal:
            text = text.replace("Оставьте, пожалуйста, ваш номер", "Скинь номер")
            text = text.replace("Подскажите, пожалуйста,", "Подскажи,")
        if emoji and not plan.get("handoff_notice"):
            text += " 🙂"

        return LLMResult(text=text, provider=self.name, model=self.model, latency_ms=elapsed())

    def extract(self, system: str, text: str, schema: dict) -> dict:
        return {}
