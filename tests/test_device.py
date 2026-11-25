"""The device of stage 2: `cuda` falls back to the CPU when torch has no CUDA."""

import sys

import pytest

from yofunscripter.pipeline.funscript_stage import _device


class _Torch:
    """A torch stub: only `cuda.is_available` matters for the device choice."""

    def __init__(self, available: bool):
        self.cuda = type("cuda", (), {"is_available": staticmethod(lambda: available)})


@pytest.fixture
def no_cuda(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _Torch(False))


@pytest.fixture
def with_cuda(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _Torch(True))


def test_cuda_falls_back_to_cpu(no_cuda):
    lines = []
    assert _device("cuda", lines.append) == "cpu"
    assert "CUDA" in lines[0]


def test_cuda_used_when_torch_sees_the_gpu(with_cuda):
    lines = []
    assert _device("cuda", lines.append) == 0
    assert lines == []


def test_auto_and_cpu(no_cuda, with_cuda):
    assert _device("auto") is None
    assert _device("") is None
    assert _device("cpu") == "cpu"


def test_no_log_hook_is_ok(no_cuda):
    assert _device("cuda") == "cpu"
