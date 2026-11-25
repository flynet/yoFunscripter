"""Catalogues: both languages have every key, the same placeholders, no empty texts."""

from __future__ import annotations

import re

from yofunscripter import i18n
from yofunscripter.locales import CATALOG

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def test_languages_are_complete():
    en = CATALOG["en"]
    ru = CATALOG["ru"]
    assert set(en) == set(ru), sorted(set(en) ^ set(ru))
    for key, text in en.items():
        assert text.strip(), f"en:{key} is empty"
        assert ru[key].strip(), f"ru:{key} is empty"


def test_placeholders_match():
    for key, text in CATALOG["en"].items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(CATALOG["ru"][key])), key


def test_tr_switches_language():
    previous = i18n.set_language("ru")
    try:
        assert i18n.tr("app_title") == CATALOG["ru"]["app_title"]
        assert i18n.tr("up_to_date", version="1.0.0") == \
            CATALOG["ru"]["up_to_date"].format(version="1.0.0")
    finally:
        i18n.set_language(previous)


def test_unknown_language_is_default():
    previous = i18n.set_language("xx")
    try:
        assert i18n.current_language() == "en"
    finally:
        i18n.set_language(previous)
