# -*- mode: python ; coding: utf-8 -*-
"""Onedir build of `tools/selftest.py`: the packages the app ships, with no Qt.

    uv run --no-sync pyinstaller --clean --noconfirm tools/selftest.spec

The `collect_all` list is the same as in `yofunscripter.spec`, so a module that the app
build misses is missed here too, and the selftest prints it on the console.
"""

import os

from PyInstaller.utils.hooks import collect_all

tools_dir = os.path.abspath(SPECPATH)
app_dir = os.path.dirname(tools_dir)

datas: list = []
binaries: list = []
hiddenimports: list = []

# the same packages as yofunscripter.spec (torchvision is in the list for its
# `_C_stable` extension, which the PyInstaller hook does not find by name)
for pkg in ("ultralytics", "torchvision", "scenedetect", "cv2", "numpy", "yaml", "httpx"):
    extra_data, extra_binaries, extra_imports = collect_all(pkg)
    datas += extra_data
    binaries += extra_binaries
    hiddenimports += extra_imports

datas.append((os.path.join(app_dir, "models"), "models"))

a = Analysis(
    [os.path.join(tools_dir, "selftest.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt is not part of the check; matplotlib stays (ultralytics plotting uses it)
    excludes=["PySide6", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="selftest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="selftest")
