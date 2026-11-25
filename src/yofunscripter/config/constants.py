"""Names of the application, the repository of the releases and the defaults.

The GitHub repository is the source of the releases the updater reads, and the prefix of
the setup file is the contract with the release workflow, so both live here as constants,
not inside the checker. The version is read from `_version.py`, which `build.ps1` writes
from `git describe --tags`.
"""

from __future__ import annotations

from yofunscripter._version import VERSION

APP_NAME = "yoFunscripter"
#: Full display name in the title bar.
APP_TITLE = "yoFunscripter"
APP_SLUG = "yofunscripter"

#: Owner and repository of the releases (github.com/owner/repo).
GITHUB_OWNER = "flynet"
GITHUB_REPO = "yoFunscripter"

#: Prefix of a setup file in the releases: `YoFunscripter-Setup-1.0.0.exe`.
SETUP_PREFIX = "YoFunscripter-Setup-"

#: The page of the repository where the user asks a question and reads the answers:
#: the «Help» button of the settings opens it in the browser.
HELP_URL = "https://github.com/flynet/yoFunscripter/issues"

#: Fallback folder names relative to the install dir when the settings have none.
DEFAULT_SCENES_DIR = "scenes"
DEFAULT_SCRIPTS_DIR = "scripts"
DEFAULT_RESULT_DIR = "result"
#: Intermediates of the app (scene lists, segment cache, artifacts): never a user folder.
DEFAULT_WORK_DIR = "work"

#: ffmpeg/ffprobe shipped into the build (bundled, not asked from the machine).
BUNDLED_DIR = "bin"

#: Stage 2/3 pattern of clips.
DEFAULT_CLIP_PATTERN = "*.mp4"
