"""Shared GUI widgets, workers, and styling."""

from __future__ import annotations

from pathlib import Path

import cv2
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton

from conversion import CONVERSION_TARGETS, ConversionTarget
from formats.heif_support import register_heif_opener
from image_conversion import IMAGE_CONVERSION_TARGETS, ImageConversionTarget
from media_types import IMAGE_EXTENSIONS
from metadata import supported_extensions

MIN_WINDOW_WITH_PREVIEW = (1200, 520)
MIN_WINDOW_WITHOUT_PREVIEW = (640, 420)
PREVIEW_AREA_MIN_SIZE = (480, 360)

APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
}
QListWidget {
    background-color: #252526;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    font-size: 13px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 0px;
    border-radius: 4px;
}
QListWidget::item:selected,
QListWidget::item:selected:active,
QListWidget::item:selected:!active {
    background-color: #3a3a3d;
    color: #d4d4d4;
}
QListWidget::item:hover {
    background-color: #2d2d30;
}
QPushButton {
    background-color: #2d2d30;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    padding: 8px 14px;
}
QPushButton:hover {
    background-color: #3a3a3d;
}
QPushButton:disabled {
    color: #777777;
}
"""


def read_first_frame(path: Path) -> QImage | None:
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return read_image_preview(path)

    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            return None

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = frame_rgb.shape
        return QImage(
            frame_rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
    finally:
        capture.release()


def read_image_preview(path: Path) -> QImage | None:
    try:
        from PIL import Image

        register_heif_opener()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            data = rgb.tobytes("raw", "RGB")
            return QImage(
                data,
                rgb.width,
                rgb.height,
                rgb.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
    except Exception:
        image = QImage(str(path))
        if not image.isNull():
            return image

        frame = cv2.imread(str(path))
        if frame is None:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = frame_rgb.shape
        return QImage(
            frame_rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()


class ConversionWorker(QThread):
    finished_ok = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, source: Path, destination: Path, target: ConversionTarget) -> None:
        super().__init__()
        self._source = source
        self._destination = destination
        self._target = target

    def run(self) -> None:
        try:
            from conversion import convert_video

            convert_video(self._source, self._destination, self._target)
        except Exception as exc:
            from conversion import ConversionError

            if isinstance(exc, ConversionError):
                self.failed.emit(str(exc))
            else:
                self.failed.emit(f"Unexpected conversion error: {exc}")
            return

        self.finished_ok.emit(self._destination)


class ImageConversionWorker(QThread):
    finished_ok = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, source: Path, destination: Path, target: ImageConversionTarget) -> None:
        super().__init__()
        self._source = source
        self._destination = destination
        self._target = target

    def run(self) -> None:
        try:
            from image_conversion import convert_image

            convert_image(self._source, self._destination, self._target)
        except Exception as exc:
            from image_conversion import ImageConversionError

            if isinstance(exc, ImageConversionError):
                self.failed.emit(str(exc))
            else:
                self.failed.emit(f"Unexpected conversion error: {exc}")
            return

        self.finished_ok.emit(self._destination)


class VideoPreviewWidget(QLabel):
    """Read-only preview area for a loaded video frame."""

    def __init__(self) -> None:
        super().__init__()
        self._source_pixmap: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(*PREVIEW_AREA_MIN_SIZE)
        self.setStyleSheet(
            """
            QLabel {
                background-color: #1e1e1e;
                color: #aaaaaa;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                font-size: 14px;
            }
            """
        )
        self.show_placeholder()

    def show_placeholder(self, message: str = "No preview available") -> None:
        self._source_pixmap = None
        self.setText(message)
        self.setPixmap(QPixmap())

    def set_preview(self, image: QImage) -> None:
        self._source_pixmap = QPixmap.fromImage(image)
        self.setText("")
        self._update_scaled_preview()

    def _update_scaled_preview(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled_preview()


class UpdatePreviewWorker(QThread):
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, source: Path) -> None:
        super().__init__()
        self._source = source

    def run(self) -> None:
        try:
            from video_preview import VideoPreviewError, update_video_preview

            update_video_preview(self._source)
        except VideoPreviewError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"Unexpected preview update error: {exc}")
            return

        self.finished_ok.emit()


class ControlPanel(QGroupBox):
    convert_video_requested = pyqtSignal(ConversionTarget)
    convert_image_requested = pyqtSignal(ImageConversionTarget)
    update_preview_requested = pyqtSignal()
    preview_toggle_requested = pyqtSignal()
    unknown_headers_requested = pyqtSignal()
    unknown_memory_requested = pyqtSignal()

    def __init__(self, media_kind: str = "video") -> None:
        super().__init__("Controls")
        self.setStyleSheet(
            """
            QGroupBox {
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                margin-top: 12px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 12)

        self._preview_toggle_button = QPushButton("Hide Preview")
        self._preview_toggle_button.clicked.connect(self.preview_toggle_requested.emit)
        layout.addWidget(self._preview_toggle_button)

        self._update_preview_button = QPushButton("Update Preview")
        self._update_preview_button.clicked.connect(self.update_preview_requested.emit)
        layout.addWidget(self._update_preview_button)

        convert_label = QLabel("Convert:")
        convert_label.setStyleSheet("color: #cccccc; font-weight: normal;")
        layout.addWidget(convert_label)

        self._video_convert_buttons: list[QPushButton] = []
        for target in CONVERSION_TARGETS:
            button = QPushButton(target.label)
            button.clicked.connect(
                lambda _checked=False, t=target: self.convert_video_requested.emit(t)
            )
            self._video_convert_buttons.append(button)
            layout.addWidget(button)

        self._image_convert_buttons: list[QPushButton] = []
        for target in IMAGE_CONVERSION_TARGETS:
            button = QPushButton(target.label)
            button.clicked.connect(
                lambda _checked=False, t=target: self.convert_image_requested.emit(t)
            )
            self._image_convert_buttons.append(button)
            layout.addWidget(button)

        self._unknown_headers_button = QPushButton("Unknown Headers")
        self._unknown_headers_button.clicked.connect(self.unknown_headers_requested.emit)
        self._unknown_headers_button.setEnabled(False)
        layout.addWidget(self._unknown_headers_button)

        self._unknown_memory_button = QPushButton("Unknown Memory")
        self._unknown_memory_button.clicked.connect(self.unknown_memory_requested.emit)
        self._unknown_memory_button.setEnabled(False)
        layout.addWidget(self._unknown_memory_button)

        layout.addStretch()
        self.set_media_kind(media_kind)

    def set_media_kind(self, media_kind: str) -> None:
        self._media_kind = media_kind
        for button in self._video_convert_buttons:
            button.setVisible(media_kind == "video")
        for button in self._image_convert_buttons:
            button.setVisible(media_kind == "image")
        self._update_preview_button.setVisible(media_kind == "video")
        self.set_convert_enabled(True)

    def set_preview_visible(self, visible: bool) -> None:
        self._preview_toggle_button.setText("Hide Preview" if visible else "Show Preview")

    def set_convert_enabled(self, enabled: bool) -> None:
        buttons = (
            self._image_convert_buttons
            if getattr(self, "_media_kind", "video") == "image"
            else self._video_convert_buttons
        )
        for button in buttons:
            button.setEnabled(enabled)

    def set_enabled(self, enabled: bool) -> None:
        self.set_convert_enabled(enabled)
        self._update_preview_button.setEnabled(enabled)

    def set_unknown_headers_enabled(self, enabled: bool) -> None:
        self._unknown_headers_button.setEnabled(enabled)
        self._unknown_memory_button.setEnabled(enabled)


def supported_extension_hint() -> str:
    return ", ".join(sorted(supported_extensions()))
