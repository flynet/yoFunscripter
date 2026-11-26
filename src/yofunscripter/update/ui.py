"""Update check in the window: dialog, download, install.

The check runs in a thread so the window stays responsive. The dialog shows the version
and the release notes with two buttons: «Update» and «Close». «Update» downloads the
installer in the thread with a bar of real megabytes, checks the SHA-256 when the release
publishes the digest, starts the installer with `/SILENT /CLOSEAPPLICATIONS /NORESTART`
and the program leaves. While the file comes, the same button reads «Cancel»: it stops
the download, the bytes already on disk are kept, and the next «Update» continues from
the byte the file reached.

Every failure of the download, of the digest and of the launch goes to the console: the
program must say why an update did not arrive, not close with a bar that moves forever.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

from yofunscripter.i18n import tr
from yofunscripter.pipeline.cancel import Cancelled, CancelToken
from yofunscripter.update import checker
from yofunscripter.update.checker import Release, UpdateError


def megabytes(size: int) -> int:
    """Bytes in whole megabytes, the number a person reads in the progress bar."""
    return max(1, round(size / (1024 * 1024)))


def _repolish(button, text: str, name: str) -> None:
    """The «Update» button is the «Cancel» of the download: the text, the red style of
    `QPushButton#danger` and the flag that the run is going all change together, and Qt
    reads the object name only after the button is polished again."""
    button.setText(text)
    button.setObjectName(name)
    button.style().unpolish(button)
    button.style().polish(button)


class UpdateThread(QThread):
    """`GET` the latest release in a thread; the window does not freeze on the API."""

    found = Signal(object)      # Release | None
    failed = Signal(str)

    def run(self) -> None:
        try:
            release = checker.fetch_release()
        except UpdateError as exc:
            self.failed.emit(str(exc))
        else:
            self.found.emit(release)


class DownloadThread(QThread):
    """The installer lands with the progress of real bytes, then the digest check."""

    progress = Signal(int, int)    # MB written, MB total
    downloaded = Signal(str)       # path of the file
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, release: Release, target_dir: Path, token: CancelToken,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.target = target_dir / release.installer.name
        self.token = token

    def _chunk(self, written: int, total: int) -> None:
        self.progress.emit(megabytes(written), megabytes(total))

    def run(self) -> None:
        try:
            path = checker.download_installer(self.release.installer, self.target,
                                              self._chunk, self.token)
            if self.token.cancelled():
                self.cancelled.emit()
                return
            if self.release.sha256_asset is not None:
                expected = checker.fetch_expected_sha(self.release.sha256_asset)
                if not checker.verify(path, expected):
                    # The bytes on disk are not the installer of the release, and they must
                    # go: the next check resumes from them and fails the digest the same way.
                    path.unlink(missing_ok=True)
                    self.failed.emit(tr("sha_mismatch"))
                    return
            self.downloaded.emit(str(path))
        except Cancelled:
            # The user pressed «Cancel» in the middle of the file: the part on disk stays.
            self.cancelled.emit()
        except UpdateError as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Version, notes, the download bar, «Update» and «Close»."""

    def __init__(self, release: Release, target_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.target_dir = target_dir
        self.path: Path | None = None
        self.token = CancelToken()
        self.leaving = False
        self.setObjectName("central")
        self.setWindowTitle(tr("updates_title"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.head = QLabel(tr("new_version", version=release.version, date=release.date))
        self.head.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.head)
        if release.body:
            layout.addWidget(QLabel(tr("notes")))
            notes = QLabel(release.body)
            notes.setWordWrap(True)
            layout.addWidget(notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.status = QLabel(tr("update_ready_to", file=release.installer.name))
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox()
        self.action = self.buttons.addButton(tr("update_now"), QDialogButtonBox.AcceptRole)
        self.close_button = self.buttons.addButton(tr("close"), QDialogButtonBox.RejectRole)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self._accepted)
        self.buttons.rejected.connect(self.reject)
        self.thread: DownloadThread | None = None

    def _accepted(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            # The same button is the cancel of the running download.
            self.token.cancel()
            self.status.setText(tr("update_stopping"))
            return
        if self.thread is not None:
            # A finished download: the next run needs a flag that is not raised.
            self.token = CancelToken()
        self.thread = DownloadThread(self.release, self.target_dir, self.token, self)
        self.thread.progress.connect(self._progress)
        self.thread.downloaded.connect(self._downloaded)
        self.thread.cancelled.connect(self._cancelled)
        self.thread.failed.connect(self._failed)
        self.thread.finished.connect(self._idle_button)
        self.thread.start()
        _repolish(self.action, tr("cancel"), "danger")
        self.close_button.setEnabled(False)
        self.status.setText(tr("downloading", file=self.release.installer.name))

    def _idle_button(self) -> None:
        """The download stopped: the button reads «Update» again and the window leaves
        when the user asked to close it."""
        _repolish(self.action, tr("update_now"), "")
        self.close_button.setEnabled(True)
        if self.leaving:
            self.accept()

    def _progress(self, written: int, total: int) -> None:
        if total > 0:
            self.bar.setValue(min(100, int(written * 100 / total)))
        self.status.setText(f"{written} / {total} MB")

    def _downloaded(self, path: str) -> None:
        self.path = Path(path)
        self.bar.setValue(100)
        self.status.setText(tr("installing", file=self.path.name))
        # The installer is on disk and verified: start it and leave, the installer runs
        # the new version at its end.
        checker.run_installer(self.path)
        self.accept()

    def _cancelled(self) -> None:
        self.status.setText(tr("update_stopped", file=self.release.installer.name))

    def _failed(self, reason: str) -> None:
        self.status.setText(tr("update_failed", reason=reason))

    def reject(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            # «Close» during the download stops it, and the window leaves when it does.
            self.leaving = True
            self.token.cancel()
            self.status.setText(tr("update_stopping"))
            return
        super().reject()
