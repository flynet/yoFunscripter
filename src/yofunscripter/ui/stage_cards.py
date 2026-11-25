"""The three cards of the main tab: Cut scenes, Generate funscripts, Merge.

Each card is one line of text (the title and what the stage does), the rows of its
folders, the options of the stage (waves filter, order of clips, result name), and the
two stage buttons at the end of the last folder row: the play arrow runs the stage, the
square stops it, the same glyphs as any video player. A word («Start», «Cancel») takes a
row of its own, a glyph does not, so the window stays short; the name of each button is
in its tooltip. The rows keep the paths the user picked; an empty row is the default
folder relative to the install dir, and the placeholder shows that default.

Every line of the card carries its own tooltip (`*_tip` keys of the catalog), so a
person who does not know the words of the pipeline sees what a setting does without
reading a manual, and every widget has the height its text asks for (`set_row_floor`),
so the window cannot be squeezed into unreadable rows.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QStyle, QVBoxLayout, QWidget)

from yofunscripter.i18n import tr
from yofunscripter.pipeline.funscript_select import SORT_LABEL_KEYS, SORT_MODES
from yofunscripter.ui.widgets import DirRow, media_button, set_row_floor

#: The tooltip of each order, so the combo explains itself: «waves» and «ticks» are the
#: two numbers a person has to tell apart. The labels of the modes are in
#: `funscript_select`, where the merge log reads them too.
SORT_TIP_KEYS = {mode: SORT_LABEL_KEYS[mode] + "_tip" for mode in SORT_LABEL_KEYS}


class StageCard(QFrame):
    """One line of text, the folder rows with the stage buttons, the extra options."""

    def __init__(self, title: str, hint: str, tip: str, rows: list[DirRow],
                 extra: QWidget | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        # the card is one block of text, not a stack of gaps: the title and the hint
        # share the first line, and the rows sit on 4 px of spacing
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        head_label = QLabel(title)
        head_label.setObjectName("cardTitle")
        head_label.setToolTip(tip)
        head.addWidget(head_label)
        hint_label = QLabel(hint)
        hint_label.setObjectName("cardHint")
        hint_label.setToolTip(tip)
        head.addWidget(hint_label, 1)
        layout.addLayout(head)
        for row in rows:
            layout.addWidget(row)
        if extra is not None:
            layout.addWidget(extra)
        # the stage buttons ride the last folder row: a play arrow and a square, the
        # glyphs of a player, no word, so no row is spent on them
        self.start = media_button(QStyle.StandardPixmap.SP_MediaPlay, tr("start_tip"),
                                  tr("start"), self)
        self.cancel = media_button(QStyle.StandardPixmap.SP_MediaStop, tr("cancel_tip"),
                                   tr("cancel"), self)
        self.cancel.setObjectName("mediaDanger")
        self.cancel.setEnabled(False)          # the button is for a run that is going
        rows[-1].add_tail(self.start)
        rows[-1].add_tail(self.cancel)
        set_row_floor(layout)
        self.rows = rows
        self.extra = extra
        self.head_label = head_label
        self.hint_label = hint_label


class MergeOptionsWidget(QWidget):
    """Waves filter, order of clips, result name: the merge card's own options."""

    def __init__(self, min_waves: int, max_waves: int, sort_mode: str,
                 result_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        grid.setColumnStretch(1, 1)
        self.min_waves = QSpinBox()
        self.min_waves.setRange(0, 1000)
        self.min_waves.setValue(min_waves)
        self.min_waves.setToolTip(tr("min_waves_tip"))
        grid.addWidget(QLabel(tr("min_waves")), 0, 0)
        grid.addWidget(self.min_waves, 0, 1)
        self.max_waves = QSpinBox()
        self.max_waves.setRange(0, 1000)
        self.max_waves.setValue(max_waves)
        self.max_waves.setToolTip(tr("max_waves_tip"))
        grid.addWidget(QLabel(tr("max_waves")), 0, 2)
        grid.addWidget(self.max_waves, 0, 3)
        self.sort = QComboBox()
        for mode in SORT_MODES:
            self.sort.addItem(tr(SORT_LABEL_KEYS[mode]), mode)
        self.sort.setCurrentIndex(max(0, SORT_MODES.index(sort_mode)))
        # a combo has no per-item tooltip, so the tooltip of the combo explains the order
        # that is chosen and follows the choice
        self.sort.setToolTip(tr(SORT_TIP_KEYS[self.sort.currentData()]))
        self.sort.currentIndexChanged.connect(self._show_sort)
        sort_label = QLabel(tr("sort_mode"))
        sort_label.setToolTip(tr("sort_mode_tip"))
        grid.addWidget(sort_label, 1, 0)
        grid.addWidget(self.sort, 1, 1, 1, 3)
        self.name = QLineEdit(result_name)
        self.name_label = QLabel(tr("result_name"))
        grid.addWidget(self.name_label, 2, 0)
        grid.addWidget(self.name, 2, 1, 1, 3)
        self._show_name(self.name.text())
        self.name.textChanged.connect(self._show_name)
        set_row_floor(grid)

    def _show_sort(self) -> None:
        """The tooltip of the order that is chosen, in the language of the window."""
        self.sort.setToolTip(tr(SORT_TIP_KEYS[self.sort.currentData()]))

    def _show_name(self, text: str) -> None:
        """The tooltip says which files the name writes, in the language of the window."""
        tip = tr("result_name_tip", name=text.strip() or "result")
        self.name.setToolTip(tip)
        self.name_label.setToolTip(tip)

    def sort_mode(self) -> str:
        return self.sort.currentData()


def scenes_card(defaults: tuple[Path, Path], settings) -> StageCard:
    """Stage 1: source videos (the user must pick the folder) and the scenes folder."""
    rows = [DirRow(tr("label_source_videos"), defaults[0], tr("label_source_videos_tip")),
            DirRow(tr("label_scenes_out"), defaults[1], tr("label_scenes_out_tip"))]
    rows[0].set_path(settings.scenes_in)
    rows[1].set_path(settings.scenes_out)
    return StageCard(tr("stage_scenes"), tr("stage_scenes_hint"), tr("stage_scenes_tip"),
                     rows, None)


def scripts_card(defaults: tuple[Path, Path], settings) -> StageCard:
    """Stage 2: clips (the scenes folder by default) and the funscript folder."""
    rows = [DirRow(tr("label_clips"), defaults[0], tr("label_clips_tip")),
            DirRow(tr("label_scripts"), defaults[1], tr("label_scripts_tip"))]
    rows[0].set_path(settings.scripts_in)
    rows[1].set_path(settings.scripts_out)
    return StageCard(tr("stage_scripts"), tr("stage_scripts_hint"), tr("stage_scripts_tip"),
                     rows, None)


def merge_card(defaults: tuple[Path, Path, Path], settings) -> StageCard:
    """Stage 3: clips, funscripts, the folder of the final file, the merge options."""
    rows = [DirRow(tr("label_clips"), defaults[0], tr("label_clips_tip")),
            DirRow(tr("label_scripts"), defaults[1], tr("label_scripts_tip")),
            DirRow(tr("label_result_dir"), defaults[2], tr("label_result_dir_tip"))]
    rows[0].set_path(settings.merge_clips_in)
    rows[1].set_path(settings.merge_scripts_in)
    rows[2].set_path(settings.merge_out)
    extra = MergeOptionsWidget(settings.min_waves, settings.max_waves, settings.sort_mode,
                               settings.result_name)
    return StageCard(tr("stage_merge"), tr("stage_merge_hint"), tr("stage_merge_tip"),
                     rows, extra)
