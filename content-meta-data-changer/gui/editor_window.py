"""Per-file editor window with metadata, preview, and memory layout."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from conversion import ConversionTarget, find_ffmpeg
from image_conversion import ImageConversionTarget
from media_types import is_convertible_video, is_image_path, is_video_path
from gui.common import (
    MIN_WINDOW_WITH_PREVIEW,
    MIN_WINDOW_WITHOUT_PREVIEW,
    PREVIEW_AREA_MIN_SIZE,
    ControlPanel,
    ConversionWorker,
    ImageConversionWorker,
    UpdatePreviewWorker,
    VideoPreviewWidget,
    read_first_frame,
)
from layout import LayoutParseError, parse_file_layout
from layout.atom_database import format_unknown_atom_keys
from layout.base import FileLayout, format_unknown_memory_segments
from layout.unknown_headers_dialog import UnknownHeadersDialog, UnknownMemoryDialog
from layout.widget import MemoryLayoutPanel
from metadata import UnsupportedFormatError, format_metadata


class MediaEditorWindow(QMainWindow):
    closed = pyqtSignal()

    def __init__(self, video_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = video_path.resolve()
        self._current_layout: FileLayout | None = None
        self._conversion_worker: ConversionWorker | ImageConversionWorker | UpdatePreviewWorker | None = None
        self._preview_visible = True

        self.setWindowTitle(f"{self._video_path.name} — Content Metadata Changer")
        self.resize(1400, 720)

        self.preview_widget = VideoPreviewWidget()

        self.metadata_view = QPlainTextEdit()
        self.metadata_view.setReadOnly(True)
        self.metadata_view.setPlaceholderText("Metadata will appear here.")
        self.metadata_view.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                font-size: 13px;
                padding: 8px;
            }
            """
        )

        self._preview_panel = QWidget()
        preview_layout = QVBoxLayout(self._preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_header = QWidget()
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(0, 0, 0, 0)
        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("color: #cccccc; font-weight: bold;")
        preview_header_layout.addWidget(preview_label)
        preview_header_layout.addStretch()
        preview_layout.addWidget(preview_header)
        preview_layout.addWidget(self.preview_widget, stretch=1)

        metadata_panel = QWidget()
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_label = QLabel("Metadata")
        metadata_label.setStyleSheet("color: #cccccc; font-weight: bold;")
        metadata_layout.addWidget(metadata_label)
        metadata_layout.addWidget(self.metadata_view, stretch=1)

        self.memory_layout_panel = MemoryLayoutPanel()

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.addWidget(self._preview_panel)
        content_splitter.addWidget(metadata_panel)
        content_splitter.addWidget(self.memory_layout_panel)
        self._content_splitter = content_splitter
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setStretchFactor(2, 2)

        media_kind = "image" if is_image_path(self._video_path) else "video"
        self.control_panel = ControlPanel(media_kind=media_kind)
        self.control_panel.set_preview_visible(True)
        self.control_panel.convert_video_requested.connect(self.convert_video)
        self.control_panel.convert_image_requested.connect(self.convert_image)
        self.control_panel.update_preview_requested.connect(self.update_preview)
        self.control_panel.preview_toggle_requested.connect(self._toggle_preview)
        self.control_panel.unknown_headers_requested.connect(self.show_unknown_headers)
        self.control_panel.unknown_memory_requested.connect(self.show_unknown_memory)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(content_splitter, stretch=1)
        layout.addWidget(self.control_panel)
        self.setCentralWidget(container)
        self._apply_preview_layout()
        self._load_video()

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)

    @property
    def video_path(self) -> Path:
        return self._video_path

    def _apply_preview_layout(self) -> None:
        if self._preview_visible:
            self.preview_widget.setMinimumSize(*PREVIEW_AREA_MIN_SIZE)
            self._preview_panel.setMinimumSize(0, 0)
            self._preview_panel.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(*MIN_WINDOW_WITH_PREVIEW)
        else:
            self.preview_widget.setMinimumSize(0, 0)
            self._preview_panel.setMinimumSize(0, 0)
            self._preview_panel.setMaximumSize(0, 0)
            self.setMinimumSize(*MIN_WINDOW_WITHOUT_PREVIEW)

    def _toggle_preview(self) -> None:
        self._preview_visible = not self._preview_visible
        self._preview_panel.setVisible(self._preview_visible)
        self.control_panel.set_preview_visible(self._preview_visible)
        self._apply_preview_layout()

    def show_unknown_headers(self) -> None:
        if self._current_layout is None:
            QMessageBox.information(
                self,
                "No layout loaded",
                "This file does not have a parsed memory layout.",
            )
            return

        headers_text = format_unknown_atom_keys(self._current_layout.segments)
        dialog = UnknownHeadersDialog(headers_text, self)
        dialog.exec()

    def show_unknown_memory(self) -> None:
        if self._current_layout is None:
            QMessageBox.information(
                self,
                "No layout loaded",
                "This file does not have a parsed memory layout.",
            )
            return

        memory_text = format_unknown_memory_segments(self._current_layout.segments)
        dialog = UnknownMemoryDialog(memory_text, self)
        dialog.exec()

    def _load_video(self) -> None:
        path = self._video_path
        try:
            metadata_text = format_metadata(path)
        except UnsupportedFormatError as exc:
            QMessageBox.warning(self, "Unsupported file", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Metadata error", f"Could not read metadata:\n{exc}")
            return

        pixmap = read_first_frame(path)
        if pixmap is None:
            self.preview_widget.show_placeholder("Could not load preview.")
        else:
            self.preview_widget.set_preview(pixmap)

        self.metadata_view.setPlainText(metadata_text)

        try:
            file_layout = parse_file_layout(path)
            self._current_layout = file_layout
            self.memory_layout_panel.set_layout(file_layout, path)
            self.memory_layout_panel.fit_to_current_width()
            self.control_panel.set_unknown_headers_enabled(True)
        except LayoutParseError as exc:
            self._current_layout = None
            self.memory_layout_panel.set_layout(None)
            self.control_panel.set_unknown_headers_enabled(False)
            QMessageBox.warning(self, "Layout parse error", f"Could not parse file layout:\n{exc}")

    def convert_image(self, target: ImageConversionTarget) -> None:
        if not is_image_path(self._video_path):
            QMessageBox.information(self, "Not an image", "Conversion is only available for image files.")
            return

        if self._conversion_worker is not None and self._conversion_worker.isRunning():
            QMessageBox.information(self, "Conversion in progress", "Please wait for the current conversion to finish.")
            return

        default_name = f"{self._video_path.stem}{target.extension}"
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {target.label}",
            str(self._video_path.with_name(default_name)),
            target.file_filter,
        )
        if not selected_path:
            return

        destination = Path(selected_path)
        self.control_panel.set_enabled(False)
        self.statusBar().showMessage(f"Converting to {target.extension}...")

        self._conversion_worker = ImageConversionWorker(self._video_path, destination, target)
        self._conversion_worker.finished_ok.connect(self._on_conversion_finished)
        self._conversion_worker.failed.connect(self._on_conversion_failed)
        self._conversion_worker.start()

    def convert_video(self, target: ConversionTarget) -> None:
        if not is_convertible_video(self._video_path):
            QMessageBox.information(self, "Not a video", "Conversion is only available for video files.")
            return

        if find_ffmpeg() is None:
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg is required for conversion.\n\nInstall it with:\nbrew install ffmpeg",
            )
            return

        if self._conversion_worker is not None and self._conversion_worker.isRunning():
            QMessageBox.information(self, "Conversion in progress", "Please wait for the current conversion to finish.")
            return

        default_name = f"{self._video_path.stem}{target.extension}"
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {target.label}",
            str(self._video_path.with_name(default_name)),
            target.file_filter,
        )
        if not selected_path:
            return

        destination = Path(selected_path)
        self.control_panel.set_enabled(False)
        self.statusBar().showMessage(f"Converting to {target.extension}...")

        self._conversion_worker = ConversionWorker(self._video_path, destination, target)
        self._conversion_worker.finished_ok.connect(self._on_conversion_finished)
        self._conversion_worker.failed.connect(self._on_conversion_failed)
        self._conversion_worker.start()

    def update_preview(self) -> None:
        if not is_video_path(self._video_path):
            QMessageBox.information(self, "Not a video", "Preview update is only available for video files.")
            return

        if self._conversion_worker is not None and self._conversion_worker.isRunning():
            QMessageBox.information(
                self,
                "Operation in progress",
                "Please wait for the current operation to finish.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Update Preview",
            (
                "Replace the embedded Finder artwork with a JPEG from the first frame?\n\n"
                f"File: {self._video_path.name}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.control_panel.set_enabled(False)
        self.statusBar().showMessage("Updating embedded preview...")

        self._conversion_worker = UpdatePreviewWorker(self._video_path)
        self._conversion_worker.finished_ok.connect(self._on_preview_update_finished)
        self._conversion_worker.failed.connect(self._on_preview_update_failed)
        self._conversion_worker.start()

    def _on_preview_update_finished(self) -> None:
        self.control_panel.set_enabled(True)
        self.statusBar().showMessage("Embedded preview updated.", 5000)
        self._load_video()
        QMessageBox.information(
            self,
            "Preview updated",
            "Embedded Finder artwork was replaced with the first frame.",
        )

    def _on_preview_update_failed(self, message: str) -> None:
        self.control_panel.set_enabled(True)
        self.statusBar().showMessage("Preview update failed", 5000)
        QMessageBox.critical(self, "Preview update failed", message)

    def _on_conversion_finished(self, destination: Path) -> None:
        self.control_panel.set_enabled(True)
        label = "image" if is_image_path(self._video_path) else "video"
        self.statusBar().showMessage(f"Saved converted {label} to {destination}", 5000)
        QMessageBox.information(self, "Conversion complete", f"File saved to:\n{destination}")

    def _on_conversion_failed(self, message: str) -> None:
        self.control_panel.set_enabled(True)
        self.statusBar().showMessage("Conversion failed", 5000)
        QMessageBox.critical(self, "Conversion failed", message)
