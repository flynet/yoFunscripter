"""Application start: settings, language, theme, window.

`main` is the entry point of `yoFunscripter.exe` and of `python -m yofunscripter`. The
language comes from the settings and is applied right after they are read, so every window
text uses the chosen language; the theme is applied to the app before the window is shown,
so the first frame of the window is painted in the chosen scheme.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from yofunscripter.config.constants import APP_NAME, VERSION
from yofunscripter.config.paths import icon_path, settings_file
from yofunscripter.config.settings import load_settings, save_settings
from yofunscripter.i18n import set_language, tr
from yofunscripter.ui.main_window import MainWindow
from yofunscripter.ui.theme import apply_theme


def restart_command() -> tuple[str, list[str]]:
    """The command that starts this program again.

    In the built program the command is the `.exe` itself. In the source tree it is the
    interpreter with the package, the same way as `python -m yofunscripter`.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, sys.argv[1:]
    return sys.executable, ["-m", "yofunscripter"] + sys.argv[1:]


def restart_application(app: QApplication) -> None:
    """«Restart» in the settings: start a detached copy and quit this one.

    The settings are written before the call, so the new copy reads the language and the
    theme the user has just chosen. The new process inherits the working directory, so
    it finds the same folders as the running one.
    """
    exe, args = restart_command()
    QProcess.startDetached(exe, args)
    app.quit()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    icon = icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    settings = load_settings(settings_file())
    # The language is chosen once for the whole run: set it before any text is built.
    set_language(settings.language)
    # The settings file is written on every start, so a first start creates it.
    save_settings(settings, settings_file())

    window = MainWindow(settings)
    apply_theme(app, settings.theme)
    window.log(f"{tr('app_title')} {VERSION} · {settings_file()}")
    # the app opens on the full screen: the log is the part of the window that grows,
    # so the room of the screen is the room of the log, and the rows of the folders keep
    # their height. Closing the log brings the window back to the size of its content
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover - the entry point of the built program
    raise SystemExit(main())
