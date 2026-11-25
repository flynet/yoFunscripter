"""Build a fake release so the updater can be tried on this machine.

The app reads `releases/latest` of the repository; a private repository answers 404 to the
app (the app has no token), so the whole chain — read the release, download the installer,
check SHA-256, start the installer — is aimed at a local server with
`YOFUNSCRIPTER_UPDATE_API`:

    python tools/update_fixture.py                        # fixture in the temp dir
    python -m http.server 8765 --directory <fixture dir>  # serve it
    set YOFUNSCRIPTER_UPDATE_API=http://127.0.0.1:8765/release.json
    <run the app>

`--installer <file>` puts a real setup file in the fixture with its `.sha256` next to it,
so the «Install» button installs the real build. Without the flag the fixture carries a
filler file of `--mb` megabytes: the download and the digest are tried without copying
228 MB. The local server answers the whole body, so the resume of a broken download
(the `Range` request) is covered by the unit test, not by this fixture.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yofunscripter.update.checker import API_URL_ENV, sha256_of

PORT = 8765


def make_fixture(version: str, installer: Path | None, mb: int, out: Path) -> Path:
    """The fixture folder: `release.json`, the installer and its digest."""
    out.mkdir(parents=True, exist_ok=True)
    name = f"YoFunscripter-Setup-{version}.exe"
    target = out / name
    if installer is not None:
        shutil.copyfile(installer, target)
    else:
        block = bytes(range(256)) * 4096
        with target.open("wb") as handle:
            for _ in range(mb):
                handle.write(block)
    digest = sha256_of(target)
    sha_file = out / (name + ".sha256")
    sha_file.write_text(f"{digest}  {name}\n", encoding="ascii")
    base = f"http://127.0.0.1:{PORT}/"
    payload = {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "published_at": date.today().isoformat() + "T12:00:00Z",
        "body": f"Fixture release {version} for testing the updater.",
        "assets": [
            {"name": name, "browser_download_url": base + name, "size": target.stat().st_size},
            {"name": name + ".sha256", "browser_download_url": base + name + ".sha256",
             "size": sha_file.stat().st_size},
        ],
    }
    (out / "release.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="1.0.1")
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--mb", type=int, default=5)
    parser.add_argument("--out", type=Path,
                        default=Path(tempfile.gettempdir()) / "yofunscripter-fixture")
    args = parser.parse_args()
    out = make_fixture(args.version, args.installer, args.mb, args.out)
    print(f"fixture: {out}")
    print(f"installer: {(out / f'YoFunscripter-Setup-{args.version}.exe').stat().st_size} bytes")
    print("serve it:")
    print(f"  python -m http.server {PORT} --directory {out}")
    print("and aim the app at it:")
    print(f"  set {API_URL_ENV}=http://127.0.0.1:{PORT}/release.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
