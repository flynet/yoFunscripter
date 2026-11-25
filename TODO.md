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
- **The packaged build**: `build.ps1` ran on this machine. PyInstaller onedir produced
  `dist\yoFunscripter\` (908 MB unpacked) with `_internal` (torch 2.15.0+cpu 373 MB with
  `torch_cpu.dll`, torchvision, ultralytics 8.4.218 with `engine/nn/trackers/cfg/data`,
  cv2, scenedetect 0.7.3, PySide6), `bin\ffmpeg.exe` + `bin\ffprobe.exe` (copied from
  `D:\ffmpeg\bin`), `models\best.pt`, `configs\`, `assets\icon.ico`; the .exe file
  properties read `ProductVersion 1.0.0`, `CompanyName flynet`; Inno Setup produced
  `dist\install\YoFunscripter-Setup-1.0.0.exe` (228 MB) with its `.sha256`, in the exact
  case of the updater contract.
- The packaged window starts: `dist\yoFunscripter\yoFunscripter.exe` runs 40 s in the
  offscreen platform, 92 MB of memory, `settings.json` is written to
  `%APPDATA%\YoFunscripter` — Qt, cv2, scenedetect and the settings path load in the
  frozen build.

- **The imports of the frozen build.** `tools/selftest.py` + `tools/selftest.spec` build
  the same packages as `yofunscripter.spec` without Qt and run in the frozen build:
  `torch 2.15.0+cpu` (cuda False), `cv2 5.1.0`, `scenedetect 0.7.3`,
  `ultralytics 8.4.218`, `models/best.pt` loads with 5 classes, `OK`, exit 0. So the
  lazy imports of stage 2 (`import torch`, `from ultralytics import YOLO`) are complete
  in the packaged build.

## Left

- **One run inside the packaged app.** The stage code inside the frozen build has not
  been driven: the selftest proves the imports and the model, the ffmpeg calls and the
  worker threads are the same code the source runs, and the source is measured
  end to end. The install of `YoFunscripter-Setup-1.0.0.exe` on a clean machine has not
  been done.
- **The updater against the repository.** `github.com/flynet/yoFunscripter` returns 404,
  so `fetch_release`, the download and the silent install are tested only by unit tests.
  The repository must be created and `v1.0.0` released before the button does anything.
  The CI workflows (`.github/workflows/ci.yml`, `release.yml`) are written against the
  same repository and have not run on GitHub.
- **The CUDA build.** `build.ps1 -Cuda` has not been run; the device selector
  `auto`/`cuda` is untested on the machine with the GPU.
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
- Vendored modules keep their Russian comments; the app-facing text and the
  documentation are English.
- The name `YoFunscripter-Setup-<version>.exe` is the contract with the updater
  (`SETUP_PREFIX`): the Inno script writes it in that exact case, `build.ps1` checks the
  file name and writes the `.sha256` with the leaf name.
