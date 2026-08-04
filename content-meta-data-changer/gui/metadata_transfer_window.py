"""Window for copying metadata from one video onto another."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.common import supported_extension_hint
from metadata import supported_extensions
from metadata_transfer import MetadataTransferError, transfer_metadata


class MetadataTransferWorker(QThread):
    finished_ok = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, target: Path, source: Path, destination: Path) -> None:
        super().__init__()
        self._target = target
        self._source = source
        self._destination = destination

    def run(self) -> None:
        try:
            output = transfer_metadata(self._target, self._source, self._destination)
        except MetadataTransferError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")
            return

        self.finished_ok.emit(output)


class MetadataTransferWindow(QMainWindow):
    def __init__(
        self,
        target_path: Path,
        library_paths: list[Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._target_path = target_path.resolve()
        self._library_paths = [path.resolve() for path in library_paths]
        self._worker: MetadataTransferWorker | None = None

        self.setWindowTitle("Transfer Metadata")
        self.setMinimumSize(560, 260)
        self.resize(640, 280)

        intro = QLabel(
            "Create a new file that keeps the media from the target file and copies metadata "
            "from another file. Videos use QuickTime atom grafting; images use EXIF/PNG metadata."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aaaaaa;")

        self._target_label = QLabel(str(self._target_path))
        self._target_label.setWordWrap(True)
        self._target_label.setTextInteractionFlags(
            self._target_label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(320)
        self._populate_source_choices()

        self._browse_source_button = QPushButton("Browse…")
        self._browse_source_button.clicked.connect(self._browse_source)

        source_row = QHBoxLayout()
        source_row.addWidget(self._source_combo, stretch=1)
        source_row.addWidget(self._browse_source_button)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Choose where to save the new file")
        self._output_edit.setText(self._default_output_path())

        self._browse_output_button = QPushButton("Browse…")
        self._browse_output_button.clicked.connect(self._browse_output)

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit, stretch=1)
        output_row.addWidget(self._browse_output_button)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        form.addRow("Keep video from:", self._target_label)
        form.addRow("Copy metadata from:", source_row)
        form.addRow("Save result to:", output_row)

        self._transfer_button = QPushButton("Transfer Metadata")
        self._transfer_button.clicked.connect(self._start_transfer)

        self._cancel_button = QPushButton("Close")
        self._cancel_button.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self._transfer_button)
        button_row.addWidget(self._cancel_button)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addStretch()
        layout.addLayout(button_row)
        self.setCentralWidget(container)

        self.statusBar().showMessage(f"Supported formats: {supported_extension_hint()}")

    def _default_output_path(self) -> str:
        stem = self._target_path.stem
        suffix = self._target_path.suffix or ".mp4"
        return str(self._target_path.with_name(f"{stem}_with_metadata{suffix}"))

    def _populate_source_choices(self) -> None:
        self._source_combo.clear()
        for path in self._library_paths:
            if path.resolve() == self._target_path:
                continue
            self._source_combo.addItem(path.name, str(path.resolve()))

        if self._source_combo.count() == 0:
            self._source_combo.addItem("(choose a file)", "")

    def _browse_source(self) -> None:
        extensions = " ".join(f"*{ext}" for ext in sorted(supported_extensions()))
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose metadata source",
            str(self._target_path.parent),
            f"Video files ({extensions});;All files (*)",
        )
        if not selected:
            return

        path = Path(selected)
        resolved = str(path.resolve())
        index = self._source_combo.findData(resolved)
        if index >= 0:
            self._source_combo.setCurrentIndex(index)
            return

        self._source_combo.insertItem(0, path.name, resolved)
        self._source_combo.setCurrentIndex(0)

    def _browse_output(self) -> None:
        extensions = " ".join(f"*{ext}" for ext in sorted(supported_extensions()))
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save file with transferred metadata",
            self._output_edit.text() or self._default_output_path(),
            f"Video files ({extensions});;All files (*)",
        )
        if selected:
            self._output_edit.setText(selected)

    def _selected_source_path(self) -> Path | None:
        raw = self._source_combo.currentData()
        if not raw:
            return None
        return Path(str(raw))

    def _start_transfer(self) -> None:
        source = self._selected_source_path()
        if source is None:
            QMessageBox.warning(self, "No source selected", "Choose a file to copy metadata from.")
            return

        if source.resolve() == self._target_path:
            QMessageBox.warning(
                self,
                "Same file selected",
                "Metadata source must be a different file from the target video.",
            )
            return

        output_text = self._output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "No output path", "Choose where to save the result file.")
            return

        destination = Path(output_text).resolve()
        if destination == self._target_path or destination == source.resolve():
            QMessageBox.warning(
                self,
                "Unsafe output path",
                "The output file must be different from both the target and metadata source files.",
            )
            return

        if destination.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite file?",
                f"{destination.name} already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Transfer in progress", "Please wait for the current transfer to finish.")
            return

        self._set_busy(True)
        self.statusBar().showMessage("Transferring metadata…")

        self._worker = MetadataTransferWorker(self._target_path, source, destination)
        self._worker.finished_ok.connect(self._on_transfer_finished)
        self._worker.failed.connect(self._on_transfer_failed)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self._transfer_button.setEnabled(not busy)
        self._browse_source_button.setEnabled(not busy)
        self._browse_output_button.setEnabled(not busy)
        self._source_combo.setEnabled(not busy)
        self._output_edit.setEnabled(not busy)

    def _on_transfer_finished(self, destination: Path) -> None:
        self._set_busy(False)
        self.statusBar().showMessage(f"Saved to {destination}", 5000)
        QMessageBox.information(
            self,
            "Transfer complete",
            f"Metadata copied successfully.\n\nSaved to:\n{destination}",
        )

    def _on_transfer_failed(self, message: str) -> None:
        self._set_busy(False)
        self.statusBar().showMessage("Metadata transfer failed", 5000)
        QMessageBox.critical(self, "Transfer failed", message)
