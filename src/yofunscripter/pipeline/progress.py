"""Progress meter shared by the three stages.

Work is measured in real units (seconds of source video, frames), so the bar tracks the
real elapsed work of a run, not a file counter:

  - stage 1: seconds of source video (15% detection + 85% ffmpeg cut);
  - stage 2: frames of all clips (the tracking loop is per frame);
  - stage 3: seconds of source video (5% of the probes, 95% of the concat copy measured by
    ffmpeg `-progress`).

The meter aggregates contributions of worker threads, clamps them to the total and
throttles emissions, so the GUI is not flooded (repainting a bar per frame is pointless).

`run_ffmpeg_progress` is the ffmpeg runner for the GUI: it inserts `-progress <file>`
before the output file, ffmpeg writes `out_time` there, and the caller polls it.
The command itself (graph, flags, outputs) is unchanged, so the encode is identical to
the CLI run, and a child registered in the cancel token is killed when the user presses
Cancel.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from .cancel import Cancelled, CancelToken, _kill
from .no_window import popen


def read_progress(progress_file: Path) -> float | None:
    """out_time (seconds) from ffmpeg `-progress`: the file is appended in blocks, the
    last `out_time=` line is the current one."""
    if not progress_file.is_file():
        return None
    try:
        text = progress_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out_time = None
    for line in text.splitlines():
        if line.startswith("out_time="):
            out_time = line.split("=", 1)[1].strip()
    if out_time is None:
        return None
    parts = out_time.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return None


def run_ffmpeg_progress(cmd: list[str], progress_file: Path,
                        on_seconds: "callable | None" = None,
                        token: CancelToken | None = None,
                        poll_s: float = 0.25) -> tuple[int, str]:
    """ffmpeg with `-progress <file>`; returns (code, stderr tail).

    `-progress` is an output option, so it is inserted before the output file: appended at
    the end it applies to a following output and the file is never written.

    `token` is the user's Cancel: the process is registered in it (Cancel kills a running
    ffmpeg at once), and `Cancelled` is raised when the flag is set — the poll loop and
    the hook both watch it, so the bar stops with the encode.
    """
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    if progress_file.exists():
        progress_file.unlink()
    idx = len(cmd) - 1
    if len(cmd) >= 2 and cmd[-2] == "-o":
        idx = len(cmd) - 2
    full = cmd[:idx] + ["-progress", str(progress_file)] + cmd[idx:]
    proc = popen(full, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if token is not None:
        token.register(proc)
    cancelled = False
    while proc.poll() is None:
        if token is not None and token.cancelled():
            _kill(proc)
            cancelled = True
            break
        if on_seconds is not None:
            try:
                on_seconds(read_progress(progress_file) or 0.0)
            except Cancelled:
                _kill(proc)
                cancelled = True
                break
        time.sleep(poll_s)
    stderr = proc.stderr.read().decode("utf-8", "replace")
    tail = " | ".join(line.strip() for line in stderr.splitlines() if line.strip())
    if on_seconds is not None and not cancelled:
        on_seconds(read_progress(progress_file) or 0.0)
    # the file is only a pipe for out_time; the last read is done, so it is not left
    # in the user's folders (stage 1 writes it next to the clips)
    try:
        progress_file.unlink()
    except OSError:
        pass
    if cancelled or (token is not None and token.cancelled()):
        # the user pressed Cancel: `token.cancel()` kills the registered child, so the
        # process can also leave the loop by exiting with a signal (-1), and the stage
        # must unwind as "stopped by the user", not as an ffmpeg failure
        raise Cancelled()
    return proc.returncode, tail[-260:]


class ProgressMeter:
    """Sum of per-source contributions -> `emit(done_units, total_units)`.

    `set(key, value)` records the contribution of one source (video/clip) in units;
    `add(key, delta)` accumulates. Emission is throttled by `min_s` seconds and only
    when the value moved, plus one forced emission at `finish()`.
    """

    def __init__(self, total: float, emit, min_s: float = 0.25) -> None:
        self.total = float(total)
        self.emit = emit
        self.min_s = min_s
        self._parts: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last = 0.0
        self._last_done = -1.0
        self._finished = False

    def set(self, key: str, value: float) -> None:
        with self._lock:
            if self._finished:
                return
            self._parts[key] = max(0.0, min(value, self.total))
            self._emit_locked()

    def add(self, key: str, delta: float) -> None:
        with self._lock:
            if self._finished:
                return
            self._parts[key] = max(0.0, self._parts.get(key, 0.0) + delta)
            self._emit_locked()

    def done(self) -> float:
        with self._lock:
            return min(self.total, sum(self._parts.values()))

    def finish(self) -> None:
        with self._lock:
            self._finished = True
            self._emit_locked(force=True)

    def _emit_locked(self, force: bool = False) -> None:
        done = min(self.total, sum(self._parts.values()))
        now = time.monotonic()
        if not force:
            if done == self._last_done:
                return
            if now - self._last < self.min_s:
                return
        self._last = now
        self._last_done = done
        self.emit(int(done), int(self.total))
