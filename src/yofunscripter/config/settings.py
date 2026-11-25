"""User settings stored in `%APPDATA%/yoFunscripter/settings.json`.

The file is written atomically and the previous file is kept as `settings.json.bak`, so
a start that cannot read the settings takes the settings of the last save, not the
defaults. Settings survive a reinstall, and the folders the user picked with them stay
where he put them: the outputs of the stages are stored as absolute paths, and an empty
value means the default folder relative to the install dir.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from yofunscripter.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, Language
from yofunscripter.pipeline.funscript_select import SORT_MODES, SORT_TICK_RATE

ThemeName = Literal["cartoons", "neon", "pink"]
#: Neon first: it is the default of the app. The names are the style of the palette,
#: three schemes taken from PyDownload, so the window looks the same as the sister app.
THEMES: tuple[ThemeName, ...] = ("neon", "cartoons", "pink")

DeviceName = Literal["auto", "cpu", "cuda"]
#: Auto first: the model uses the GPU when it is there, `cpu` is the reproducible run,
#: `cuda` is the explicit choice of a machine with CUDA.
DEVICES: tuple[DeviceName, ...] = ("auto", "cpu", "cuda")

DEFAULT_JOBS = 1
DEFAULT_THREADS = 1
DEFAULT_MIN_WAVES = 3
DEFAULT_MAX_WAVES = 0
DEFAULT_RESULT_NAME = "result"
DEFAULT_PATTERN = "*.mp4"


@dataclass
class Settings:
    #: Language of the interface, applied at startup: a widget writes its text when it
    #: is built, so changing the language needs a restart.
    language: Language = DEFAULT_LANGUAGE
    theme: ThemeName = "neon"
    #: ffmpeg processes of stage 1 (the same parameter as the yolo run).
    jobs: int = DEFAULT_JOBS
    #: torch threads of stage 2 (the same parameter as the yolo run).
    threads: int = DEFAULT_THREADS
    device: DeviceName = "auto"
    #: Waves filter of stage 3: 0 = no filter.
    min_waves: int = DEFAULT_MIN_WAVES
    max_waves: int = DEFAULT_MAX_WAVES
    #: Order of the kept clips, the five modes of the merge.
    sort_mode: str = SORT_TICK_RATE
    #: Regenerate sidecars and re-encode segments (the `--force` of the CLI runs).
    force: bool = False
    #: Skip the checks of the merged script and of the final video.
    no_check: bool = False
    #: YOLO weights chosen by the user, `""` is the bundled `models/best.pt`.
    model_path: str = ""
    #: Stage 1: source videos, no default (the user picks the folder).
    scenes_in: str = ""
    scenes_out: str = ""
    #: Stage 2: clips (the scenes folder by default) and the sidecar folder.
    scripts_in: str = ""
    scripts_out: str = ""
    #: Stage 3: clips, sidecars, the folder of the final file.
    merge_clips_in: str = ""
    merge_scripts_in: str = ""
    merge_out: str = ""
    result_name: str = DEFAULT_RESULT_NAME
    #: Clip pattern of stage 2/3, the pattern of stage 1 (the yolo default).
    pattern_scenes: str = DEFAULT_PATTERN
    pattern_clips: str = DEFAULT_PATTERN
    console_open: bool = True
    window_geometry: str = ""


def _backup_path(path: Path) -> Path:
    """The copy of the settings the previous save left next to the file."""
    return path.parent / (path.name + ".bak")


def _read(path: Path) -> dict[str, object] | None:
    """The keys of a settings file, `None` when it is missing or damaged."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_settings(path: Path) -> Settings:
    """Read settings; a missing or damaged file falls back to the backup, then the defaults.

    Every start of the program writes the file, so a start that cannot read it loses the
    theme, the language, the folders of the stages and the model the user chose. A damaged
    `settings.json` is read from `settings.json.bak` — the file the previous save kept.
    """
    settings = Settings()
    raw = _read(path)
    if raw is None:
        raw = _read(_backup_path(path))
    if raw is None:
        return settings
    for key, value in raw.items():
        if not hasattr(settings, key):
            continue
        default = getattr(settings, key)
        if type(value) is type(default):
            setattr(settings, key, value)
    if settings.theme not in THEMES:
        settings.theme = "neon"
    if settings.language not in SUPPORTED_LANGUAGES:
        settings.language = DEFAULT_LANGUAGE
    if settings.device not in DEVICES:
        settings.device = "auto"
    if settings.sort_mode not in SORT_MODES:
        settings.sort_mode = SORT_TICK_RATE
    settings.jobs = max(1, min(16, int(settings.jobs)))
    settings.threads = max(1, min(64, int(settings.threads)))
    settings.min_waves = max(0, int(settings.min_waves))
    settings.max_waves = max(0, int(settings.max_waves))
    # An empty name would write `/.mp4`, a pattern without the star matches nothing.
    settings.result_name = settings.result_name.strip() or DEFAULT_RESULT_NAME
    for key in ("pattern_scenes", "pattern_clips"):
        pattern = str(getattr(settings, key)).strip()
        setattr(settings, key, pattern if pattern.startswith("*") else DEFAULT_PATTERN)
    return settings


def save_settings(settings: Settings, path: Path) -> None:
    """Write settings atomically and keep the previous file as the backup.

    The file is written to `settings.json.new` in the same folder and moved onto
    `settings.json` in one call, so a start that is killed in the middle of the write
    cannot leave a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(asdict(settings), ensure_ascii=False, indent=2)
    fresh = path.parent / (path.name + ".new")
    fresh.write_text(body, encoding="utf-8")
    if path.is_file():
        shutil.copy2(path, _backup_path(path))
    fresh.replace(path)
