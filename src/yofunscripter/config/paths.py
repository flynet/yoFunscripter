"""Where the installed application lives and what it is allowed to write.

The program is installed into one folder (the Inno Setup `{app}`): the outputs of the
stages live **in the program folder** (`scenes/`, `scripts/`, `result/`), so removing the
installation removes the files the user made, and the intermediates (scene lists, segment
cache, artifacts of the clips) live in `work/`, which the user never opens.

Settings live in `%APPDATA%/yoFunscripter/settings.json`: they survive a reinstall, and
the user can point every stage at any folder, so `%APPDATA%` stores only the choices.

When the program folder is not writable (a `Program Files` install without administrator
rights), the outputs fall back to `%LOCALAPPDATA%/yoFunscripter` — the same rule PyDownload
uses.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

from yofunscripter.config.constants import (APP_NAME, BUNDLED_DIR, DEFAULT_RESULT_DIR,
                                            DEFAULT_SCENES_DIR, DEFAULT_SCRIPTS_DIR,
                                            DEFAULT_WORK_DIR)
from yofunscripter.pipeline.paths import Layout, configure, resource_root

logger = logging.getLogger("yofunscripter.paths")


def application_dir() -> Path:
    """Folder of the program: next to `yoFunscripter.exe` or the checkout root.

    In a frozen build this is the folder the user installed the program into
    (`{app}`); in a source checkout it is the repository root, so running `run.bat`
    behaves exactly like the installed application.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def resource_dir() -> Path:
    """Folder of the files shipped with the program (`configs/`, `models/`, `bin/`, `assets/`).

    A PyInstaller build unpacks its data into `_MEIPASS`; a checkout keeps the files in
    the repository root, so `configs/funscript.yaml` is found the same way.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return application_dir()


def app_data_root() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) / APP_NAME if base else Path.home() / "AppData" / "Roaming" / APP_NAME


def local_app_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / APP_NAME if base else Path.home() / "AppData" / "Local" / APP_NAME


def settings_file() -> Path:
    return app_data_root() / "settings.json"


def icon_path() -> Path | None:
    """The window icon, `None` when the build did not ship it."""
    path = resource_dir() / "assets" / "icon.ico"
    return path if path.is_file() else None


def _writable(folder: Path) -> bool:
    """Whether a file can be created in `folder` (the outputs of the stages live there)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write-test-", delete=True):
            pass
    except OSError:
        return False
    return True


def data_root() -> Path:
    """Folder for the files the program writes: the program folder when writable.

    `scenes/`, `scripts/`, `result/` and `work/` live there, so deleting the installation
    deletes them with it. A read-only install (Program Files, no admin) keeps the data in
    LocalAppData, and the user sees the warning in the console.
    """
    app = application_dir()
    if _writable(app):
        return app
    local = local_app_data_root()
    logger.warning("program folder %s is not writable, the outputs go to %s", app, local)
    return local


def _bundled(name: str) -> str:
    """Bundled binary of `bin/`, the system one as the fallback."""
    path = resource_dir() / BUNDLED_DIR / name
    if path.is_file():
        return str(path)
    found = shutil.which(name)
    return found if found else name


def app_layout(settings) -> Layout:
    """Layout of the app for the settings: user dirs win, install dirs are the defaults.

    An empty string in the settings means the default folder relative to the install dir,
    so the defaults of the spec (`./scenes`, `./scripts`, `./result`) work from the first
    start, and a user who chose his own folders keeps them. Stage 1 has no default input:
    the user must pick the source folder.
    """
    root = data_root()
    resources = resource_dir()

    def pick(value: str, default: str) -> Path:
        return Path(value) if value else root / default

    return Layout(
        root=root,
        resources=resources,
        scenes_dir=pick(settings.scenes_out, DEFAULT_SCENES_DIR),
        scripts_dir=pick(settings.scripts_out, DEFAULT_SCRIPTS_DIR),
        result_dir=pick(settings.merge_out, DEFAULT_RESULT_DIR),
        work_dir=root / DEFAULT_WORK_DIR,
        model_path=Path(settings.model_path) if settings.model_path
        else resources / "models" / "best.pt",
        ffmpeg_bin=_bundled("ffmpeg.exe"),
        ffprobe_bin=_bundled("ffprobe.exe"),
    )


def install_layout(settings) -> Layout:
    """`app_layout` applied to the pipeline modules, so the stages see the same dirs.

    The vendored pipeline resolves `ROOT / cfg["out_dir"]` through the module globals;
    `configure` refreshes them and returns the layout the GUI hands to the stages.
    """
    lay = app_layout(settings)
    return configure(root=lay.root, scenes_dir=lay.scenes_dir, scripts_dir=lay.scripts_dir,
                     result_dir=lay.result_dir, work_dir=lay.work_dir,
                     model_path=lay.model_path, ffmpeg_bin=lay.ffmpeg_bin,
                     ffprobe_bin=lay.ffprobe_bin)
