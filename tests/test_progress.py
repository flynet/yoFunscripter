"""Progress meter: sums the workers, clamps to the total, throttles, one forced emission."""

from __future__ import annotations

from yofunscripter.pipeline.progress import ProgressMeter


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
