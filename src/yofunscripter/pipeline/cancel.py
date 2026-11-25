"""Cooperative cancel of a running stage.

A stage is a loop over videos/clips with ffmpeg and torch children. The GUI presses
«Отмена», the token flips, and three things happen:

  - every child process registered in the token is terminated, so the ffmpeg that is
    encoding right now stops at once;
  - `check()` raises `Cancelled` at the loop boundaries (video, clip, progress hook),
    so the stage unwinds without writing the rest of the work;
  - the worker turns `Cancelled` into one `cancelled` signal, and the window unlocks.

The token is shared: `cancel()` is called from the GUI thread, `register()` and
`check()` run in the worker thread, so the children list is locked.
"""
from __future__ import annotations

import threading


class Cancelled(Exception):
    """The user stopped the run; nothing is written after the stop."""


class CancelToken:
    """Flag + the live child processes of the run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._children: list = []

    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Loop boundary: stop the stage at once if the user pressed Cancel."""
        if self._cancelled:
            raise Cancelled()

    def register(self, proc) -> None:
        """Track a live `Popen` child; a token that is already cancelled kills it at once."""
        with self._lock:
            self._children.append(proc)
            if self._cancelled:
                _kill(proc)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            for proc in self._children:
                _kill(proc)


def _kill(proc) -> None:
    """Terminate a live child; a process that already exited is left alone."""
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass
