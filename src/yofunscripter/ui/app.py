"""Application start: settings, language, theme, window.

`main` is the entry point of `yoFunscripter.exe` and of `python -m yofunscripter`. The
language comes from the settings and is applied right after they are read, so every window
text uses the chosen language; the theme is applied to the app before the window is shown,
so the first frame of the window is painted in the chosen scheme.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from yofunscripter.config.constants import APP_NAME, VERSION
from yofunscripter.config.paths import icon_path, settings_file
from yofunscripter.config.settings import load_settings, save_settings
from yofunscripter.i18n import set_language, tr
from yofunscripter.ui.main_window import MainWindow
from yofunscripter.ui.theme import apply_theme


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
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover - the entry point of the built program
    raise SystemExit(main())
