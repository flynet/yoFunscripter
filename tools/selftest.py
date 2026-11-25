"""Selftest of the frozen build: the imports the stages load at runtime.

PyInstaller reports nothing about a module imported inside a function (`import torch` and
`from ultralytics import YOLO` run when stage 2 starts), so a missing hidden import shows
only as a window that says "no module named ...". This program imports them in the frozen
build and loads the bundled model, so the same failure prints on the console:

    uv run --no-sync pyinstaller --clean --noconfirm tools/selftest.spec
    dist\\selftest\\selftest.exe

`--no-sync` keeps the wheels of the venv, so a CUDA venv builds a CUDA selftest.

It builds the same packages as `yofunscripter.spec` (`collect_all` of ultralytics,
scenedetect, cv2, numpy, yaml, httpx) with no Qt, so the check is fast and reads one
line: `OK`.
"""
import sys
from pathlib import Path

import cv2
import httpx
import numpy
import scenedetect
import torch
import yaml
from ultralytics import YOLO

model = Path(sys._MEIPASS) / "models" / "best.pt"
m = YOLO(str(model))
print("torch", torch.__version__, "cuda available", torch.cuda.is_available(),
      "cuda runtime", torch.version.cuda)
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    # one frame of inference on the GPU: the device is real, not just reported
    frame = __import__("numpy").zeros((360, 640, 3), dtype=__import__("numpy").uint8)
    r = m(frame, device=0, verbose=False)[0]
    print("gpu inference ok, detections", len(r.boxes))
print("cv2", cv2.__version__)
print("scenedetect", scenedetect.__version__)
print("numpy", numpy.__version__)
print("ultralytics", __import__("ultralytics").__version__)
print("model", model.name, model.stat().st_size, "classes", len(m.names))
print("OK")
