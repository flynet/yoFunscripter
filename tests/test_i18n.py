"""Catalogues: both languages have every key, the same placeholders, no empty texts."""

from __future__ import annotations

import re
from pathlib import Path

from yofunscripter import i18n
from yofunscripter.locales import CATALOG

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
#: One call of `tr` with a literal key, as the window writes it.
TR_CALL = re.compile(r'\btr\("([a-z0-9_]+)"')


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


#: The words of the code: a person who opens the window does not know them, and the
#: interface must say the same thing in his words — «файл .funscript», not «sidecar».
JARGON = ("sidecar", "wave_rate", "tick_rate", "ffmpeg", "PySceneDetect", "torch")


def test_interface_has_no_words_of_the_code():
    for lang, texts in CATALOG.items():
        for key, text in texts.items():
            # the placeholders are names of the code inside a template, not words of the text
            low = PLACEHOLDER.sub("", text).lower()
            for word in JARGON:
                assert word not in low, f"{lang}:{key} says {word!r}: {text}"


def test_every_text_of_the_window_is_a_key():
    """A `tr("key")` in the UI must be in both catalogs: a missing text shows the key."""
    source = Path(__file__).resolve().parents[1] / "src" / "yofunscripter"
    keys = set()
    for py in sorted(source.rglob("*.py")):
        keys.update(TR_CALL.findall(py.read_text(encoding="utf-8-sig")))
    for key in sorted(keys):
        assert key in CATALOG["en"], f"en has no {key}"
        assert key in CATALOG["ru"], f"ru has no {key}"
