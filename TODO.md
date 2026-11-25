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
- The window: title, Main/Settings tabs, three stage cards, progress panel, merge
  options, settings sync writes `settings.json`.

## Left

- **The packaged build.** `build.ps1` has not been run: PyInstaller has not packed
  ultralytics/torch/cv2/PySide6, `bin\ffmpeg.exe` + `bin\ffprobe.exe` have not been
  copied, the Inno Setup installer has not been produced, and the packaged app has not
  been started. Torch is collected whole, so a missing hidden import shows as a window
  that says "no module named ..."; the build must be run once on a real machine.
- **The updater against the repository.** `github.com/flynet/yoFunscripter` returns 404,
  so `fetch_release`, the download and the silent install are tested only by unit tests.
  The repository must be created and `v1.0.0` released before the button does anything.
  The CI workflows (`.github/workflows/ci.yml`, `release.yml`) are written against the
  same repository and have not run on GitHub.
- **The CUDA build.** `build.ps1 -Cuda` has not been run; the device selector
  `auto`/`cuda` is untested on the machine with the GPU.
- **Look of the window.** The three color schemes and both languages have not been
  screenshot-checked in the running window; the icon has not been seen in the taskbar.
- README screenshots of the three cards.

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
