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
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from yofunscripter.i18n import tr

#: Console lines kept on screen: a long run writes thousands of lines, and the last
#: ones are the whole story of the stage.
CONSOLE_MAX_LINES = 2000


class ConsolePanel(QWidget):
    """The log of the window: one `append` per console line, the last lines stay visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("console")))
        row.addStretch(1)
        self.clear_button = QPushButton(tr("clear"))
        self.clear_button.setObjectName("browse")
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        self.view = QPlainTextEdit()
        self.view.setObjectName("console")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(CONSOLE_MAX_LINES)
        layout.addWidget(self.view)
        self.clear_button.clicked.connect(self.view.clear)

    def append(self, line: str) -> None:
        self.view.appendPlainText(line)

    def show_console(self, visible: bool) -> None:
        self.view.setVisible(visible)


class DirRow(QWidget):
    """Label + path + Browse + Open; the empty path is the default folder."""

    def __init__(self, label: str, default: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.default = default
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setMinimumWidth(120)
        layout.addWidget(self.label)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(str(default))
        self.edit.setText("")
        layout.addWidget(self.edit, 1)
        self.browse = QPushButton(tr("browse"))
        self.browse.setObjectName("browse")
        self.browse.clicked.connect(self._pick)
        layout.addWidget(self.browse)
        self.open = QPushButton(tr("open_folder"))
        self.open.setObjectName("browse")
        self.open.clicked.connect(self._open)
        layout.addWidget(self.open)

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
