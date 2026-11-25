"""Catalogs of the interface languages.

The catalog is a dict of dicts: `CATALOG["en"]["stage_scenes"]`. Every key is present in
English (the source of the texts), a missing Russian text falls back to English in `tr`.
"""

from yofunscripter.locales.en import TEXTS as TEXTS_EN
from yofunscripter.locales.ru import TEXTS as TEXTS_RU

CATALOG: dict[str, dict[str, str]] = {"en": TEXTS_EN, "ru": TEXTS_RU}

__all__ = ["CATALOG"]
