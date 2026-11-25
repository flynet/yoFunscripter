"""The progress panel: percent of the real work, ETA, elapsed time.

Every stage measures its work in real units — seconds of source video, frames of the
tracking loop, seconds of encoded segments — so the bar shows how much of the real work
is done, not how many files were touched. The ETA comes from the measured rate
(`units per second` of the run), so it moves with the machine, not with a guess.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QProgressBar, QVBoxLayout, QLabel, QWidget

from yofunscripter.i18n import tr
from yofunscripter.ui.widgets import fmt_time, fmt_units, set_row_floor


class ProgressPanel(QFrame):
    """Bar + one line: `{pct}% · done / total unit · ETA eta · elapsed elapsed`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.label = QLabel(tr("progress_idle"))
        self.label.setObjectName("progressLabel")
        layout.addWidget(self.label)
        tip = tr("progress_tip")
        self.setToolTip(tip)
        self.bar.setToolTip(tip)
        self.label.setToolTip(tip)
        set_row_floor(layout)
        self.stage = ""
        self.unit_key = "unit_seconds"
        self.total = 0
        self.done = 0
        self._t0 = 0.0
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self, stage: str, unit_key: str) -> None:
        """A run begins: the clock starts, the bar is zero, the ETA is unknown."""
        self.stage = stage
        self.unit_key = unit_key
        self.done = 0
        self.total = 0
        self._t0 = time.monotonic()
        self._running = True
        self.bar.setValue(0)
        self._render()
        self._timer.start()

    def update(self, done: int, total: int) -> None:
        """The meter reports the units of real work done and the total of the stage."""
        self.done = int(done)
        if total > 0:
            self.total = int(total)
        self._render()

    def finish(self, ok: bool) -> None:
        """The stage is over: the bar closes, the ETA is dropped, the elapsed stays."""
        self._running = False
        self._timer.stop()
        self.bar.setValue(100 if ok else self.bar.value())
        elapsed = time.monotonic() - self._t0 if self._t0 else 0.0
        if ok:
            self.bar.setValue(100)
            self.label.setText(f"{self.stage}: 100% · {fmt_units(self.total, self.unit_key)} "
                               f"· {fmt_time(elapsed)}")
        else:
            self.label.setText(f"{self.stage}: {fmt_time(elapsed)}")

    def _tick(self) -> None:
        self._render()

    def _render(self) -> None:
        elapsed = time.monotonic() - self._t0 if self._t0 else 0.0
        total = max(1, self.total)
        pct = min(100, int(self.done * 100 / total))
        self.bar.setValue(pct)
        eta = "—"
        if self._running and self.done > 0:
            rate = self.done / max(elapsed, 0.5)
            if rate > 0:
                eta = fmt_time((total - self.done) / rate)
        self.label.setText(tr("eta", pct=pct, done=fmt_units(self.done, self.unit_key),
                              total=fmt_units(self.total, self.unit_key),
                              eta=eta, elapsed=fmt_time(elapsed)))
