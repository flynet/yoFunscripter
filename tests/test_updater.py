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
    target = tmp_path / "setup.exe"
    target.write_bytes(b"old")
    seen = {}

    def fake_stream(method, url, **kwargs):
        seen.update(kwargs)
        return _Response(headers={"content-range": "bytes 3-5/6"}, chunks=(b"def",))

    monkeypatch.setattr(checker.httpx, "stream", fake_stream)
    checker.download_installer("https://example.test/setup.exe", target)
    assert seen["headers"]["Range"] == "bytes=3-"
    assert target.read_bytes() == b"olddef"


def test_download_empty_answer_is_an_error(tmp_path, monkeypatch):
    def fake_stream(method, url, **kwargs):
        return _Response(status_code=500)

    monkeypatch.setattr(checker.httpx, "stream", fake_stream)
    with pytest.raises(checker.UpdateError):
        checker.download_installer("https://example.test/setup.exe", tmp_path / "s.exe")
