# TODO

State of the project, in the order of what is left.

## Verified (measured, not assumed)

- **Stage 1 (cut scenes)** end to end. Synthetic 3-scene source: clips of 125 frames each
  (forced re-cut: 3 clips, progress 15 s = 15 s, no progress files left in the output
  folder). Real 1080p source `11 (2).mp4`: scenes of 78 / 1706 / 533 frames came out
  exactly as the scene list, `time_base 1/30000`, moov before mdat, min dts 0, checks clean.
- **Stage 2 (funscripts)** end to end on 3 real clips: ticks 297 / 102 / 75, the progress
  meter finished at 2699 frames = the sum of the frames of the clips.
- **Stage 3 (merge)** end to end: 1 real clip (18 s) -> `result.mp4` + `result.funscript`
  with 32 checks `PASS`, 0 fails (payload rules, target format, `time_base 1/30000`,
  monotonic PTS, last tick 18421 = video duration, ticks 75 = 75 - 0 + 0), progress
  18 s = 18 s of source video. The freshness rule was seen working: a clip copied with a
  newer mtime was rejected because its sidecar was older. Re-running with the segment
  cache reuses the encoded segment (encode skipped, concat + checks re-run).
- 40 unit tests pass: settings (atomic save, backup, clamping), the updater (release
  parsing, version compare, SHA-256, resume of a partial download), the language
  catalogues (same keys, same placeholders), the progress meter, the merge selection
  (filters, five order modes, reproducible random), the packaged layout.
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
  right expectation. The repository is **private**, so:
  - `releases/latest` answers 404 without a token (measured) and 200 with the token;
  - `browser_download_url` answers 404 for a private release (it needs a browser session),
    and the API address of the asset `https://api.github.com/.../releases/assets/<id>` with
    `Accept: application/octet-stream` gives the file (measured);
  - the app sends the token from `YOFUNSCRIPTER_GITHUB_TOKEN`, and reads the release, the
    digest and the installer with it. With the token the whole chain is measured against
    the real private release: `fetch_release` → `1.0.1`, `is_newer("1.0.0", "1.0.1")` → True,
    the installer downloaded byte for byte (239407095 bytes, 229 chunk reports), the SHA-256
    of the release asset matched the file, the command is
    `setup.exe /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /NORESTART` with
    `DETACHED_PROCESS` (the installer was not launched, `Popen` was stubbed).
  - Without a token the button reports that there is nothing to show, which is the truth
    for a private repository. The owner keeps the repository private; the token of a
    read-only fine-grained PAT is given to the machines that should receive updates, and
    `YOFUNSCRIPTER_UPDATE_API` aims the check at a local fixture (`tools/update_fixture.py`)
    to test the chain without any token.
  The CI workflows (`.github/workflows/ci.yml`, `release.yml`) have
  not run on GitHub.
- **The CUDA build.** `build.ps1 -Cuda` was run once and produced a CPU build: `uv run
  pyinstaller` syncs the project, so it put the CPU wheels back over the cu126 wheels that
  the CUDA step had installed (the build carried `torch-2.15.0+cpu.dist-info`). `build.ps1`
  now uses `uv run --no-sync` and stops the build when the venv does not have the cu126
  wheels. The GPU build with the cu126 wheels has to be built and measured on the machine
  with the GPU (`RTX 4060 Laptop, driver 621.24, 8 GB`). `cuda` in the settings cannot work
  in a CPU build: ultralytics raised the big `Invalid CUDA 'device=0'` error on every clip
  of the user's 21-clip run, so the device is resolved once at the start of stage 2
  (`_device`) and the stage falls back to the CPU with one line in the log.
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
