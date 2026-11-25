# yoFunscripter

Windows desktop app for three jobs on a folder of videos:

1. **Cut scenes** — split videos into scene clips with PySceneDetect + FFmpeg.
2. **Generate funscripts** — YOLO tracking on the clips, one `.funscript` sidecar per clip.
3. **Merge** — pick clips by wave count, encode them to one format, concatenate into one
   video and one funscript.

## Requirements

- Windows 10/11 x64. FFmpeg and FFprobe are bundled.
- A YOLO model `best.pt` is bundled; another model can be picked in the settings.

## Install

Download `YoFunscripter-Setup-<version>.exe` from
[Releases](https://github.com/flynet/yoFunscripter/releases) and run it. The defaults of
every stage are subfolders of the install folder:

```
scenes\   cut clips of stage 1
scripts\  .funscript sidecars of stage 2
result\   merged video + merged funscript
work\     intermediates; safe to delete
```

**Check for updates** reads the latest GitHub release, downloads its installer, checks
SHA-256 and runs it silently.

## Use

**Settings** — language (EN/RU), colour scheme, threads, device (`auto` / `cpu` / `cuda`),
model file, and Save / Revert / Restart. Settings are written to
`%APPDATA%\YoFunscripter\settings.json` on Save.

**Cut scenes** — source folder (required), output folder (default `scenes`), file pattern,
parallel jobs, Start.

**Generate funscripts** — clips folder (default `scenes`), scripts folder (default
`scripts`). A sidecar newer than its clip is reused.

**Merge** — clips folder, scripts folder, output folder (default `result`), result name.
Order: tick rate (default), waves ascending/descending, folder order, random.
`min_waves` (default 3, `0` = no filter).

`cuda` works in the CUDA build (`build.ps1 -Cuda`); in the CPU build stage 2 runs on the
CPU.

## Build from source

```powershell
uv sync
powershell -ExecutionPolicy Bypass -File build.ps1        # CPU wheels
powershell -ExecutionPolicy Bypass -File build.ps1 -Cuda  # GPU build
```

`build.ps1` writes the version from `git describe --tags`, bundles `bin\ffmpeg.exe` and
`bin\ffprobe.exe`, runs PyInstaller (onedir) and builds
`dist\install\YoFunscripter-Setup-<version>.exe` with its `.sha256` file when Inno Setup 6
is installed.

Run without packaging: `run.bat`

Selftest of the frozen build (imports the stages load at runtime, prints `OK`):

```powershell
uv run --no-sync pyinstaller --clean --noconfirm tools\selftest.spec
dist\selftest\selftest.exe
```

`--no-sync` keeps the wheels of the venv: a plain `uv run` syncs the project and puts the
CPU torch wheels back over the cu126 ones.

```powershell
.venv\Scripts\python.exe tools\make_screenshots.py
.venv\Scripts\python.exe tools\make_icon.py
```

## Tests

```powershell
uv run pytest
```

The tests cover the Qt-free parts: updater, settings, i18n catalogs, progress meter, merge
selection. The pipelines need real video and a model, so they are tested by running the app.

## License

MIT, see `NOTICE`. FFmpeg is the GPL build of the FFmpeg project, Ultralytics is AGPL-3.0.
