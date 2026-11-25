"""Каждый процесс ffmpeg/ffprobe идёт без окна консоли.

Установленное приложение — оконная программа (PyInstaller windowed): когда оно запускает
консольного ребёнка (ffmpeg, ffprobe) и у самого приложения консоли нет, Windows даёт
ребёнку новое консольное окно, и такое окно всплывает на каждый процесс реза.
`CREATE_NO_WINDOW` оставляет процесс в фоне. Все запуски пайплайна идут через `run` и
`popen` этого модуля; на не-Windows флаг не передаётся.
"""
from __future__ import annotations

import subprocess
import sys

#: CREATE_NO_WINDOW: ребёнок получает окно, но оно не показывается.
NO_WINDOW = 0x08000000


def _flags(kw: dict) -> dict:
    """`creationflags` с флагом фонового окна, только для Windows."""
    if sys.platform == "win32":
        kw["creationflags"] = NO_WINDOW | kw.get("creationflags", 0)
    return kw


def run(cmd: list[str], **kw):
    """`subprocess.run` без окна консоли у ребёнка."""
    return subprocess.run(cmd, **_flags(kw))


def popen(cmd: list[str], **kw):
    """`subprocess.Popen` без окна консоли у ребёнка."""
    return subprocess.Popen(cmd, **_flags(kw))
