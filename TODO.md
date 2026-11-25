# TODO

State of the project, in the order of what is left.

## Verified (measured, not assumed)

- Stage 1 (cut scenes) end to end. Synthetic 3-scene source: clips of 125 frames each.
  Real 1080p source `11 (2).mp4`: scenes of 78 / 1706 / 533 frames came out exactly as
  the scene list, `time_base 1/30000`, moov before mdat, min dts 0, all clip checks clean.
- Stage 2 (funscripts) end to end on 3 real clips: ticks 297 / 102 / 75, the progress
  meter finished at 2699 frames = the sum of the frames of the clips.
- 40 unit tests pass: settings (atomic save, backup, clamping), the updater (release
  parsing, version compare, SHA-256, resume of a partial download), the language
  catalogues (same keys, same placeholders), the progress meter, the merge selection
  (filters, five order modes, reproducible random), the packaged layout.
- The window: title, Main/Settings tabs, three stage cards, progress panel, merge
  options, settings sync writes `settings.json`.

## Left

- **Stage 3 end to end.** The merge has not been run through the app: encode the
  segments, concatenate the video, merge the funscripts, then the checks of the final
  file (`check_final`, `merged_gap_check`, last tick = duration). The code runs, one
  missing import was found and fixed, the rest is unmeasured.
- **The packaged build.** `build.ps1` has not been run: PyInstaller has not packed
  ultralytics/torch/cv2/PySide6, `bin\ffmpeg.exe` + `bin\ffprobe.exe` have not been
  copied, the Inno Setup installer has not been produced, and the packaged app has not
  been started. Torch is collected whole, so a missing hidden import shows as a window
  that says "no module named ..."; the build must be run once on a real machine.
- **The updater against the repository.** `github.com/flynet/yoFunscripter` returns 404,
  so `fetch_release`, the download and the silent install have been tested only by unit
  tests. The repository must be created and `v1.0.0` released before the button does
  anything.
- **The CUDA build.** `build.ps1 -Cuda` has not been run; the device selector
  `auto`/`cuda` is untested on the machine with the GPU.
- **Look of the window.** The three color schemes and both languages have not been
  screenshot-checked in the running window; the icon has not been seen in the taskbar.
- README screenshots of the three cards.

## Small things to keep in mind

- `run.bat` uses `uv` and `pythonw`; a checkout without uv must print one readable
  error, which is the current behavior.
- The pipeline keeps the intermediate artifacts in `work/` next to the program: the
  uninstaller deletes `work/`, the user folders (`scenes`, `scripts`, `result`) are
  left alone.
- Vendored modules keep their Russian comments; the app-facing text and the
  documentation are English.
