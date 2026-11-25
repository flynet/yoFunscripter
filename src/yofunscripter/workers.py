"""Stage workers: one `QThread` per run of a stage.

The stage functions are plain Python (no Qt), so a worker calls them with the progress,
log and cancel hooks and turns the callbacks into Qt signals. Every failure of a stage —
the `ValueError` the GUI wrapper raises, the `SystemExit` of the vendored ffmpeg runner,
an unexpected error — becomes one `failed` line, so a run never dies in silence and the
window is always unlocked again.

`cancel()` is the user's «Отмена»: it flips the token, the token terminates the ffmpeg
children it registered, and the stage raises `Cancelled` -> the `cancelled` signal.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from yofunscripter.pipeline.cancel import Cancelled, CancelToken


class StageWorker(QThread):
    """`fn(cfg, opts, on_progress=..., on_log=..., token=...)` in a thread.

    `progress(done, total)` carries the units of real work (seconds of video, frames);
    `logged(line)` is one line of the console; `finished_ok(summary)` is the summary of
    the stage; `failed(reason)` is why the stage stopped; `cancelled` is the run the user
    stopped.
    """

    progress = Signal(int, int)
    logged = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, stage: str, fn, cfg: dict, opts,
                 token: CancelToken | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stage = stage
        self.fn = fn
        self.cfg = cfg
        self.opts = opts
        self.token = token if token is not None else CancelToken()

    def cancel(self) -> None:
        """Stop the run: the flag flips, every live ffmpeg child is terminated."""
        self.token.cancel()

    def _progress(self, done: int, total: int) -> None:
        self.progress.emit(int(done), int(total))

    def _log(self, line: str) -> None:
        self.logged.emit(str(line))

    def run(self) -> None:
        try:
            summary = self.fn(self.cfg, self.opts, on_progress=self._progress,
                              on_log=self._log, token=self.token)
        except Cancelled:
            self.cancelled.emit()
            return
        except (ValueError, RuntimeError, SystemExit) as exc:
            # `ValueError` is the message the GUI stage raises; `SystemExit` is the
            # failure of the vendored ffmpeg runner. Both are the reason the user reads.
            self.failed.emit(str(exc))
            return
        except Exception as exc:            # one bad file must not kill the thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit(dict(summary))
