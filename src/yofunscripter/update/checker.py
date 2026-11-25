"""Update check through GitHub Releases of `flynet/yoFunscripter`.

The core is Qt-free: the network code returns the release data, the dialog decides what
to show. The button in the status bar asks once per click (no cache), a network failure
is one console line, not a hang: the window keeps running.

The setup file is named `YoFunscripter-Setup-<version>.exe` — the contract with the
release workflow. The download is resumed from the byte the file reached, because GitHub
answers a big installer over a slow link in pieces, and a restart from zero never finishes.

The repository is private, so `releases/latest` answers 404 to a request without a token:
the app sends the token of `YOFUNSCRIPTER_GITHUB_TOKEN` when the environment has one, and
reads the release, the digest and the installer with it. Without a token the check reports
that there is nothing to show, which is the truth for a private repository.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from yofunscripter.config.constants import (GITHUB_OWNER, GITHUB_REPO, SETUP_PREFIX)
from yofunscripter.i18n import tr

#: `https://api.github.com/repos/<owner>/<repo>/releases/latest`
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
#: The variable that aims the check at another address. A private repository answers 404
#: to the app (it has no token), so the updater is pointed at a local test server
#: (`tools/update_fixture.py`) to try the whole chain: read the release, download the
#: installer, check the digest, start the installer.
API_URL_ENV = "YOFUNSCRIPTER_UPDATE_API"
#: A private repository answers 404 to the app, so the releases are read with a token.
#: The token is taken from the environment and never stored inside the program: a
#: fine-grained token that can read the repository is enough (`YOFUNSCRIPTER_GITHUB_TOKEN`).
TOKEN_ENV = "YOFUNSCRIPTER_GITHUB_TOKEN"
SHA_SUFFIX = ".sha256"
INSTALLER_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART"]
#: Windows flag: the installer runs detached, no console window is shown.
DETACHED_PROCESS = 0x00000008
API_TIMEOUT = 15.0
#: The window of a read of the installer: a release comes over a slow link, and the
#: short timeout of the API check stops a big file in the middle with no word about it.
INSTALLER_READ_TIMEOUT = 90.0
INSTALLER_TIMEOUT = httpx.Timeout(connect=API_TIMEOUT, read=INSTALLER_READ_TIMEOUT,
                                  write=30.0, pool=API_TIMEOUT)
#: How many times a broken connection of the installer is tried again, each time from
#: the byte the file reached (the `Range` of HTTP), not from the start.
DOWNLOAD_ATTEMPTS = 3
USER_AGENT = "yoFunscripter"


class UpdateError(RuntimeError):
    """The release information cannot be read; the message is a catalog key."""


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    #: The API address of the same file (`https://api.github.com/repos/.../releases/assets/<id>`).
    #: A private repository answers 404 to `browser_download_url`, and this address with the
    #: token and `Accept: application/octet-stream` gives the file.
    api_url: str = ""


@dataclass(frozen=True)
class Release:
    """One published release: version, date, notes and the installer file."""

    version: str
    tag: str
    date: str
    body: str
    installer: Asset
    sha256_asset: Asset | None

    @property
    def has_installer(self) -> bool:
        return self.installer.name.endswith(".exe")

    @property
    def is_setup(self) -> bool:
        return self.installer.name.startswith(SETUP_PREFIX)


def parse_release(payload: Mapping[str, Any]) -> Release | None:
    """Read the API answer of `releases/latest`.

    Returns `None` for a prerelease, a draft, a release without a tag, or a release with
    no installer asset, so the caller reports nothing.
    """
    if payload.get("prerelease") is True or payload.get("draft") is True:
        return None
    tag = str(payload.get("tag_name") or "")
    if not tag:
        return None
    assets = [item for item in payload.get("assets", []) if isinstance(item, Mapping)]
    setup = next((item for item in assets
                  if str(item.get("name", "")).startswith(SETUP_PREFIX)
                  and str(item.get("name", "")).endswith(".exe")), None)
    installer = setup or next((item for item in assets
                              if str(item.get("name", "")).endswith(".exe")), None)
    if installer is None:
        return None
    sha = next((item for item in assets
                if str(item.get("name", "")).endswith(SHA_SUFFIX)), None)
    return Release(
        version=strip_v(tag),
        tag=tag,
        date=str(payload.get("published_at") or "")[:10],
        body=str(payload.get("body") or ""),
        installer=Asset(str(installer["name"]), str(installer["browser_download_url"]),
                        int(installer.get("size", 0)), str(installer.get("url", ""))),
        sha256_asset=Asset(str(sha["name"]), str(sha["browser_download_url"]), 0,
                           str(sha.get("url", ""))) if sha else None,
    )


def download_url(asset: Asset) -> str:
    """The address to read the file from: the API address with a token, the web address without.

    A private release gives 404 on `browser_download_url` (that address needs a browser
    session), so the token reads the file through the API address of the asset.
    """
    if github_token() and asset.api_url:
        return asset.api_url
    return asset.url


def strip_v(tag: str) -> str:
    """`v1.2.3` → `1.2.3`."""
    return tag[1:] if tag.startswith("v") else tag


def parse_version(text: str) -> Version | None:
    """SemVer of the release, `None` when the string is not a version."""
    try:
        return Version(strip_v(text))
    except InvalidVersion:
        return None


def is_newer(current: str, latest: str) -> bool:
    """`True` when the release version is above the running one."""
    mine = parse_version(current)
    theirs = parse_version(latest)
    if mine is None or theirs is None:
        return False
    return theirs > mine


def github_token() -> str:
    """The token of the releases from the environment, empty when there is none."""
    return os.environ.get(TOKEN_ENV, "").strip()


def auth_headers(extra: dict | None = None) -> dict:
    """The headers of a request: the user agent, and the token when the repository is private."""
    headers = {"User-Agent": USER_AGENT}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


def api_url() -> str:
    """Where to read `releases/latest`: the variable's address, else the repository."""
    return os.environ.get(API_URL_ENV, "").strip() or API_URL


def fetch_release(url: str | None = None, timeout: float = API_TIMEOUT) -> Release | None:
    """`GET` the latest release; `None` when there is nothing to show.

    Raises `UpdateError` on a network failure, so the caller writes one console line and
    keeps running.
    """
    target = url or api_url()
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.get(target, headers=auth_headers(
                {"Accept": "application/vnd.github+json"}))
    except httpx.HTTPError as exc:
        raise UpdateError(tr("update_failed", reason=exc)) from exc
    if response.status_code == 404:
        # A repository without published releases answers 404: nothing to show.
        return None
    if response.status_code == 403:
        raise UpdateError(tr("update_failed", reason="rate limit"))
    if response.status_code >= 400:
        raise UpdateError(tr("update_failed", reason=f"HTTP {response.status_code}"))
    return parse_release(response.json())


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, read in one MB chunks."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha(text: str) -> str:
    """Hex digest from a `.sha256` file (`<hex> filename` or plain hex)."""
    first = text.strip().split()[0] if text.strip() else ""
    return first.lower()


def fetch_expected_sha(asset: Asset) -> str:
    """The expected digest from the release asset."""
    try:
        with httpx.Client(follow_redirects=True, timeout=API_TIMEOUT) as client:
            response = client.get(download_url(asset),
                                  headers=auth_headers({"Accept": "application/octet-stream"}))
    except httpx.HTTPError as exc:
        raise UpdateError(tr("update_failed", reason=exc)) from exc
    if response.status_code >= 400:
        raise UpdateError(tr("update_failed", reason=f"HTTP {response.status_code}"))
    return parse_sha(response.text)


def verify(path: Path, expected: str) -> bool:
    """True when the downloaded installer matches the published digest."""
    return sha256_of(path) == expected.lower()


def _final_size(headers: Mapping[str, str], done: int, length: int) -> int:
    """The whole size of the installer the server promises.

    A normal answer says the size in `Content-Length`. A part of the file (`206`) says
    only what is left and writes the whole size in `Content-Range`, so the bar needs that
    number to show the bytes already on disk against the full file.
    """
    span = headers.get("content-range", "")
    if "/" in span:
        tail = span.rsplit("/", 1)[1]
        if tail.isdigit():
            return int(tail)
    return done + length


def download_installer(asset: Asset, target: Path, on_chunk=None) -> Path:
    """Save the installer to `target`; `on_chunk(written, total)` reports the bytes.

    A connection that breaks is tried again from the byte the file reached. Every network
    failure is turned into `UpdateError`, so the console names the reason instead of
    leaving the program to hang with a moving bar and no word about the update.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    url = download_url(asset)
    last: Exception | None = None
    for _attempt in range(DOWNLOAD_ATTEMPTS):
        done = target.stat().st_size if target.exists() else 0
        headers = auth_headers({"Accept": "application/octet-stream"})
        if done:
            headers["Range"] = f"bytes={done}-"
        try:
            with httpx.stream("GET", url, follow_redirects=True,
                              timeout=INSTALLER_TIMEOUT, headers=headers) as response:
                if response.status_code >= 400:
                    raise UpdateError(tr("update_failed", reason=f"HTTP {response.status_code}"))
                if response.status_code == 416:
                    # The server has no bytes after the ones the file already has: the
                    # installer is whole.
                    return target
                length = int(response.headers.get("content-length", 0) or 0)
                final = _final_size(response.headers, done, length)
                written = done
                with target.open("ab") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
                        written += len(chunk)
                        if on_chunk is not None:
                            on_chunk(written, final)
                if final and written >= final:
                    return target
        except UpdateError:
            # A reason the user must hear (HTTP 404, a cancel): the same address answers
            # the same way, so trying it again is pointless.
            raise
        except httpx.HTTPError as exc:
            last = exc
            continue
    if not target.exists() or target.stat().st_size == 0:
        raise UpdateError(tr("update_failed", reason=last or "empty answer"))
    return target


def installer_command(path: Path) -> list[str]:
    """The installer is run silently with the applications closed."""
    return [str(path), *INSTALLER_ARGS]


def run_installer(path: Path) -> subprocess.Popen:
    """Start the installer as a detached process; the caller exits the program."""
    return subprocess.Popen(installer_command(path), creationflags=DETACHED_PROCESS)
