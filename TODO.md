# TODO

State of the project, in the order of what is left.

## Verified (measured, not assumed)

- **Stage 1 (cut scenes)** end to end. Synthetic 3-scene source: clips of 125 frames each
  (forced re-cut: 3 clips, progress 15 s = 15 s, no progress files left in the output
  folder). Real 1080p source `11 (2).mp4`: scenes of 78 / 1706 / 533 frames came out
  exactly as the scene list, `time_base 1/30000`, moov before mdat, min dts 0, checks clean.
  The cut is one ffmpeg process per video with `filter_complex_script`: `split=N`, trim by
  frame numbers, `fps=target_fps`, `scale/pad/setsar` to the target size, AAC audio — the
  clip is normalized once, here (unit-tested; the normalized clips of a real cut have not
  been measured in this app yet). The graph and the progress file live in `work/`, the
  output folder keeps only clips.
- **Stage 2 (funscripts)** end to end on 3 real clips: ticks 297 / 102 / 75, the progress
  meter finished at 2699 frames = the sum of the frames of the clips.
- **Stage 3 (merge)** end to end: 1 real clip (18 s) -> `result.mp4` + `result.funscript`
  with 32 checks `PASS`, 0 fails (payload rules, target format, `time_base 1/30000`,
  monotonic PTS, last tick 18421 = video duration, ticks 75 = 75 - 0 + 0), progress
  18 s = 18 s of source video. The freshness rule was seen working: a clip copied with a
  newer mtime was rejected because its sidecar was older. The merge is now `-c copy` on the
  clips **in place** (the normalization moved to the cut, so the merge encodes and copies
  nothing): the path is unit-tested, and it has not been run against real clips in this app
  — the design and the numbers are measured in `D:\Java\yolo` (concat copy of normalized
  clips, dts of the final = 0, container tail = AAC priming only).
- **Cancel** in the window (offscreen, Qt only, no CPU work): each card has the square
  (`QPushButton#mediaDanger`) in the top right corner of its title line, it is enabled
  only while a run is going, `_cancel()` with no worker does nothing, and `_cancelled`
  writes `⛔ Merge: stopped by the user` to the console and the status line and unlocks
  the buttons. Cancel kills the registered ffmpeg children and stops the stage at the
  loop boundaries (video, clip, progress hook); the detect pass of stage 1 decodes
  in-process (PySceneDetect), so it is not interruptible — the stage stops right after it.
- 81 unit tests pass (0.7 s, no ffmpeg, no torch): settings (atomic save, backup,
  clamping, the default theme `neon`), the updater (release parsing, version compare,
  SHA-256, resume of a partial download, `Cancelled` out of the download loop with the
  bytes on disk kept), the language catalogues (same keys, same placeholders, no code words
  in the interface texts, every `tr("key")` of the source present in both languages), the
  `.funscript` pairing rule (paired by name, missing counted, an older file rejected and
  named with the stage that fixes it), the progress meter,
  the cut graph (one split, frame trim, normalization to the target, NVENC session limit,
  one thread per x264 encoder), the merge selection (filters, five order modes,
  reproducible random), the clip rules the merge refuses (`check_concat_inputs`), the
  concat list written in the work dir with the clips read in place, the cancel token
  (kill of live children, `Cancelled` out of the ffmpeg runner), the packaged layout.
- **The window, checked offscreen** (`tools/smoke_window.py`): the default theme is neon
  (window palette read `#0e0e1a`), the default language is English, every control has a
  tooltip (68 in the window), the folder fields keep `minWidth 220` and the labels the
  floor of their text, the minimum window is `875x548` with the log closed, the log is the
  rubber of the window: closed at start (one row of buttons, the window sized to its
  content, `maximumHeight` 548 so it cannot be dragged into empty space), open it asks for
  743 px and takes every extra pixel of a taller window (the log read 351 px in a 900 px
  window), «Open console» ⇄ «Close console» shows and hides it with «Clear» appearing only
  while the log is on screen, the play arrow and the square of a stage sit in the top right
  corner of the title line of a card, the title and the hint of a card share one line,
  every hint is one line of text, «Check for updates» and «Help» stand on the row of the
  settings buttons (`Help` opens `github.com/flynet/yoFunscripter/issues`), no button
  clips its text (29 buttons measured), the order combo shows the meaning of the order
  that is chosen, and no text of the catalogues says `sidecar`, `tick_rate`, `ffmpeg`,
  `torch`. The console lines of all three stages are in the language of the window.
- **The window** in the real (windows) platform: title `yoFunscripter 1.0.0`, Main/Settings
  tabs, three stage cards with the folder rows, the progress panel with the gradient bar
  and the `60% · 7200 s of 12000 s · ETA · elapsed` line, the console, the merge options,
  the settings page. Cyrillic and Latin both render; the screenshots in `assets/screenshots`
  are the real window (`tools/make_screenshots.py`).
- **The settings page applies the form by the «Save» button** (the pattern of PyDownload):
  measured offscreen with `C:\Users\Home\AppData\Local\Temp\opencode\probe_save.py` (Qt only,
  no CPU work): changing the widgets writes nothing; `Save` writes
  `settings.json` at once, applies the colour scheme immediately (window palette read
  `#fff6e0` for cartoons), prints «Settings are saved: a restart applies the language and
  the theme» when the language differs; `Revert` returns the widgets to the saved values;
  `Reset model` + `Save` writes the empty model path; `Restart` is enabled only when the
  chosen language is not the running one, and `restart_command()` is
  `python -m yofunscripter` in the source tree, the `.exe` in the frozen build.

- **The packaged build**: `build.ps1` ran on this machine. PyInstaller onedir produced
  `dist\yoFunscripter\` (908 MB unpacked) with `_internal` (torch 2.15.0+cpu 373 MB with
  `torch_cpu.dll`, torchvision, ultralytics 8.4.218 with `engine/nn/trackers/cfg/data`,
  cv2, scenedetect 0.7.3, PySide6), `bin\ffmpeg.exe` + `bin\ffprobe.exe` (copied from
  `D:\ffmpeg\bin`), `models\best.pt`, `configs\`, `assets\icon.ico`; the .exe file
  properties read `ProductVersion 1.0.0`, `CompanyName flynet`; Inno Setup produced
  `dist\install\YoFunscripter-Setup-1.0.0.exe` (228 MB) with its `.sha256`, in the exact
  case of the updater contract.
- The packaged window starts and shows the settings row: `dist\yoFunscripter\yoFunscripter.exe`
  runs 40 s in the offscreen platform, 92 MB of memory, `settings.json` is written to
  `%APPDATA%\YoFunscripter`; on the real (windows) platform the window opens and the Settings
  tab shows the row «Сбросить / Перезапустить / Сохранить» (the captured window is
  `C:\Users\Home\AppData\Local\Temp\opencode\packaged-settings.png`), with the model
  placeholder pointing at `_internal\models\best.pt` of the bundle. The compiled modules of
  the PYZ inside the `.exe` contain `settings_save`, `settings_revert`,
  `settings_restart`, `save_requested`, `restart_requested`, `_apply_settings`,
  `_restart_app`, `restart_command`, `startDetached`, `Сохранить`, `Сбросить`,
  `Перезапустить`, so the frozen build is the code of the source tree.

- **The imports of the frozen build.** `tools/selftest.py` + `tools/selftest.spec` build
  the same packages as `yofunscripter.spec` without Qt and run in the frozen build:
  `torch 2.15.0+cpu` (cuda False), `cv2 5.1.0`, `scenedetect 0.7.3`,
  `ultralytics 8.4.218`, `models/best.pt` loads with 5 classes, `OK`, exit 0. So the
  lazy imports of stage 2 (`import torch`, `from ultralytics import YOLO`) are complete
  in the packaged build.

## Left

- **The new cut and merge on real video.** Stage 1 writes normalized clips (target fps,
  size, timescale, AAC), stage 3 concatenates them in place with `-c copy`. The numbers are
  measured in `D:\Java\yolo`; in this app the run must be seen on real sources: a cut with
  `cuda` (NVENC) and a cut with `cpu` (libx264), a merge of several clips (checks PASS, the
  duration of the final = the sum of the clips, the last tick = the duration), and «Cancel»
  pressed in the middle of a cut, of a tracking run and of a concat.

- **One run inside the packaged app.** `dist\` and `dist\install\YoFunscripter-Setup-1.0.0.exe`
  are rebuilt after the «Save» row (228.4 MB, SHA-256
  `7cc86494389a1f21e8ba3e08a0f1c2a1d6af3da03991f06964516813858d733c`). The stage code inside
  the frozen build has not been driven: the selftest proves the imports and the model, the
  ffmpeg calls and the worker threads are the same code the source runs, and the source is
  measured end to end. The install of `YoFunscripter-Setup-1.0.0.exe` on a clean machine has
  not been done.
- **The updater against the repository.** The releases `v1.0.0` and `v1.0.1` exist
  (`https://github.com/flynet/yoFunscripter/releases`) with the assets
  `YoFunscripter-Setup-<version>.exe` and `YoFunscripter-Setup-<version>.exe.sha256`; the
  digest `build.ps1` writes equals GitHub's own digest of the asset, so `verify()` has the
  right expectation. The repository is **public** (the owner flipped it with the API:
  `visibility=public`, measured `private=True` before and `private=False` after), so the app
  needs no token:
  - `releases/latest` answers 200 without a token (measured);
  - `browser_download_url` gives the file without a token. The whole chain against the real
    public release 1.0.1 is measured unauthenticated: `fetch_release` → `1.0.1`,
    `is_newer("1.0.0", "1.0.1")` → True, the installer downloaded byte for byte (239407095
    bytes, 229 chunk reports), the SHA-256 of the release asset matched the file, the command
    is `setup.exe /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /NORESTART` with
    `DETACHED_PROCESS` (the installer was not launched, `Popen` was stubbed);
  - the code that reads a private repository is kept: the token of
    `YOFUNSCRIPTER_GITHUB_TOKEN` (a read-only fine-grained PAT) is sent when the environment
    has one, and the release, the digest and the installer are read through the API address
    of each asset with it (measured against the private release 1.0.1: `browser_download_url`
    answered 404, the API asset address with `Accept: application/octet-stream` gave the
    file);
  - `YOFUNSCRIPTER_UPDATE_API` aims the check at a local fixture
    (`tools/update_fixture.py`) to test the chain end to end without any network. The flow
    inside the window is measured with the fixture as 1.0.3 against the app of 1.0.2: the
    status line becomes `A new release 1.0.3 is available (2026-11-25)`, the window opens
    the dialog itself, the real download thread writes 3145728 bytes with the bar at 100,
    the SHA-256 of the downloaded file equals the published one, and the file lands in the
    app data (`<app data>/yoFunscripter/updates/`), not in a user folder. The installer of
    the fixture is never launched: the fixture file is not an installer.
  - **The dialog has two buttons, «Обновить» and «Закрыть»** (measured offscreen with
    `smoke_update103.py` and a stubbed download): «Обновить» starts the download and, when
    the file lands and the digest matches, starts the installer and the program leaves.
    While the file comes, the same button reads «Отмена» (the red `QPushButton#danger`
    style of the stage cards), «Закрыть» is disabled, the bar and the `N / M MB` line follow
    the real bytes; pressing it stops the download at the next megabyte, the bytes already
    on disk stay, and the next «Обновить» continues from that byte. «Закрыть» during the
    download stops it and the window leaves when the thread ends. The texts in English read
    `Update` and `Close`. Pressing the button of a window that is not running starts the
    download again.
  The CI workflows (`.github/workflows/ci.yml`, `release.yml`) have
  not run on GitHub.
- **The CUDA build and release 1.0.2.** `https://github.com/flynet/yoFunscripter/releases/tag/v1.0.2`
  (release id `457813468`) carries `YoFunscripter-Setup-1.0.2.exe` (asset id `790659388`,
  1793830265 bytes, SHA-256
  `72b2209121a35d5e689981f0830c20a5e587d36ecd5ffc6949c5876abf5d650b`) and its `.sha256`
  (asset id `790669130`, 96 bytes); the tag is moved to the commit the build was made from
  (`886e162`). The published chain without a token is measured: `api_url` →
  `releases/latest` of the repository, the release reads `1.0.2`, `is_setup` True, the
  download URL is `browser_download_url`, `is_newer("1.0.1", "1.0.2")` True and
  `is_newer("1.0.2", "1.0.2")` False, the SHA-256 of the release asset equals the digest of
  the file in `dist\install` and `verify()` is True, the sizes are equal byte for byte, the
  chunked reader is exercised on the 96-byte asset, the command is
  `setup.exe /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /NORESTART` with `creationflags`
  `0x8` = `DETACHED_PROCESS`, and `Popen` is stubbed so the installer is never launched. The
  installer 1.0.2 has not been installed and run on a machine (the install and the device
  `cuda` in the settings are for the user).
- **The CUDA build.** `build.ps1 -Cuda` was run once and produced a CPU build: `uv pip
  install` without `--reinstall` printed `Audited 2 packages` and changed nothing (the CPU
  wheels already satisfy the requirement), and `uv run pyinstaller` syncs the project, so it
  put the CPU wheels back over the cu126 wheels (the build carried
  `torch-2.15.0+cpu.dist-info`). `build.ps1` now uses `uv pip install --reinstall` and
  `uv run --no-sync`, and stops the build when the venv does not have the cu126 wheels (the
  control caught the first attempt). A probe process of the venv that is still running locks
  `numpy.libs` and the install fails halfway with `os error 5`, so no venv process is left
  open before the CUDA install. After the fix the venv reports `torch 2.14.1+cu126`,
  `torch.version.cuda 12.6`, `cuda.is_available()` True, device `NVIDIA GeForce RTX 4060
  Laptop GPU`, `torchvision 0.29.1+cu126`, and `uv run --no-sync python` reports the same
  `2.14.1+cu126`. `_device` with the real torch is measured: `auto` and `""` → `None`,
  `cpu` → `'cpu'`, `cuda` → `0` (the GPU) with no log line. What is not measured: the CUDA
  libraries that the packaged build carries, the size of the CUDA installer (the limit of a
  GitHub release asset is 2 GiB), and one frame of GPU inference in the frozen build.
  `cuda` in the settings cannot work in a CPU build: ultralytics raised the big `Invalid
  CUDA 'device=0'` error on every clip of the user's 21-clip run, so the device is resolved
  once at the start of stage 2 (`_device`) and the stage falls back to the CPU with one line
  in the log.
- **torchvision in the frozen build.** The CUDA selftest died with `RuntimeError: operator
  `torchvision::nms does not exist``: the PyInstaller hook `hook-torchvision.py` declares the
  hidden import `torchvision._C`, and in torchvision 0.29 the extension is
  `torchvision._C_stable`, so the build carried the `.py` files of torchvision and no
  `.pyd`/`.dll` at all. `collect_all("torchvision")` gives the 9 binaries (`_C_stable.pyd`
  7023616 bytes, `image_stable.pyd`, `nvjpeg64_12.dll`, `cudart64_12.dll`, `jpeg8.dll`,
  `libpng16.dll`, `libwebp.dll`, `libsharpyuv.dll`, `zlib.dll`) and the hidden import
  `torchvision._C_stable`, so torchvision is in the `collect_all` list of both spec files.
  The CUDA selftest then prints `torch 2.14.1+cu126`, `cuda available True`,
  `cuda runtime 12.6`, `device NVIDIA GeForce RTX 4060 Laptop GPU`,
  `gpu inference ok, detections 0`, `cv2 5.1.0`, `scenedetect 0.7.3`, `numpy 2.5.4`,
  `ultralytics 8.4.218`, `model best.pt 5550533 classes 5`, `OK`. The app does not import
  torchvision: after `torch`, `numpy`, `cv2`, `yaml`, `scenedetect`, `ultralytics` and
  `YOLO(best.pt)` the module table has no torchvision, and `ultralytics` has no
  `torchvision` reference, so the defect only broke the selftest.
  The CUDA installer measured 1791039101 bytes (the limit of a GitHub release asset is
  2147483648 bytes), `_internal` 4624 MB with `torch` 4097 MB, of which the CUDA DLLs are
  2390 MB (largest: `cublasLt64_12.dll` 532 MB,
  `cudnn_engines_precompiled64_9.dll` 514 MB, `cusparse64_12.dll` 288 MB,
  `cudnn_adv64_9.dll` 282 MB, `cufft64_11.dll` 277 MB).
  The second CUDA build died in the PyInstaller analysis with
  `FileNotFoundError: 'C:\Users\Home\miniconda3\Library\bin\libcrypto-3-x64.dll'`: the
  machine has `C:\Users\Home\miniconda3` in PATH with no folder behind it (measured
  `Test-Path` False for the folder and for `Library\bin`), and `libcrypto-3-x64.dll` is a
  dependency of `_ssl.pyd`, so PyInstaller resolved the dependency through PATH and stopped.
  The real file is in the uv python install
  (`...cpython-3.12.11-windows-x86_64-none\DLLs`) and not in the venv. `build.ps1` filters
  PATH to the directories that exist before PyInstaller runs.
- **The icon in the running program.** `assets/icon.ico` is built into the .exe and the
  installer, and the window icon is set from the bundle; it has not been seen in the
  taskbar of a running packaged app.
- The pink scheme has not been seen in the running window (neon and cartoons are in
  `assets/screenshots`).

## Small things to keep in mind

- The console panel shows the pipeline lines as the pipeline writes them. The app's own
  lines (stage status, the summary lines of the stages) are English/Russian by the locale;
  the check lines of the vendored `funscript_check.py` and the concat reports are Russian.
  Localizing them means a text map inside the pipeline modules: do it when the console
  becomes a feature that users read, not before.
- Intermediate files stay in `work/` next to the program: scene lists and stats
  (`work/scenes`), segment cache and concat list (`work/concat`), track CSV and reports
  (`work/funscript`), ffmpeg progress files (`work/progress`, deleted by the runner after
  each process). The user folders (`scenes`, `scripts`, `result`) get only the outputs.
  The uninstaller deletes `work/`, the user folders are left alone.
- `run.bat` uses `uv` and `pythonw`; a checkout without uv prints one readable error.
- **No console window of a child process.** The installed program is a windowed PyInstaller
  build, and Windows gives a new console window to every console child it starts, so each
  ffmpeg cut of stage 1 popped a window on the screen. `pipeline/no_window.py` puts
  `CREATE_NO_WINDOW` on every ffmpeg/ffprobe child (measured with a stub of
  `subprocess.Popen`: 7 calls, flags `0x8000000` on every one). Any new child of the pipeline
  must go through `no_window.run` / `no_window.popen`, not through `subprocess` directly.
- Vendored modules keep their Russian comments; the app-facing text and the
  documentation are English.
- The name `YoFunscripter-Setup-<version>.exe` is the contract with the updater
  (`SETUP_PREFIX`): the Inno script writes it in that exact case, `build.ps1` checks the
  file name and writes the `.sha256` with the leaf name.
