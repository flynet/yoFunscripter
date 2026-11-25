"""Resource and data directories for the packaged app.

Three roots, resolved once per run:

  - `resource_root()` — bundled read-only data (configs, default model, bin/ffmpeg).
    Under PyInstaller onedir this is `_MEIPASS` (`<install>/_internal`), in a source
    checkout it is the repo root.
  - `app_root()` — the writable install directory: default `scenes/`, `scripts/`,
    `result/` and the pipeline work dir live here, relative to the program location,
    as the user expects from the spec.
  - `settings_dir()` — `%APPDATA%\\YoFunscripter` (settings.json, logs).

The pipeline modules resolve `ROOT / cfg["out_dir"]`, so `ROOT` is the app root and
`out_dir` / `concat_dir` in configs are relative work subdirectories. `configure()` is
called once at startup from the saved settings; the pipeline reads `layout()`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "YoFunscripter"


def resource_root() -> Path:
    """Bundled data dir: `_MEIPASS` when frozen, repo root in a source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def app_root() -> Path:
    """Writable install dir: the program folder (where defaults ./scenes live)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def settings_dir() -> Path:
    local = Path.home() / "AppData" / "Roaming" / APP_NAME
    if local.is_dir() or not local.parent.is_dir():
        return local
    return Path.home() / "AppData" / "Local" / APP_NAME


@dataclass(frozen=True)
class Layout:
    root: Path           # writable install dir
    resources: Path      # bundled configs / models / bin
    scenes_dir: Path     # stage 1 output, stage 2+3 input
    scripts_dir: Path    # stage 2 output (.funscript sidecars)
    result_dir: Path     # stage 3 output
    work_dir: Path       # pipeline artifacts (track.csv, segments, reports)
    model_path: Path     # YOLO weights, default bundled models/best.pt
    ffmpeg_bin: str      # bundled bin/ffmpeg.exe resolved to an absolute path
    ffprobe_bin: str


_LAYOUT: Layout | None = None


def configure(root: Path | None = None, *, scenes_dir: Path | None = None,
             scripts_dir: Path | None = None, result_dir: Path | None = None,
             work_dir: Path | None = None, model_path: Path | None = None,
             ffmpeg_bin: str | None = None, ffprobe_bin: str | None = None) -> Layout:
    """Resolve the layout once at startup; all defaults come from the install dir.

    `ROOT` is a module global in the vendored pipeline (`ROOT / cfg["out_dir"]`), so it
    is refreshed here: the pipeline keeps the yolo convention, the paths become absolute.
    """
    root = Path(root) if root else app_root()
    res = resource_root()
    global _LAYOUT
    _LAYOUT = Layout(
        root=root,
        resources=res,
        scenes_dir=Path(scenes_dir) if scenes_dir else root / "scenes",
        scripts_dir=Path(scripts_dir) if scripts_dir else root / "scripts",
        result_dir=Path(result_dir) if result_dir else root / "result",
        work_dir=Path(work_dir) if work_dir else root / "work",
        model_path=Path(model_path) if model_path else res / "models" / "best.pt",
        ffmpeg_bin=_resolve_bin(ffmpeg_bin, res, "ffmpeg.exe"),
        ffprobe_bin=_resolve_bin(ffprobe_bin, res, "ffprobe.exe"),
    )
    from . import funscript_common, scenedetect_run
    funscript_common.ROOT = _LAYOUT.root
    funscript_common.FUNSCRIPT_CONFIG = funscript_config()
    scenedetect_run.ROOT = _LAYOUT.root
    scenedetect_run.SCENES_CONFIG = scenes_config()
    return _LAYOUT


def _resolve_bin(name: str | None, res: Path, exe: str) -> str:
    """Bundled binary wins; a user override (or plain PATH name) is honoured."""
    if name:
        candidate = Path(name)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
        bundled = res / "bin" / candidate.name
        if bundled.is_file():
            return str(bundled)
        return name
    bundled = res / "bin" / exe
    return str(bundled) if bundled.is_file() else exe


def layout() -> Layout:
    global _LAYOUT
    if _LAYOUT is None:
        _LAYOUT = configure()
    return _LAYOUT


def funscript_config() -> Path:
    return resource_root() / "configs" / "funscript.yaml"


def scenes_config() -> Path:
    return resource_root() / "configs" / "scenes.yaml"


def classes_config() -> Path:
    return resource_root() / "configs" / "classes.yaml"


def model_path(cfg: dict) -> Path:
    """Weights из configs/funscript.yaml: relative путь ищет в бандле, потом в install dir.

    GUI перекрывает модель значением из настроек (абсолютный путь), CLI-прогон yolo
    использует этот резолвер, чтобы `weights: models/best.pt` работал и в exe, и в
    исходном checkout.
    """
    w = Path(str(cfg["weights"]))
    if w.is_absolute():
        return w
    lay = layout()
    for base in (lay.resources, lay.root):
        cand = base / w
        if cand.is_file():
            return cand
    return lay.resources / w
