"""Offscreen check of the window: the default theme, the tooltips, the floors.

    python tools/smoke_window.py

The window is built by the same code the app runs, so the checks are about the real
window: the default palette is applied, every control has the tooltip that explains it,
the rows keep the height their text asks for, and the order combo shows the meaning of
the order that is chosen. The script prints `ok` per check and exits 1 on any failure.
It opens no files and runs no stage, so it is safe on a machine with the app installed.
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox, QApplication, QWidget

from yofunscripter.config.settings import Settings
from yofunscripter.i18n import set_language
from yofunscripter.locales import CATALOG
from yofunscripter.pipeline.funscript_select import SORT_LABEL_KEYS
from yofunscripter.ui.main_window import MainWindow
from yofunscripter.ui.theme import PALETTES, apply_theme

fails: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("ok  " if cond else "FAIL") + " " + label)
    if not cond:
        fails.append(label)


def walk(widget: QWidget, found: list[QWidget]) -> None:
    found.append(widget)
    for child in widget.children():
        if isinstance(child, QWidget):
            walk(child, found)


def main() -> int:
    s = Settings()
    check(s.theme == "neon", "the default theme is neon")
    check(s.language == "en", "the default language is English")

    app = QApplication([])
    apply_theme(app, s.theme)
    check(app.palette().window().color().name() == PALETTES["neon"]["background"].lower(),
          "the palette of the default theme is applied")
    set_language("en")
    win = MainWindow(s)
    win.show()
    app.processEvents()

    widgets: list[QWidget] = []
    walk(win, widgets)
    # the inner line edit of a spin box shows the tooltip of its spin box
    inputs = [w for w in widgets if isinstance(w, (QComboBox, QLineEdit, QSpinBox))
              and w.objectName() != "qt_spinbox_lineedit"]
    missing = [w for w in inputs if not w.toolTip()]
    check(not missing, f"every control explains itself ({len(inputs)} controls, "
                       f"{len(missing)} without a tooltip)")
    for w in missing:
        print("      no tooltip:", type(w).__name__, w.objectName())
    check(len([w for w in widgets if w.toolTip()]) >= 40,
          f"the window carries {len([w for w in widgets if w.toolTip()])} tooltips")

    minimum = win.minimumSize()
    check(minimum.width() >= 600 and minimum.height() >= 500,
          f"the window has a readable minimum size ({minimum.width()}x{minimum.height()})")
    check(win.console.minimumHeight() >= 60, "the console keeps its minimum height")

    cards = (win.scenes_card, win.scripts_card, win.merge_card)
    check(all(row.edit.minimumWidth() >= 220 for card in cards for row in card.rows),
          "the folder fields keep their minimum width")
    check(all(row.label.minimumHeight() == row.label.sizeHint().height()
              for card in cards for row in card.rows),
          "the folder labels keep the floor of their text")
    check(win.scenes_card.start.toolTip() and win.scenes_card.cancel.toolTip(),
          "Start and Cancel explain themselves")

    combo = win.merge_card.extra.sort
    check(combo.count() == len(SORT_LABEL_KEYS), "the order combo lists every order")
    for i in range(combo.count()):
        combo.setCurrentIndex(i)
        app.processEvents()
        key = SORT_LABEL_KEYS[combo.itemData(i)] + "_tip"
        check(combo.toolTip() == CATALOG["en"][key], f"the order {key} shows its meaning")

    check(not any("sidecar" in text.lower() for text in CATALOG["en"].values()),
          "the interface has no words of the code")
    win.close()
    print("failures:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
