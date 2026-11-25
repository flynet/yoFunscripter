# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification of yoFunscripter.

One directory build: `dist/yoFunscripter/yoFunscripter.exe` with `_internal` and the
bundled `bin/ffmpeg.exe`, `bin/ffprobe.exe` (copied there by `build.ps1`), the YOLO
weights `models/best.pt` and the `configs/` of the pipeline. Torch, ultralytics, cv2 and
scenedetect are collected whole: the tracking loop imports them at runtime, and a missing
submodule is a window that says "no module named ...".
"""

import os

from PyInstaller.utils.hooks import collect_all

app_dir = os.path.abspath(SPECPATH)
src_dir = os.path.join(app_dir, "src")

datas: list = []
binaries: list = []
hiddenimports: list = []

# The pipeline imports these at runtime; the data files of ultralytics (its default
# `coco128.yaml`, the fonts of the plots) and of scenedetect must travel with the build.
# torchvision is collected for its extension: the hook of PyInstaller declares the hidden
# import `torchvision._C`, and in torchvision 0.29 the extension is `torchvision._C_stable`,
# so a build without this line carries the .py files of torchvision and none of its
# `.pyd`/`.dll`, and `import torchvision` dies with
# `RuntimeError: operator torchvision::nms does not exist`.
for pkg in ("ultralytics", "torchvision", "scenedetect", "cv2", "numpy", "yaml", "httpx"):
    extra_data, extra_binaries, extra_imports = collect_all(pkg)
    datas += extra_data
    binaries += extra_binaries
    hiddenimports += extra_imports

# The config files and the model of the app: the pipeline resolves them through the
# resource dir (`sys._MEIPASS`), so they are shipped inside `_internal`.
datas.append((os.path.join(app_dir, "configs"), "configs"))
datas.append((os.path.join(app_dir, "models"), "models"))
icon_path = os.path.join(app_dir, "assets", "icon.ico")
icon = icon_path if os.path.exists(icon_path) else None
if icon is not None:
    datas.append((icon_path, "assets"))
# build.ps1 fills the placeholders of version_info.template.txt into this file.
version_file = os.path.join(app_dir, "build", "version_info.txt")

a = Analysis(
    [os.path.join(src_dir, "yofunscripter", "__main__.py")],
    pathex=[src_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the program does not use; keeping them would bloat the build.
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
             "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="yoFunscripter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_injection=True,
    icon=icon,
    version=version_file if os.path.exists(version_file) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="yoFunscripter",
)
