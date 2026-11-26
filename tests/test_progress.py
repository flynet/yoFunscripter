"""Progress meter: sums the workers, clamps to the total, throttles, one forced emission."""

from __future__ import annotations

from pathlib import Path

from yofunscripter.pipeline.progress import ProgressMeter, read_progress


def test_sum_and_clamp():
    seen = []
    meter = ProgressMeter(100, lambda done, total: seen.append((done, total)), min_s=0.0)
    meter.set("a", 40)
    meter.set("b", 40)
    meter.set("a", 500)          # over the total: clamped to 100
    assert seen[-1] == (100, 100)
    assert meter.done() == 100


def test_throttle_and_finish():
    seen = []
    meter = ProgressMeter(10, lambda done, total: seen.append((done, total)), min_s=60.0)
    meter.set("a", 2)
    meter.set("a", 3)            # same window: not emitted
    assert seen == [(2, 10)]
    meter.finish()
    assert seen[-1] == (3, 10)


def test_no_emission_when_value_did_not_move():
    seen = []
    meter = ProgressMeter(10, lambda done, total: seen.append((done, total)), min_s=0.0)
    meter.set("a", 5)
    meter.set("a", 5)
    assert seen == [(5, 10)]


def test_add_accumulates_per_key():
    meter = ProgressMeter(10, lambda done, total: None, min_s=0.0)
    meter.add("a", 2)
    meter.add("a", 3)
    meter.add("b", 1)
    assert meter.done() == 6


def test_finished_meter_ignores_late_workers():
    seen = []
    meter = ProgressMeter(10, lambda done, total: seen.append((done, total)), min_s=0.0)
    meter.set("a", 4)
    meter.finish()
    meter.set("a", 9)
    assert seen[-1] == (4, 10)


def test_progress_reads_the_last_out_time(tmp_path: Path):
    """`out_time` = время ПОСЛЕДНЕГО выхода: чанк из 16 клипов даёт 3.4 s при 135 s encoded.

    Замер Project2.mp4, чанк 0 (16 выходов, 4057 кадров): последних 12 блоков — рост
    49.8..52.6 s одного выхода, затем `N/A` и 6.7 s следующего; блоков 176 на 2983 кадра,
    то есть блок = не кадр. Полосу чанка ведёт вызывающий (база + максимум, полный чанк
    по завершении процесса), здесь проверяется только чтение файла.
    """
    f = tmp_path / "cut.txt"
    f.write_text("frame=100\nout_time=00:01:25.000000\nprogress=continue\n"
                 "frame=10\nout_time=00:00:03.400000\nprogress=continue\n", encoding="utf-8")
    assert read_progress(f) == 3.4            # the last block, not the longest output
    f.write_text("frame=1\nout_time=N/A\nprogress=continue\n", encoding="utf-8")
    assert read_progress(f) is None           # N/A is not seconds
    assert read_progress(tmp_path / "missing.txt") is None
