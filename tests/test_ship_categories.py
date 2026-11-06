"""Categorías de buque (tarea 6.4): las mismas reglas que el mapa."""

import pytest

from app.services.ship_categories import CATEGORIES, CATEGORY_RANGES, ship_category


@pytest.mark.parametrize(
    ("ship_type", "expected"),
    [
        (None, "unknown"),
        (70, "cargo"),
        (79, "cargo"),
        (80, "tanker"),
        (89, "tanker"),
        (60, "passenger"),
        (69, "passenger"),
        (31, "tug"),
        (32, "tug"),
        (50, "tug"),
        (52, "tug"),
        (30, "fishing"),
        (36, "pleasure"),
        (37, "pleasure"),
        (0, "other"),
        (33, "other"),
        (51, "other"),
        (90, "other"),
        (99, "other"),
    ],
)
def test_ship_category(ship_type: int | None, expected: str) -> None:
    assert ship_category(ship_type) == expected


def test_the_ranges_do_not_overlap() -> None:
    claimed: dict[int, str] = {}
    for category, ranges in CATEGORY_RANGES:
        for low, high in ranges:
            for code in range(low, high + 1):
                assert code not in claimed, f"{code} está en {claimed[code]} y en {category}"
                claimed[code] = category


def test_every_category_is_listed_once() -> None:
    assert len(CATEGORIES) == len(set(CATEGORIES)) == 8
    assert {ship_category(code) for code in [None, *range(100)]} == set(CATEGORIES)
