"""Updater: release parsing, version comparison, digest parsing, resume of the download."""

from __future__ import annotations

from pathlib import Path

import pytest

from yofunscripter.update import checker


def _release(name="YoFunscripter-Setup-1.2.3.exe", **extra):
    asset = {"name": name, "browser_download_url": "https://example.test/" + name,
             "size": 1234}
    payload = {"tag_name": "v1.2.3", "published_at": "2026-05-01T10:00:00Z",
               "body": "notes", "assets": [asset,
                                          {"name": name + ".sha256",
                                           "browser_download_url": "https://example.test/sha",
                                           "size": 70}]}
    payload.update(extra)
    return payload


def test_parse_release():
    release = checker.parse_release(_release())
    assert release is not None
    assert release.version == "1.2.3"
    assert release.is_setup is True
    assert release.has_installer is True
    assert release.sha256_asset is not None


def test_parse_release_ignores_drafts_and_prereleases():
    assert checker.parse_release(_release(draft=True)) is None
    assert checker.parse_release(_release(prerelease=True)) is None
    assert checker.parse_release({"tag_name": "", "assets": []}) is None
    assert checker.parse_release({"tag_name": "v1.0.0", "assets": []}) is None


def test_plain_exe_when_no_setup_asset():
    release = checker.parse_release(_release("yoFunscripter-portable.exe"))
    assert release is not None
    assert release.is_setup is False
    assert release.has_installer is True


def test_versions():
    assert checker.strip_v("v2.0.0") == "2.0.0"
    assert checker.strip_v("2.0.0") == "2.0.0"
    assert checker.is_newer("1.0.0", "1.2.3") is True
    assert checker.is_newer("1.2.3", "1.2.3") is False
    assert checker.is_newer("2.0.0", "1.9.9") is False
    assert checker.is_newer("1.0.0", "nightly") is False


def test_api_url_override(monkeypatch):
    monkeypatch.delenv(checker.API_URL_ENV, raising=False)
    assert checker.api_url() == checker.API_URL
    monkeypatch.setenv(checker.API_URL_ENV, "http://127.0.0.1:8765/release.json")
    assert checker.api_url() == "http://127.0.0.1:8765/release.json"
    monkeypatch.setenv(checker.API_URL_ENV, "   ")
    assert checker.api_url() == checker.API_URL


def test_token_headers(monkeypatch):
    monkeypatch.delenv(checker.TOKEN_ENV, raising=False)
    assert checker.auth_headers() == {"User-Agent": checker.USER_AGENT}
    monkeypatch.setenv(checker.TOKEN_ENV, "abc")
    assert checker.auth_headers()["Authorization"] == "Bearer abc"
    head = checker.auth_headers({"Accept": "application/vnd.github+json"})
    assert head["Accept"] == "application/vnd.github+json"
    assert head["Authorization"] == "Bearer abc"


class _Client:
    """A `httpx.Client` that answers one canned response and remembers the request."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.sent = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None):
        self.sent = {"url": url, "headers": dict(headers or {})}
        return _HttpResponse(self.payload, self.status)


class _HttpResponse:
    def __init__(self, payload, status):
        self.payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self.payload


def test_fetch_release_uses_the_token(monkeypatch):
    monkeypatch.setenv(checker.TOKEN_ENV, "secret-token")
    client = _Client(_release())
    monkeypatch.setattr(checker.httpx, "Client", lambda **kw: client)
    release = checker.fetch_release()
    assert release.version == "1.2.3"
    assert client.sent["headers"]["Authorization"] == "Bearer secret-token"


def test_fetch_release_without_a_token(monkeypatch):
    monkeypatch.delenv(checker.TOKEN_ENV, raising=False)
    client = _Client(_release())
    monkeypatch.setattr(checker.httpx, "Client", lambda **kw: client)
    checker.fetch_release()
    assert "Authorization" not in client.sent["headers"]
    assert client.sent["url"] == checker.API_URL


def test_parse_sha():
    assert checker.parse_sha("ABCDEF  file.exe\n") == "abcdef"
    assert checker.parse_sha("  abcdef  ") == "abcdef"
    assert checker.parse_sha("") == ""


def test_final_size_uses_content_range():
    headers = {"content-range": "bytes 100-199/1000"}
    assert checker._final_size(headers, 100, 100) == 1000
    assert checker._final_size({}, 0, 500) == 500


def test_sha256_and_verify(tmp_path: Path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"yoFunscripter")
    digest = checker.sha256_of(path)
    assert checker.verify(path, digest) is True
    assert checker.verify(path, "0" * 64) is False


def test_installer_command():
    cmd = checker.installer_command(Path("C:/tmp/setup.exe"))
    assert cmd[0] == str(Path("C:/tmp/setup.exe"))
    assert "/SILENT" in cmd and "/CLOSEAPPLICATIONS" in cmd


class _Response:
    def __init__(self, status_code=206, headers=None, chunks=(b"abc",)):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks

    def iter_bytes(self, _size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_resumes_from_existing_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv(checker.TOKEN_ENV, "token")
    asset = checker.Asset("setup.exe", "https://example.test/setup.exe", 6)
    target = tmp_path / "setup.exe"
    target.write_bytes(b"old")
    seen = {}

    def fake_stream(method, url, **kwargs):
        seen.update(kwargs)
        return _Response(headers={"content-range": "bytes 3-5/6"}, chunks=(b"def",))

    monkeypatch.setattr(checker.httpx, "stream", fake_stream)
    checker.download_installer(asset, target)
    assert seen["headers"]["Range"] == "bytes=3-"
    assert seen["headers"]["Authorization"] == "Bearer token"
    assert target.read_bytes() == b"olddef"


def test_download_empty_answer_is_an_error(tmp_path, monkeypatch):
    def fake_stream(method, url, **kwargs):
        return _Response(status_code=500)

    monkeypatch.setattr(checker.httpx, "stream", fake_stream)
    asset = checker.Asset("setup.exe", "https://example.test/setup.exe", 6)
    with pytest.raises(checker.UpdateError):
        checker.download_installer(asset, tmp_path / "s.exe")


def test_download_url_of_a_private_release(monkeypatch):
    asset = checker.Asset("setup.exe", "https://github.com/x/y/releases/download/v1/s.exe",
                          6, "https://api.github.com/repos/x/y/releases/assets/7")
    monkeypatch.delenv(checker.TOKEN_ENV, raising=False)
    assert checker.download_url(asset) == asset.url
    monkeypatch.setenv(checker.TOKEN_ENV, "token")
    assert checker.download_url(asset) == asset.api_url
    monkeypatch.setenv(checker.TOKEN_ENV, "")
    assert checker.download_url(asset) == asset.url


def test_parse_release_keeps_the_api_url():
    payload = _release()
    payload["assets"][0]["url"] = "https://api.github.com/repos/x/y/releases/assets/7"
    release = checker.parse_release(payload)
    assert release.installer.api_url.endswith("/assets/7")
