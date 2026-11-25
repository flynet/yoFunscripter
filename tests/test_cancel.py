"""Cancel: the token flips, the live ffmpeg is killed, the stage unwinds with `Cancelled`.

Qt-free. `popen` is stubbed, so the runner is tested without launching ffmpeg: the fake
process writes the progress file and reports itself alive until `terminate()`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yofunscripter.pipeline import progress as pr
from yofunscripter.pipeline.cancel import Cancelled, CancelToken


class FakeStderr:
    def read(self) -> bytes:
        return b"encoded 10 frames\n"


class FakeProc:
    """A child that lives until it is terminated, and writes `-progress` output."""

    def __init__(self, progress_file: Path | None = None) -> None:
        self.returncode = None
        self.stderr = FakeStderr()
        self.terminations = 0
        self.progress_file = progress_file

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminations += 1
        self.returncode = -1
        if self.progress_file is not None:
            self.progress_file.write_text("frame=10\nout_time=00:00:02.000000\n"
                                           "out_time_end_processed=\n", encoding="utf-8")


def fake_popen(progress_file: Path, seen: list):
    def popen(cmd, **kw):
        seen.append(cmd)
        proc = FakeProc(progress_file)
        progress_file.write_text("frame=1\nout_time=00:00:01.000000\n", encoding="utf-8")
        return proc
    return popen


def test_check_passes_until_the_user_stops():
    token = CancelToken()
    token.check()
    assert token.cancelled() is False
    token.cancel()
    assert token.cancelled() is True
    with pytest.raises(Cancelled):
        token.check()


def test_a_child_registered_after_the_cancel_is_killed_at_once():
    token = CancelToken()
    token.cancel()
    proc = FakeProc()
    token.register(proc)
    assert proc.terminations == 1


def test_cancel_kills_live_children_and_leaves_exited_ones():
    token = CancelToken()
    live = FakeProc()
    done = FakeProc()
    done.returncode = 0
    token.register(live)
    token.register(done)
    token.cancel()
    assert live.terminations == 1
    assert done.terminations == 0


def test_runner_is_cancelled_and_kills_its_child(tmp_path: Path, monkeypatch):
    prog = tmp_path / "p.txt"
    seen: list[list[str]] = []
    monkeypatch.setattr(pr, "popen", fake_popen(prog, seen))
    token = CancelToken()
    ticks: list[float] = []

    def on_seconds(sec: float) -> None:
        ticks.append(sec)
        if len(ticks) == 1:
            token.cancel()          # the user presses «Отмена» on the first tick

    with pytest.raises(Cancelled):
        pr.run_ffmpeg_progress(["ffmpeg", "-i", "a.mp4", "out.mp4"], prog, on_seconds,
                               token, poll_s=0.01)
    cmd = seen[0]
    # `-progress` is an output option: it goes before the output file
    assert cmd[cmd.index("-progress") + 1] == str(prog)
    assert cmd[-1] == "out.mp4"
    assert ticks[0] == 1.0
    assert not prog.exists()        # the progress file is not left in the folders


def test_a_full_run_reports_the_last_progress(tmp_path: Path, monkeypatch):
    prog = tmp_path / "p.txt"
    seen: list[list[str]] = []

    def popen(cmd, **kw):
        seen.append(cmd)
        proc = FakeProc(prog)
        prog.write_text("out_time=00:00:01.000000\n", encoding="utf-8")
        proc.returncode = 0
        return proc

    monkeypatch.setattr(pr, "popen", popen)
    ticks: list[float] = []
    code, tail = pr.run_ffmpeg_progress(["ffmpeg", "-i", "a.mp4", "out.mp4"], prog,
                                        lambda sec: ticks.append(sec), CancelToken(),
                                        poll_s=0.01)
    assert code == 0
    assert "encoded" in tail
    assert ticks[-1] == 1.0
