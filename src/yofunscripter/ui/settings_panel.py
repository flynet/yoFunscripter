"""Settings tab: language, color scheme, stage parameters, the YOLO model.

The panel writes nothing by itself: the values are applied when the user presses
«Save» (`save_requested`), the same way as in the settings dialog of PyDownload — a
change of a combo box must not restart a run that is going with the old values. «Revert»
returns the widgets to the values that are in `settings.json`, «Restart» starts a new
copy of the program, because the language is applied at startup.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from yofunscripter.config.settings import DEVICES, Settings, THEMES
from yofunscripter.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, current_language, tr
from yofunscripter.ui.widgets import set_row_floor

#: Names of the device in the language of the window, `auto` first.
DEVICE_KEYS = {"auto": "device_auto", "cpu": "device_cpu", "cuda": "device_cuda"}
THEME_KEYS = {"neon": "theme_neon", "cartoons": "theme_cartoons", "pink": "theme_pink"}


class SettingsPanel(QWidget):
    """One grid of the settings + the row of buttons: Save, Revert, Restart."""

    #: the window writes these values and applies the theme
    save_requested = Signal()
    #: the window starts a new copy of the program (the language needs a start)
    restart_requested = Signal()
    #: the window runs the check of the releases (the chain lives in `update`)
    updates_requested = Signal()
    #: the window opens the issues page of the repository in the browser
    help_requested = Signal()

    def __init__(self, settings: Settings, default_model: Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setColumnStretch(1, 1)
        row = 0

        self.language = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self.language.addItem(LANGUAGE_NAMES[code], code)
        self.language.setCurrentIndex(max(0, SUPPORTED_LANGUAGES.index(settings.language)))
        self.language.setToolTip(tr("language_tip"))
        grid.addWidget(QLabel(tr("language")), row, 0)
        grid.addWidget(self.language, row, 1)
        row += 1

        self.theme = QComboBox()
        for name in THEMES:
            self.theme.addItem(tr(THEME_KEYS[name]), name)
        self.theme.setCurrentIndex(max(0, THEMES.index(settings.theme)))
        self.theme.setToolTip(tr("theme_tip"))
        grid.addWidget(QLabel(tr("theme")), row, 0)
        grid.addWidget(self.theme, row, 1)
        row += 1

        self.jobs = QSpinBox()
        self.jobs.setRange(1, 16)
        self.jobs.setValue(settings.jobs)
        self.jobs.setToolTip(tr("jobs_tip"))
        grid.addWidget(QLabel(tr("jobs")), row, 0)
        grid.addWidget(self.jobs, row, 1)
        row += 1

        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(settings.threads)
        self.threads.setToolTip(tr("threads_tip"))
        grid.addWidget(QLabel(tr("threads")), row, 0)
        grid.addWidget(self.threads, row, 1)
        row += 1

        self.device = QComboBox()
        for name in DEVICES:
            self.device.addItem(tr(DEVICE_KEYS[name]), name)
        self.device.setCurrentIndex(max(0, DEVICES.index(settings.device)))
        self.device.setToolTip(tr("device_tip"))
        grid.addWidget(QLabel(tr("device")), row, 0)
        grid.addWidget(self.device, row, 1)
        row += 1

        self.model = QLineEdit(settings.model_path)
        self.model.setPlaceholderText(tr("model_default", path=default_model))
        self.model.setToolTip(tr("model_tip"))
        self.model.textChanged.connect(self._show_model)
        grid.addWidget(QLabel(tr("model")), row, 0)
        grid.addWidget(self.model, row, 1)
        self.browse_model = QPushButton(tr("browse"))
        self.browse_model.setObjectName("browse")
        self.browse_model.setToolTip(tr("browse_tip"))
        grid.addWidget(self.browse_model, row, 2)
        # «Reset» is the other half of the same field, so it rides the same row
        self.reset_model = QPushButton(tr("model_reset"))
        self.reset_model.setObjectName("browse")
        self.reset_model.setToolTip(tr("model_tip"))
        grid.addWidget(self.reset_model, row, 3)
        row += 1

        self.force = QCheckBox(tr("force"))
        self.force.setChecked(settings.force)
        self.force.setToolTip(tr("force_tip"))
        grid.addWidget(self.force, row, 0, 1, 3)
        row += 1

        self.no_check = QCheckBox(tr("no_check"))
        self.no_check.setChecked(settings.no_check)
        self.no_check.setToolTip(tr("no_check_tip"))
        grid.addWidget(self.no_check, row, 0, 1, 3)
        row += 1

        layout.addLayout(grid)

        # Save is the button that finishes the page, so it stands at the right of the
        # row, in the corner where a person looks for it; Revert, Restart, the update
        # check and Help are the commands of the page on the left of it.
        buttons = QHBoxLayout()
        self.revert_button = QPushButton(tr("settings_revert"))
        self.revert_button.setObjectName("browse")
        self.revert_button.setToolTip(tr("settings_revert_tip"))
        self.revert_button.clicked.connect(self._revert)
        self.restart_button = QPushButton(tr("settings_restart"))
        self.restart_button.setObjectName("browse")
        self.restart_button.setToolTip(tr("settings_restart_tip"))
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.updates_button = QPushButton(tr("check_updates"))
        self.updates_button.setObjectName("browse")
        self.updates_button.setToolTip(tr("check_updates_tip"))
        self.updates_button.clicked.connect(self.updates_requested.emit)
        self.help_button = QPushButton(tr("help"))
        self.help_button.setObjectName("browse")
        self.help_button.setToolTip(tr("help_tip"))
        self.help_button.clicked.connect(self.help_requested.emit)
        self.save_button = QPushButton(tr("settings_save"))
        self.save_button.setToolTip(tr("settings_save_tip"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save_requested.emit)
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.restart_button)
        buttons.addWidget(self.updates_button)
        buttons.addWidget(self.help_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addStretch(1)
        set_row_floor(layout)

        # the restart is useful only when the chosen language is not the running one
        self.language.currentIndexChanged.connect(self._refresh_restart)
        self._refresh_restart()

    def _show_model(self, text: str) -> None:
        """The tooltip of the model field: the path the user typed, the hint when the
        field is empty and the bundled model is the default."""
        self.model.setToolTip(text if text else tr("model_tip"))

    def _refresh_restart(self) -> None:
        """«Restart» is enabled when the chosen language is not the running language."""
        self.restart_button.setEnabled(self.language.currentData() != current_language())

    def _revert(self) -> None:
        """Return the widgets to the values that are in the settings."""
        self.language.setCurrentIndex(max(0, SUPPORTED_LANGUAGES.index(self.settings.language)))
        self.theme.setCurrentIndex(max(0, THEMES.index(self.settings.theme)))
        self.jobs.setValue(self.settings.jobs)
        self.threads.setValue(self.settings.threads)
        self.device.setCurrentIndex(max(0, DEVICES.index(self.settings.device)))
        self.model.setText(self.settings.model_path)
        self.force.setChecked(self.settings.force)
        self.no_check.setChecked(self.settings.no_check)

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
