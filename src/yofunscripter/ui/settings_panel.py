"""Settings tab: language, color scheme, stage parameters, the YOLO model.

The panel emits the same change signal the window listens to: every change is saved to
`settings.json` at once, so a crash in the middle of a run keeps the choices the user
made. The language and the theme are applied at startup, so the window asks for a
restart when one of them is changed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from yofunscripter.config.settings import DEVICES, Settings, THEMES
from yofunscripter.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, tr

#: Names of the device in the language of the window, `auto` first.
DEVICE_KEYS = {"auto": "device_auto", "cpu": "device_cpu", "cuda": "device_cuda"}
THEME_KEYS = {"neon": "theme_neon", "cartoons": "theme_cartoons", "pink": "theme_pink"}


class SettingsPanel(QWidget):
    """One grid of the settings: the widgets the window reads and saves."""

    def __init__(self, settings: Settings, default_model: Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        row = 0

        self.language = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self.language.addItem(LANGUAGE_NAMES[code], code)
        self.language.setCurrentIndex(max(0, SUPPORTED_LANGUAGES.index(settings.language)))
        grid.addWidget(QLabel(tr("language")), row, 0)
        grid.addWidget(self.language, row, 1)
        row += 1

        self.theme = QComboBox()
        for name in THEMES:
            self.theme.addItem(tr(THEME_KEYS[name]), name)
        self.theme.setCurrentIndex(max(0, THEMES.index(settings.theme)))
        grid.addWidget(QLabel(tr("theme")), row, 0)
        grid.addWidget(self.theme, row, 1)
        row += 1

        self.jobs = QSpinBox()
        self.jobs.setRange(1, 16)
        self.jobs.setValue(settings.jobs)
        grid.addWidget(QLabel(tr("jobs")), row, 0)
        grid.addWidget(self.jobs, row, 1)
        row += 1

        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(settings.threads)
        grid.addWidget(QLabel(tr("threads")), row, 0)
        grid.addWidget(self.threads, row, 1)
        row += 1

        self.device = QComboBox()
        for name in DEVICES:
            self.device.addItem(tr(DEVICE_KEYS[name]), name)
        self.device.setCurrentIndex(max(0, DEVICES.index(settings.device)))
        grid.addWidget(QLabel(tr("device")), row, 0)
        grid.addWidget(self.device, row, 1)
        row += 1

        self.model = QLineEdit(settings.model_path)
        self.model.setPlaceholderText(tr("model_default", path=default_model))
        grid.addWidget(QLabel(tr("model")), row, 0)
        grid.addWidget(self.model, row, 1)
        self.browse_model = QPushButton(tr("browse"))
        self.browse_model.setObjectName("browse")
        grid.addWidget(self.browse_model, row, 2)
        row += 1

        self.reset_model = QPushButton(tr("model_reset"))
        self.reset_model.setObjectName("browse")
        grid.addWidget(self.reset_model, row, 1)
        row += 1

        self.force = QCheckBox(tr("force"))
        self.force.setChecked(settings.force)
        grid.addWidget(self.force, row, 0, 1, 3)
        row += 1

        self.no_check = QCheckBox(tr("no_check"))
        self.no_check.setChecked(settings.no_check)
        grid.addWidget(self.no_check, row, 0, 1, 3)
        row += 1

        layout.addLayout(grid)
        layout.addStretch(1)

    def pick_model(self) -> None:
        """Weights of YOLO: the `.pt` file the user chooses, `""` is the bundled model."""
        start = self.model.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, tr("model"), start,
                                              "YOLO weights (*.pt);;All files (*)")
        if path:
            self.model.setText(path)

    def values(self) -> dict[str, object]:
        """The settings the panel shows, ready to write into the `Settings` dataclass."""
        return {
            "language": self.language.currentData(),
            "theme": self.theme.currentData(),
            "jobs": self.jobs.value(),
            "threads": self.threads.value(),
            "device": self.device.currentData(),
            "model_path": self.model.text().strip(),
            "force": self.force.isChecked(),
            "no_check": self.no_check.isChecked(),
        }
