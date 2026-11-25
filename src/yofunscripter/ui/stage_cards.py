"""The three cards of the main tab: Cut scenes, Generate funscripts, Merge.

Each card is the title, the hint of what the stage does, the rows of its folders, the
options of the stage (waves filter, order of clips, result name), a Start button and a
Cancel button (enabled only while a run of this card is going). The rows keep the paths
the user picked; an empty row is the default folder relative to the install dir, and the
placeholder shows that default.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from yofunscripter.i18n import tr
from yofunscripter.pipeline.funscript_select import (SORT_KEEP, SORT_MODES, SORT_RANDOM,
                                                     SORT_TICK_RATE, SORT_WAVES_ASC,
                                                     SORT_WAVES_DESC)
from yofunscripter.ui.widgets import DirRow

SORT_LABEL_KEYS = {
    SORT_TICK_RATE: "sort_tick_rate",
    SORT_WAVES_ASC: "sort_waves_asc",
    SORT_WAVES_DESC: "sort_waves_desc",
    SORT_KEEP: "sort_keep",
    SORT_RANDOM: "sort_random",
}


class StageCard(QFrame):
    """Title, hint, folder rows, extra options, Start button."""

    def __init__(self, title: str, hint: str, rows: list[DirRow],
                 extra: QWidget | None, start_label: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        head = QLabel(title)
        head.setObjectName("cardTitle")
        layout.addWidget(head)
        hint_label = QLabel(hint)
        hint_label.setObjectName("cardHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        for row in rows:
            layout.addWidget(row)
        if extra is not None:
            layout.addWidget(extra)
        self.start = QPushButton(start_label)
        self.cancel = QPushButton(tr("cancel"))
        self.cancel.setObjectName("danger")
        self.cancel.setEnabled(False)          # the button is for a run that is going
        buttons = QHBoxLayout()
        buttons.addWidget(self.start)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self.rows = rows
        self.extra = extra


class MergeOptionsWidget(QWidget):
    """Waves filter, order of clips, result name: the merge card's own options."""

    def __init__(self, min_waves: int, max_waves: int, sort_mode: str,
                 result_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        self.min_waves = QSpinBox()
        self.min_waves.setRange(0, 1000)
        self.min_waves.setValue(min_waves)
        grid.addWidget(QLabel(tr("min_waves")), 0, 0)
        grid.addWidget(self.min_waves, 0, 1)
        self.max_waves = QSpinBox()
        self.max_waves.setRange(0, 1000)
        self.max_waves.setValue(max_waves)
        grid.addWidget(QLabel(tr("max_waves")), 0, 2)
        grid.addWidget(self.max_waves, 0, 3)
        self.sort = QComboBox()
        for mode in SORT_MODES:
            self.sort.addItem(tr(SORT_LABEL_KEYS[mode]), mode)
        self.sort.setCurrentIndex(max(0, SORT_MODES.index(sort_mode)))
        grid.addWidget(QLabel(tr("sort_mode")), 1, 0)
        grid.addWidget(self.sort, 1, 1, 1, 3)
        self.name = QLineEdit(result_name)
        grid.addWidget(QLabel(tr("result_name")), 2, 0)
        grid.addWidget(self.name, 2, 1, 1, 3)

    def sort_mode(self) -> str:
        return self.sort.currentData()


def scenes_card(defaults: tuple[Path, Path], settings) -> StageCard:
    """Stage 1: source videos (the user must pick the folder) and the scenes folder."""
    rows = [DirRow(tr("label_source_videos"), defaults[0]),
            DirRow(tr("label_scenes_out"), defaults[1])]
    rows[0].set_path(settings.scenes_in)
    rows[1].set_path(settings.scenes_out)
    return StageCard(tr("stage_scenes"), tr("stage_scenes_hint"), rows, None, tr("start"))


def scripts_card(defaults: tuple[Path, Path], settings) -> StageCard:
    """Stage 2: clips (the scenes folder by default) and the sidecar folder."""
    rows = [DirRow(tr("label_clips"), defaults[0]),
            DirRow(tr("label_scripts"), defaults[1])]
    rows[0].set_path(settings.scripts_in)
    rows[1].set_path(settings.scripts_out)
    return StageCard(tr("stage_scripts"), tr("stage_scripts_hint"), rows, None, tr("start"))


def merge_card(defaults: tuple[Path, Path, Path], settings) -> StageCard:
    """Stage 3: clips, sidecars, the folder of the final file, the merge options."""
    rows = [DirRow(tr("label_clips"), defaults[0]),
            DirRow(tr("label_scripts"), defaults[1]),
            DirRow(tr("label_result_dir"), defaults[2])]
    rows[0].set_path(settings.merge_clips_in)
    rows[1].set_path(settings.merge_scripts_in)
    rows[2].set_path(settings.merge_out)
    extra = MergeOptionsWidget(settings.min_waves, settings.max_waves, settings.sort_mode,
                               settings.result_name)
    return StageCard(tr("stage_merge"), tr("stage_merge_hint"), rows, extra, tr("start"))
