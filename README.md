# yoFunscripter

Windows desktop app for three jobs on a folder of videos:

1. **Cut scenes** — split videos into scene clips. Every clip is written in one format
   (fps, size, audio), so the clips can be merged without re-encoding.
2. **Generate funscripts** — the movement track of every clip is computed, one `.funscript`
   file per clip, named like the clip.
3. **Merge** — pick clips by waves, join them in place (no re-encoding, no copies) into one
   video and one `.funscript`.

Every setting of the window has a tooltip that says what it does in plain words. Each
card is one line of text — the name of the stage and one short line of what it does — and
in the top right corner of that line the two buttons of the stage: the play arrow runs it,
the square stops it, the two glyphs of any video player. The full explanation of a stage
is in the tooltip of the card. The window opens on the full screen with the log closed, and
the window is rubber in height: the room the user gives it becomes the space between the
cards, and an open log takes a bigger part of that room than a gap. Closing the log gives
the room back to the gaps, so the size of the window never jumps and the text of a row is
never squeezed under the height it needs. **Open console** ⇄ **Close console** is one
button of the row, **Clear** is on the row only while the log is on screen, and the row
carries no word **Console**. **Help** opens the issues page of this repository, and
**Check for updates** stands on the row of the settings buttons.

## Requirements

- Windows 10/11 x64. FFmpeg and FFprobe are bundled.
- A YOLO model `best.pt` is bundled; another model can be picked in the settings.

## Install

Download `YoFunscripter-Setup-<version>.exe` from
[Releases](https://github.com/flynet/yoFunscripter/releases) and run it. The defaults of
every stage are subfolders of the install folder:

```
scenes\   cut clips of stage 1
scripts\  .funscript files of stage 2
result\   merged video + merged .funscript
work\     intermediates; safe to delete
```

**Check for updates** reads the latest GitHub release, downloads its installer, checks
SHA-256 and runs it silently.

## Use

**Settings** — language (English default, Russian), colour scheme (neon default), jobs,
threads, device (`auto` / `cpu` / `cuda`), model file. They are applied by **Save**
(written to `%APPDATA%\YoFunscripter\settings.json`); **Revert** takes the saved values
back, **Restart** restarts the app so the language and the scheme are applied.

**Cut scenes** — source folder (pick it), output folder (default `scenes`), file pattern,
jobs, Start.

**Generate funscripts** — clips folder (default `scenes`), `.funscript` folder (default
`scripts`). A `.funscript` newer than its clip is reused; a clip that was cut again needs
the track recomputed.

**Merge** — clips folder, `.funscript` folder, output folder (default `result`), result
name. Order: ticks per second (default), waves ascending/descending, file names, random.
Minimum waves (default 3, `0` = no filter). A `.funscript` older than its clip is not
used: the merge says how many files are missing and how many are old, and stage 2 fixes
them. Clips must be cut in one format: a clip that does not match is an error, fixed by
cutting the scenes again.

Every run has a play arrow (start) and a square (stop) in the top right corner of its
card: the square stops the run at once (the ffmpeg child is killed, the bar stops, the
window is unlocked). The bar counts real units (seconds of source video, frames, seconds
of the merged movie). The name of each button is in its tooltip.

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
.venv\Scripts\python.exe tools\smoke_window.py
.venv\Scripts\python.exe tools\make_icon.py
```

`smoke_window.py` renders the window offscreen and checks the defaults, the tooltips of
every control, the minimum sizes of the rows, the stage buttons in the top right of a
card, the log closed at start (no word «Console» on its row), the rubber of the window (a
screen-sized window spreads the space between the cards, an open log takes more of it than
a gap, closing the log keeps the size of the window, the cards keep the height of their
text), the startup that shows the window maximized, the settings row (Revert, Restart,
Check for updates, Help, Save), the one-line hints, that no button clips its text, the
order combo and its per-order tooltip, and that no console text uses the words of the code.

## Release

```powershell
git tag v1.0.4; git push origin v1.0.4
powershell -ExecutionPolicy Bypass -File tools\publish_release.ps1   # the release on GitHub
powershell -ExecutionPolicy Bypass -File build.ps1 -Cuda            # the CUDA installer
powershell -ExecutionPolicy Bypass -File tools\publish_upload.ps1    # attach it to the release
```

`publish_release.ps1` creates the release from `build\release-notes-<version>.md` and
writes the release id to `build\release_id.txt`; the CI workflow builds the CPU installer.
`publish_upload.ps1` attaches the installer of the local CUDA build and removes the CPU
asset of the CI, so the release keeps one setup file. Both read the token from the git
credential manager.

## Tests

```powershell
uv run pytest
```

The tests cover the Qt-free parts: updater, settings, i18n catalogs (both languages,
placeholders, no code words), the `.funscript` pairing rule (paired by name, fresh or
rejected), progress meter, cut graph, merge selection and clip checks, cancel. The
pipelines need real video and a model, so they are tested by running the app.

## License

MIT, see `NOTICE`. FFmpeg is the GPL build of the FFmpeg project, Ultralytics is AGPL-3.0.
