"""The single window of the app: Main (three stages, progress, console) and Settings.

Main tab: three cards — Cut scenes, Generate funscripts, Merge — each with the folders it
reads and writes and one Start button; under them the progress panel (percent of the real
work, ETA, elapsed) and the console, which every line of a stage is written to. Settings
tab: language, color scheme, jobs/threads, device, the YOLO model; the status bar carries
the Check for updates button.

A stage runs in a worker thread; the Start buttons are locked while it runs, so two stages
cannot write the same folder at the same time, and the Cancel button of the running card
stops it (`StageWorker.cancel()` -> the cancel token kills the ffmpeg children ->
`Cancelled` -> the window unlocks).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget,
                               QVBoxLayout, QWidget)

from yofunscripter.config.constants import HELP_URL, VERSION
from yofunscripter.config.paths import app_data_root, install_layout
from yofunscripter.config.settings import Settings, save_settings
from yofunscripter.i18n import current_language, tr
from yofunscripter.pipeline import funscript_stage, merge_stage, scenes_stage
from yofunscripter.pipeline.cancel import CancelToken
from yofunscripter.pipeline.paths import Layout
from yofunscripter.ui.progress_panel import ProgressPanel
from yofunscripter.ui.settings_panel import SettingsPanel
from yofunscripter.ui.stage_cards import merge_card, scenes_card, scripts_card
from yofunscripter.ui.theme import apply_theme
from yofunscripter.ui.widgets import ConsolePanel, fmt_time, set_row_floor
from yofunscripter.update import checker
from yofunscripter.update.ui import UpdateDialog, UpdateThread
from yofunscripter.workers import StageWorker


#: the ceiling of `setMaximumHeight` in Qt: the height a widget is allowed to have
#: when nothing limits it
MAX_HEIGHT = 16777215


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.layout: Layout = install_layout(settings)
        self.worker: StageWorker | None = None
        self.update_thread: UpdateThread | None = None
        #: the theme the app is painted in now, so «Save» repaints only when it changed
        self._theme = settings.theme

        self.setWindowTitle(f"{tr('app_title')} {VERSION}")
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.main_tab = QWidget()
        main_layout = QVBoxLayout(self.main_tab)
        self.main_layout = main_layout
        # the cards are blocks of their own: the window spends its height on the rows,
        # not on the gaps between them
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.scenes_card = scenes_card((self.layout.root, self.layout.scenes_dir), settings)
        self.scripts_card = scripts_card((self.layout.scenes_dir, self.layout.scripts_dir),
                                         settings)
        self.merge_card = merge_card((self.layout.scenes_dir, self.layout.scripts_dir,
                                      self.layout.result_dir), settings)
        main_layout.addWidget(self.scenes_card)
        main_layout.addWidget(self.scripts_card)
        main_layout.addWidget(self.merge_card)

        self.progress = ProgressPanel()
        main_layout.addWidget(self.progress)

        self.console = ConsolePanel()
        # the log is the rubber of the window: an open log takes every extra pixel of
        # the window, a closed log is one row of buttons and the empty space is the
        # stretch item below it, which the window is not allowed to grow into
        main_layout.addWidget(self.console)
        main_layout.addStretch(1)
        self._console_index = main_layout.indexOf(self.console)
        self._space_index = main_layout.count() - 1
        self.console.toggle.clicked.connect(self._balance_console)
        # the rows of the cards keep the height their text asks for, so a short window
        # shrinks the console, not the text of the folders: the console sets its own
        # floor (one row when closed, the readable minimum of the log when open)
        set_row_floor(main_layout)
        self.tabs.addTab(self.main_tab, tr("tab_main"))

        self.panel = SettingsPanel(settings, self.layout.model_path)
        self.tabs.addTab(self.panel, tr("tab_settings"))
        outer.addWidget(self.tabs)
        set_row_floor(outer)

        self.status = QLabel(tr("progress_idle"))
        self.statusBar().addWidget(self.status, 1)
        # «Check for updates» is a command of the settings page, not of the status line:
        # it stands with Revert, Restart, Help and Save, where a person looks for the
        # commands of the program
        self.panel.updates_requested.connect(self._check_updates)
        self.panel.help_requested.connect(self._open_help)

        self.scenes_card.start.clicked.connect(self._start_scenes)
        self.scripts_card.start.clicked.connect(self._start_scripts)
        self.merge_card.start.clicked.connect(self._start_merge)
        for card in (self.scenes_card, self.scripts_card, self.merge_card):
            card.cancel.clicked.connect(self._cancel)
        self.panel.browse_model.clicked.connect(self.panel.pick_model)
        self.panel.reset_model.clicked.connect(self._reset_model)
        # the settings are applied by the Save button of the panel, not by a change of
        # one widget: a run that is going must not pick up half of a new form
        self.panel.save_requested.connect(self._apply_settings)
        self.panel.restart_requested.connect(self._restart_app)

        for row in self.scenes_card.rows + self.scripts_card.rows + self.merge_card.rows:
            row.edit.textChanged.connect(self._sync_dirs)
        self.merge_card.extra.min_waves.valueChanged.connect(self._sync_merge)
        self.merge_card.extra.max_waves.valueChanged.connect(self._sync_merge)
        self.merge_card.extra.sort.currentIndexChanged.connect(self._sync_merge)
        self.merge_card.extra.name.textChanged.connect(self._sync_merge)

        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromHex(bytes(settings.window_geometry, "ascii")))
        # the window is drawn in the state of the log, which is closed at start: the
        # shape of the window and the shape of the log are one decision, not two
        self._balance_console()

    def log(self, line: str) -> None:
        """One line to the console and to the status line."""
        self.console.append(line)
        self.status.setText(line)

    def _balance_console(self) -> None:
        """The log is the rubber of the window: an open log takes every pixel the user
        gives the window, so dragging the window taller makes the log taller and the
        free space is the text, never an empty box. A closed log is one row of buttons:
        the window takes exactly the height of its content and cannot be dragged
        taller, so nothing stands empty under the row."""
        visible = self.console.is_open
        self.main_layout.setStretch(self._console_index, 1 if visible else 0)
        self.main_layout.setStretch(self._space_index, 0 if visible else 1)
        if visible:
            self.setMaximumHeight(MAX_HEIGHT)
            self.resize(self.width(), max(self.height(), self.sizeHint().height()))
        else:
            compact = self.sizeHint().height()
            self.setMaximumHeight(compact)
            self.resize(self.width(), compact)

    # ---------------------------------------------------------------- stages

    def _start_scenes(self) -> None:
        row = self.scenes_card.rows[0]
        if not row.edit.text().strip():
            self.log(tr("pick_source_first"))
            QMessageBox.information(self, tr("stage_scenes"), tr("pick_source_first"))
            return
        opts = scenes_stage.ScenesOptions(
            source=row.path(), out_dir=self.scenes_card.rows[1].path(),
            pattern=self.settings.pattern_scenes, jobs=self.settings.jobs,
            force=self.settings.force, no_check=self.settings.no_check,
            device=self.settings.device)
        self._launch(tr("stage_scenes"), scenes_stage.run,
                     scenes_stage.load_scenes_config(), opts, opts.source, opts.out_dir,
                     "unit_seconds")

    def _start_scripts(self) -> None:
        weights = Path(self.settings.model_path) if self.settings.model_path else None
        if weights is not None and not weights.is_file():
            self.log(tr("model_missing", path=weights))
            QMessageBox.warning(self, tr("stage_scripts"), tr("model_missing", path=weights))
            return
        opts = funscript_stage.ScriptsOptions(
            source=self.scripts_card.rows[0].path(),
            scripts_dir=self.scripts_card.rows[1].path(),
            pattern=self.settings.pattern_clips, device=self.settings.device,
            force=self.settings.force, threads=self.settings.threads, weights=weights)
        self._launch(tr("stage_scripts"), funscript_stage.run,
                     funscript_stage.load_funscript_config(), opts, opts.source,
                     opts.scripts_dir, "unit_frames")

    def _start_merge(self) -> None:
        opts = merge_stage.MergeOptions(
            clips_dir=self.merge_card.rows[0].path(),
            scripts_dir=self.merge_card.rows[1].path(),
            out_dir=self.merge_card.rows[2].path(),
            name=self.merge_card.extra.name.text().strip() or "result",
            pattern=self.settings.pattern_clips,
            min_waves=self.merge_card.extra.min_waves.value(),
            max_waves=self.merge_card.extra.max_waves.value(),
            sort_mode=self.merge_card.extra.sort_mode(),
            force=self.settings.force, no_check=self.settings.no_check)
        self._launch(tr("stage_merge"), merge_stage.run,
                     funscript_stage.load_funscript_config(), opts, opts.clips_dir,
                     opts.out_dir, "unit_seconds")

    def _launch(self, stage: str, fn, cfg: dict, opts, source: Path, out: Path,
                unit_key: str) -> None:
        """One run: the worker is started, the meter is opened, the buttons are locked."""
        if self.worker is not None and self.worker.isRunning():
            self.log(tr("one_stage"))
            QMessageBox.information(self, tr("app_title"), tr("one_stage"))
            return
        self._sync_dirs()
        self._sync_merge()
        self.log(tr("stage_start", stage=stage, source=source, out=out))
        self.progress.start(stage, unit_key)
        self._set_buttons(True)
        self.token = CancelToken()
        self.worker = StageWorker(stage, fn, cfg, opts, token=self.token, parent=self)
        self.worker.progress.connect(self.progress.update)
        self.worker.logged.connect(self.log)
        self.worker.finished_ok.connect(lambda summary: self._finished(stage, summary))
        self.worker.failed.connect(lambda reason: self._failed(stage, reason))
        self.worker.cancelled.connect(lambda: self._cancelled(stage))
        self.worker.start()

    def _cancel(self) -> None:
        """«Отмена» of the run that is going: the token flips and kills its ffmpeg children."""
        if self.worker is None or not self.worker.isRunning():
            return
        self.worker.cancel()
        self.log(tr("cancel"))

    def _set_buttons(self, running: bool) -> None:
        for card in (self.scenes_card, self.scripts_card, self.merge_card):
            card.start.setEnabled(not running)
            card.cancel.setEnabled(running)

    def _finished(self, stage: str, summary: dict) -> None:
        out = summary.get("out_dir") or summary.get("video") or summary.get("report") or ""
        elapsed = float(summary.get("elapsed_s", 0.0))
        self.log(tr("stage_done", stage=stage, elapsed=fmt_time(elapsed), out=out))
        self.progress.finish(True)
        self._set_buttons(False)

    def _failed(self, stage: str, reason: str) -> None:
        self.log(tr("stage_failed", stage=stage, reason=reason))
        self.progress.finish(False)
        self._set_buttons(False)

    def _cancelled(self, stage: str) -> None:
        """The user stopped the run: the console says it, the window is unlocked."""
        self.log(tr("stage_cancelled", stage=stage))
        self.progress.finish(False)
        self._set_buttons(False)

    # ---------------------------------------------------------------- settings

    def _sync_dirs(self) -> None:
        """The folder rows write the settings: the choices survive the run and the restart."""
        self.settings.scenes_in = self.scenes_card.rows[0].edit.text().strip()
        self.settings.scenes_out = self.scenes_card.rows[1].edit.text().strip()
        self.settings.scripts_in = self.scripts_card.rows[0].edit.text().strip()
        self.settings.scripts_out = self.scripts_card.rows[1].edit.text().strip()
        self.settings.merge_clips_in = self.merge_card.rows[0].edit.text().strip()
        self.settings.merge_scripts_in = self.merge_card.rows[1].edit.text().strip()
        self.settings.merge_out = self.merge_card.rows[2].edit.text().strip()
        self._save()

    def _sync_merge(self) -> None:
        self.settings.min_waves = self.merge_card.extra.min_waves.value()
        self.settings.max_waves = self.merge_card.extra.max_waves.value()
        self.settings.sort_mode = self.merge_card.extra.sort_mode()
        self.settings.result_name = self.merge_card.extra.name.text().strip() or "result"
        self._save()

    def _apply_settings(self) -> None:
        """«Save»: write the form into `settings.json` and apply what can be applied now."""
        for key, value in self.panel.values().items():
            setattr(self.settings, key, value)
        self._save()
        app = QApplication.instance()
        if app is not None and self.settings.theme != self._theme:
            # the color scheme is applied at once: the window repaints in the new palette
            apply_theme(app, self.settings.theme)
            self._theme = self.settings.theme
        if self.settings.language != current_language():
            self.log(tr("restart_needed"))
        else:
            self.log(tr("settings_saved"))

    def _restart_app(self) -> None:
        """«Restart»: save the form and start a new copy of the program."""
        from yofunscripter.ui.app import restart_application

        self._save()
        self.close()
        app = QApplication.instance()
        if app is not None:
            restart_application(app)

    def _reset_model(self) -> None:
        self.panel.model.setText("")

    def _save(self) -> None:
        save_settings(self.settings, app_data_root() / "settings.json")
        self.layout = install_layout(self.settings)

    def closeEvent(self, event) -> None:
        self.settings.window_geometry = bytes(QByteArray(self.saveGeometry()).toHex()).decode()
        self._save()
        super().closeEvent(event)

    # ---------------------------------------------------------------- updates

    def _open_help(self) -> None:
        """The issues page of the repository in the browser: the place where a question
        about a stage or an error is asked and answered."""
        QDesktopServices.openUrl(QUrl(HELP_URL))

    def _check_updates(self) -> None:
        if self.update_thread is not None and self.update_thread.isRunning():
            return
        self.status.setText(tr("checking"))
        self.update_thread = UpdateThread(self)
        self.update_thread.found.connect(self._show_release)
        self.update_thread.failed.connect(
            lambda reason: self.log(tr("update_failed", reason=reason)))
        self.update_thread.start()

    def _show_release(self, release) -> None:
        if release is None:
            self.status.setText(tr("no_release"))
            return
        if not checker.is_newer(VERSION, release.version):
            self.status.setText(tr("up_to_date", version=VERSION))
            return
        self.status.setText(tr("new_version", version=release.version, date=release.date))
        dialog = UpdateDialog(release, app_data_root() / "updates", self)
        dialog.exec()
        if dialog.path is not None:
            # The installer was started: this copy of the program must leave, the installer
            # closes it and launches the new version at its end.
            QApplication.closeAllWindows()
            QApplication.quit()
