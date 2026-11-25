"""Small widgets of the window: the console panel and the folder rows.

A folder row is the label, the path the user picked, the «Browse…» button of the folder
picker and «Open» of the file manager. An empty row means the default folder relative to
the install dir, and the placeholder shows that default, so the user sees where the files
go before he picks anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from yofunscripter.i18n import tr

#: Console lines kept on screen: a long run writes thousands of lines, and the last
#: ones are the whole story of the stage.
CONSOLE_MAX_LINES = 2000
#: The console can shrink to this, never under it: the log stays readable.
CONSOLE_MIN_HEIGHT = 60


def set_row_floor(layout: QLayout) -> None:
    """Give every widget of a layout the height its own text asks for.

    A `QLineEdit` has the minimum height of zero, so a layout can squeeze a row to
    15 px and the letters of the text show half: the user reads nothing. The
    `sizeHint` of a widget is the height its font and its content ask for, and it
    becomes the floor of the widget, so the rows keep their height, the layout gets
    the minimum height it needs, and the window cannot be squeezed under it. The same
    rule as the settings dialog of PyDownload (`_set_row_floor`).
    """
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setMinimumHeight(widget.sizeHint().height())
        inner = item.layout()
        if inner is not None:
            set_row_floor(inner)


class ConsolePanel(QWidget):
    """The log of the window: one `append` per console line, the last lines stay visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        console_label = QLabel(tr("console"))
        console_label.setToolTip(tr("console_tip"))
        row.addWidget(console_label)
        row.addStretch(1)
        self.clear_button = QPushButton(tr("clear"))
        self.clear_button.setObjectName("browse")
        self.clear_button.setToolTip(tr("clear_tip"))
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        self.view = QPlainTextEdit()
        self.view.setObjectName("console")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(CONSOLE_MAX_LINES)
        self.view.setMinimumHeight(CONSOLE_MIN_HEIGHT)
        self.view.setToolTip(tr("console_tip"))
        layout.addWidget(self.view)
        self.clear_button.clicked.connect(self.view.clear)
        set_row_floor(layout)

    def append(self, line: str) -> None:
        self.view.appendPlainText(line)

    def show_console(self, visible: bool) -> None:
        self.view.setVisible(visible)


class DirRow(QWidget):
    """Label + path + Browse + Open; the empty path is the default folder.

    `tip` is the tooltip of the row: the label says what the folder is, the tooltip
    says what the stage does with it. The path field shows its full text in its own
    tooltip, so a long path stays readable when the window is narrow.
    """

    def __init__(self, label: str, default: Path, tip: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.default = default
        self.tip = tip
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setMinimumWidth(120)
        self.label.setToolTip(tip)
        layout.addWidget(self.label)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(str(default))
        self.edit.setText("")
        # a path is the text a person must read, so it has a floor in both directions
        self.edit.setMinimumWidth(220)
        self.edit.setToolTip(tip)
        self.edit.textChanged.connect(self._show_tip)
        layout.addWidget(self.edit, 1)
        self.browse = QPushButton(tr("browse"))
        self.browse.setObjectName("browse")
        self.browse.setToolTip(tr("browse_tip"))
        self.browse.clicked.connect(self._pick)
        layout.addWidget(self.browse)
        self.open = QPushButton(tr("open_folder"))
        self.open.setObjectName("browse")
        self.open.setToolTip(tr("open_folder_tip"))
        self.open.clicked.connect(self._open)
        layout.addWidget(self.open)
        set_row_floor(layout)

    def _show_tip(self, text: str) -> None:
        """The tooltip of the field: the path the user typed, the hint of the row when
        the field is empty and the default folder shows as a placeholder."""
        self.edit.setToolTip(text if text else self.tip)

    def path(self) -> Path:
        """The folder the user picked, the default when the row is empty."""
        text = self.edit.text().strip()
        return Path(text) if text else self.default

    def set_path(self, path: Path | str) -> None:
        text = str(path)
        self.edit.setText("" if text == str(self.default) else text)

    def set_default(self, default: Path) -> None:
        """The default folder changed (the install dir, the settings of the stage)."""
        self.default = default
        self.edit.setPlaceholderText(str(default))

    def _pick(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("pick_folder"),
                                                  str(self.path()))
        if folder:
            self.edit.setText(folder)

    def _open(self) -> None:
        """Open the folder in Explorer, creating it first: an empty folder the stage is
        about to write must be there, not an error of the file manager."""
        folder = self.path()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)], creationflags=0x00000008)


def fmt_time(seconds: float) -> str:
    """Seconds as `m:ss`, the ETA and the elapsed time of the progress line."""
    total = int(max(0.0, seconds))
    return f"{total // 60}:{total % 60:02d}"


def fmt_units(value: int, unit_key: str) -> str:
    """Units of the meter with the language of the user: seconds of video, frames."""
    text = tr(unit_key)
    return f"{value} {text}" if value >= 0 else str(value)
