"""Update check in the window: dialog, download, install.

The check runs in a thread so the window stays responsive. The dialog shows the version
and the release notes with the buttons «Run the installer», «Cancel». The installer is
downloaded in the thread with a progress bar of real megabytes, verified by SHA-256 when
the release publishes the digest, started with `/SILENT /CLOSEAPPLICATIONS /NORESTART`,
and the program exits.

Every failure of the download, of the digest and of the launch goes to the console: the
program must say why an update did not arrive, not close with a bar that moves forever.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

from yofunscripter.i18n import tr
from yofunscripter.update import checker
from yofunscripter.update.checker import Release, UpdateError


def megabytes(size: int) -> int:
    """Bytes in whole megabytes, the number a person reads in the progress bar."""
    return max(1, round(size / (1024 * 1024)))


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
    failed = Signal(str)

    def __init__(self, release: Release, target_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.target = target_dir / release.installer.name

    def _chunk(self, written: int, total: int) -> None:
        self.progress.emit(megabytes(written), megabytes(total))

    def run(self) -> None:
        try:
            path = checker.download_installer(self.release.installer.url, self.target,
                                              self._chunk)
            if self.release.sha256_asset is not None:
                expected = checker.fetch_expected_sha(self.release.sha256_asset.url)
                if not checker.verify(path, expected):
                    self.failed.emit(tr("sha_mismatch"))
                    return
            self.downloaded.emit(str(path))
        except UpdateError as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Version, notes, the download bar, the button of the installer."""

    def __init__(self, release: Release, target_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.target_dir = target_dir
        self.path: Path | None = None
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
        self.status = QLabel(tr("downloading", file=release.installer.name))
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox()
        self.download_button = self.buttons.addButton(tr("download"),
                                                       QDialogButtonBox.AcceptRole)
        self.install_button = self.buttons.addButton(tr("install_now"),
                                                      QDialogButtonBox.AcceptRole)
        self.install_button.setEnabled(False)
        self.buttons.addButton(tr("close"), QDialogButtonBox.RejectRole)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self._accepted)
        self.buttons.rejected.connect(self.reject)
        self.thread: DownloadThread | None = None

    def _accepted(self) -> None:
        if self.path is not None:
            # The installer is on disk: start it and leave, the installer runs the new
            # version at its end.
            checker.run_installer(self.path)
            self.accept()
            return
        if self.thread is not None:
            return
        self.thread = DownloadThread(self.release, self.target_dir, self)
        self.thread.progress.connect(self._progress)
        self.thread.downloaded.connect(self._downloaded)
        self.thread.failed.connect(self._failed)
        self.thread.start()

    def _progress(self, written: int, total: int) -> None:
        if total > 0:
            self.bar.setValue(min(100, int(written * 100 / total)))
        self.status.setText(f"{written} / {total} MB")

    def _downloaded(self, path: str) -> None:
        self.path = Path(path)
        self.bar.setValue(100)
        self.status.setText(tr("update_ready", file=self.path.name))
        self.install_button.setEnabled(True)
        self.download_button.setEnabled(False)

    def _failed(self, reason: str) -> None:
        self.status.setText(tr("update_failed", reason=reason))
        self.download_button.setEnabled(True)
