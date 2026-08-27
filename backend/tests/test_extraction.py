"""Qualification extraction and scoring."""
from __future__ import annotations

import pytest

from app.core import settings_store
from app.core.extractor import extract
from app.core.qualification import compute, merge


def signals_of(text: str) -> set[str]:
    return extract(text).signals


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Нужен игровой ноут до 100 тысяч", 100_000),
        ("бюджет 80к", 80_000),
        ("готов потратить до 150 000", 150_000),
        ("в пределах 90 тыс", 90_000),
        ("не дороже 120к", 120_000),
    ],
)
def test_budget_extraction(text, expected):
    assert extract(text).fields["budget"]["value"] == expected


def test_spec_numbers_are_not_budgets():
    """"RTX 4060" and "16 ГБ" must never be read as money."""
    result = extract("Хочу с RTX 4060 и 16 ГБ оперативки, 144 Гц")
    assert "budget" not in result.fields


@pytest.mark.parametrize(
    "text,zone",
    [
        ("я в Москве", "msk"),
        ("живу в Химках", "mo"),
        ("Я из Казани", "region"),
        ("мы в Санкт-Петербурге", "region"),
    ],
)
def test_geo_zones(text, zone):
    assert extract(text).fields["geo"]["value"]["zone"] == zone


def test_multiple_fields_from_one_sentence():
    """The §25 requirement: never re-ask what the customer already volunteered."""
    result = extract("Я в Москве, нужен игровой ноут до 100 тысяч, купить хочу сегодня")
    assert result.fields["geo"]["value"]["zone"] == "msk"
    assert result.fields["budget"]["value"] == 100_000
    assert result.fields["timeframe"]["value"] == "today"
    assert "games" in result.fields["tasks"]["value"]


def test_gift_recipient():
    result = extract("Хочу купить в подарок сыну на день рождения")
    assert result.fields["recipient"]["value"] == {"type": "gift", "who": "сыну"}


def test_phone_capture():
    assert extract("мой номер +7 916 245-18-30").meta["phone"] == "+79162451830"


# --- signal accuracy: these were real false positives ------------------------


def test_rabota_is_not_a_bot():
    assert "ai_suspicion" not in signals_of("нужен ноутбук для работы и монтажа видео")


def test_videomontage_is_not_a_photo_request():
    assert "photo_request" not in signals_of("Занимаюсь видеомонтажом и рендером")


def test_photoshop_is_not_a_photo_request():
    assert "photo_request" not in signals_of("Работаю в фотошопе целыми днями")


def test_real_photo_request_is_detected():
    assert "photo_request" in signals_of("Пришлите фото товара пожалуйста")


def test_real_ai_suspicion_is_detected():
    assert "ai_suspicion" in signals_of("У меня ощущение, что я с роботом разговариваю")


def test_affirmative_with_punctuation():
    assert "affirmative" in signals_of("Да, сегодня удобно")


# --- scoring -----------------------------------------------------------------


def test_score_uses_configured_weights(db):
    config = settings_store.get_section(db, "qualification")
    state: dict = {}
    merge(state, extract("Я в Москве, игровой ноут до 100 тысяч, беру сегодня"))
    stats = compute(state, config)
    assert stats["closed_count"] == 4
    assert stats["qualified"] is True
    assert 70 <= stats["score"] <= 80


def test_threshold_is_configuration_not_constant(db):
    config = dict(settings_store.get_section(db, "qualification"))
    state: dict = {}
    merge(state, extract("Москва, игры, до 100 тысяч"))
    config["handoff_threshold"] = 40
    assert compute(state, config)["over_threshold"] is True
    config["handoff_threshold"] = 99
    assert compute(state, config)["over_threshold"] is False


def test_region_rule_needs_four_fields(db):
    config = settings_store.get_section(db, "qualification")
    state: dict = {}
    merge(state, extract("Я из Казани, нужен ноут"))
    assert compute(state, config)["region_rule"] is False
    merge(state, extract("до 150 тысяч, для работы, куплю на этой неделе"))
    assert compute(state, config)["region_rule"] is True
