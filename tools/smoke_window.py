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

from PySide6.QtWidgets import (QComboBox, QLineEdit, QPushButton, QSpinBox, QApplication,
                               QWidget)

from yofunscripter.config.constants import HELP_URL
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
    check(win.console.view.minimumHeight() >= 60, "the console keeps its minimum height")

    # the log starts hidden: the window shows the folders and the bar, not the text,
    # and the button of the block says what it does in its own state
    closed_height = win.height()
    check(not win.console.view.isVisible(), "the console is hidden at start")
    check(not win.console.clear_button.isVisible(),
          "«Clear» is hidden while the console is closed")
    win.console.toggle.click()
    app.processEvents()
    check(win.console.view.isVisible() and win.console.clear_button.isVisible(),
          "opening the console shows the log and «Clear»")
    check(win.height() > closed_height, "an open log makes the window taller")
    check(win.console.toggle.text() == CATALOG["en"]["console_close"],
          "the button of an open console reads «Close console»")
    win.console.toggle.click()
    app.processEvents()
    check(not win.console.view.isVisible() and not win.console.clear_button.isVisible(),
          "closing the console hides the log and «Clear»")
    check(win.height() == closed_height, "a closed log takes the empty box back")
    check(win.console.toggle.text() == CATALOG["en"]["console_open"],
          "the button of a closed console reads «Open console»")

    # the commands of the settings page: Check for updates and Help stand on the row of
    # the buttons of the page, not in the status line (the tab is hidden, so the row is
    # checked by the y of the buttons)
    same_row = (win.panel.save_button.y() == win.panel.updates_button.y() ==
                win.panel.help_button.y() == win.panel.revert_button.y() ==
                win.panel.restart_button.y())
    check(same_row, "Check for updates and Help are on the row of the settings buttons")
    check(win.panel.help_button.toolTip() == CATALOG["en"]["help_tip"],
          "Help says what it opens")
    check(HELP_URL == "https://github.com/flynet/yoFunscripter/issues",
          f"Help opens the issues page ({HELP_URL})")

    cards = (win.scenes_card, win.scripts_card, win.merge_card)
    check(all(row.edit.minimumWidth() >= 220 for card in cards for row in card.rows),
          "the folder fields keep their minimum width")
    check(all(row.label.minimumHeight() == row.label.sizeHint().height()
              for card in cards for row in card.rows),
          "the folder labels keep the floor of their text")
    check(win.scenes_card.start.toolTip() and win.scenes_card.cancel.toolTip(),
          "the stage buttons explain themselves")
    check(all(card.start.accessibleName() and card.cancel.accessibleName()
              for card in cards),
          "the glyph buttons are named for the reader")

    # the stage buttons are in the top right corner of the card, on the line of the
    # title, so they never push the folder buttons of the rows
    top_right = all(abs(card.start.y() - card.head_label.y()) <= 2 and
                    card.start.x() > card.hint_label.x() + card.hint_label.width() and
                    card.cancel.x() > card.start.x() for card in cards)
    check(top_right, "the stage buttons are in the top right of the card")

    # the title and the hint are one line of the card, not two
    one_line = all(abs(card.head_label.y() - card.hint_label.y()) <= 2 for card in cards)
    check(one_line, "the title and the hint of a card share one line")

    # a hint is one line of text: it has the height of that line, and the full
    # explanation is its tooltip
    hints = [card.hint_label for card in cards]
    # the text of a hint is one line: the height its text asks for is the height of the
    # line (the label may be stretched taller by the buttons of the row, which is not
    # the text wrapping)
    check(all(h.sizeHint().height() <= h.fontMetrics().height() + 2 for h in hints),
          "every hint of a card is one line")
    check(all(h.toolTip() for h in hints), "the full text of a stage is in its tooltip")

    # the text of a button must fit its box: no clipped word, no wrapped word
    buttons = [w for w in widgets if isinstance(w, QPushButton)]
    clipped = [b for b in buttons
               if b.contentsRect().height() < b.fontMetrics().height()
               or b.contentsRect().width() < b.fontMetrics().horizontalAdvance(b.text())]
    check(not clipped, f"no button clips its text ({len(buttons)} buttons, "
                       f"{len(clipped)} too small)")
    for b in clipped:
        print("      clipped:", b.objectName(), repr(b.text()),
              b.contentsRect().width(), b.contentsRect().height(),
              b.fontMetrics().horizontalLength(b.text()), b.fontMetrics().height())

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
