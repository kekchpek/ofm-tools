"""Interactive file memory layout visualization widget."""

from __future__ import annotations

import math

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QWheelEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from layout.atom_database import get_atom_description
from layout.base import CATEGORY_COLORS, CATEGORY_LABELS, FileLayout, FileSegment
from layout.edit_safety import (
    EDIT_SAFETY_COLORS,
    EDIT_SAFETY_LABELS,
    EDIT_SAFETY_MARKS,
    format_edit_safety_mark,
    format_edit_safety_summary,
    get_edit_safety,
)
from layout.segment_info_dialog import SegmentInfoDialog

MAP_HEIGHT = 28
MIN_BYTES_PER_PIXEL = 1
MAX_BYTES_PER_PIXEL = 1024 * 1024
MAX_SEGMENT_PREVIEW_BYTES = 512
MAX_BINARY_DISPLAY_CHARS = 1800
MAX_TEXT_DISPLAY_CHARS = 800


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


def _format_offset(offset: int) -> str:
    return f"0x{offset:08X} ({offset:,})"


def _edit_safety_tooltip(segment: FileSegment) -> str:
    safety = get_edit_safety(segment)
    mark = EDIT_SAFETY_MARKS[safety.level]
    return f"Edit safety: {mark} {safety.label}\n{safety.reason}"


def _read_segment_bytes(source_path: Path, segment: FileSegment) -> bytes:
    with source_path.open("rb") as handle:
        handle.seek(segment.offset)
        return handle.read(min(segment.size, MAX_SEGMENT_PREVIEW_BYTES))


def _format_binary(data: bytes, total_size: int) -> str:
    hex_bytes = " ".join(f"{byte:02X}" for byte in data)
    if len(hex_bytes) > MAX_BINARY_DISPLAY_CHARS:
        hex_bytes = hex_bytes[: MAX_BINARY_DISPLAY_CHARS - 4].rstrip() + " ..."
    elif total_size > len(data):
        hex_bytes += " ..."
    return hex_bytes


def _format_text(data: bytes, total_size: int) -> str:
    chars: list[str] = []
    for byte in data:
        if 32 <= byte <= 126:
            chars.append(chr(byte))
        elif byte in (9, 10, 13):
            chars.append(chr(byte))
        else:
            chars.append(".")

    text = "".join(chars)
    if len(text) > MAX_TEXT_DISPLAY_CHARS:
        text = text[: MAX_TEXT_DISPLAY_CHARS - 4].rstrip() + " ..."
    elif total_size > len(data):
        text += "..."
    return text


class SegmentDetailPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        detail_style = """
            QPlainTextEdit {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
                padding: 6px;
            }
            """

        self._caption = QLabel("Select a segment to inspect its contents.")
        self._caption.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        binary_label = QLabel("Binary")
        binary_label.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 11px;")
        self._binary_view = QPlainTextEdit()
        self._binary_view.setReadOnly(True)
        self._binary_view.setPlaceholderText("Hex dump appears here.")
        self._binary_view.setStyleSheet(detail_style)
        self._binary_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        text_label = QLabel("Text")
        text_label.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 11px;")
        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setPlaceholderText("Printable text appears here.")
        self._text_view.setStyleSheet(detail_style)
        self._text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._caption)
        layout.addWidget(binary_label)
        layout.addWidget(self._binary_view, stretch=1)
        layout.addWidget(text_label)
        layout.addWidget(self._text_view, stretch=1)

        self.clear()

    def clear(self) -> None:
        self._caption.setText("Select a segment to inspect its contents.")
        self._binary_view.clear()
        self._text_view.clear()

    def show_segment(self, source_path: Path, segment: FileSegment) -> None:
        category = CATEGORY_LABELS.get(segment.category, segment.category.title())
        safety = format_edit_safety_summary(segment)
        self._caption.setText(
            f"{segment.label} | {category} | {safety} | "
            f"{_format_offset(segment.offset)} | {_format_bytes(segment.size)}"
        )

        try:
            data = _read_segment_bytes(source_path, segment)
        except OSError as exc:
            self._binary_view.setPlainText(f"Could not read segment: {exc}")
            self._text_view.clear()
            return

        if not data:
            self._binary_view.setPlainText("(empty segment)")
            self._text_view.setPlainText("(empty segment)")
            return

        self._binary_view.setPlainText(_format_binary(data, segment.size))
        self._text_view.setPlainText(_format_text(data, segment.size))


class MemoryMapCanvas(QWidget):
    segment_hovered = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._layout: FileLayout | None = None
        self._bytes_per_pixel = 4096.0
        self._hovered_segment: FileSegment | None = None
        self.setMinimumHeight(MAP_HEIGHT + 8)
        self.setMouseTracking(True)

    def set_layout(self, layout: FileLayout | None) -> None:
        self._layout = layout
        self._hovered_segment = None
        self._update_geometry()
        self.update()

    def set_bytes_per_pixel(self, value: float) -> None:
        self._bytes_per_pixel = max(MIN_BYTES_PER_PIXEL, min(MAX_BYTES_PER_PIXEL, value))
        self._update_geometry()
        self.update()

    def bytes_per_pixel(self) -> float:
        return self._bytes_per_pixel

    def _content_width(self) -> int:
        if self._layout is None or self._layout.file_size == 0:
            return 1
        return max(1, int(self._layout.file_size / self._bytes_per_pixel))

    def _update_geometry(self) -> None:
        self.setFixedSize(self._content_width(), MAP_HEIGHT + 8)

    def _segment_at_x(self, x: int) -> FileSegment | None:
        if self._layout is None or self._layout.file_size == 0:
            return None

        offset = int(x * self._bytes_per_pixel)
        offset = max(0, min(offset, self._layout.file_size - 1))
        return self._layout.segment_at(offset)

    def _tooltip_for(self, segment: FileSegment) -> str:
        category = CATEGORY_LABELS.get(segment.category, segment.category.title())
        return (
            f"{segment.label}\n"
            f"Category: {category}\n"
            f"{_edit_safety_tooltip(segment)}\n"
            f"Offset: {_format_offset(segment.offset)}\n"
            f"Size: {_format_bytes(segment.size)}\n"
            f"Path: {segment.path_label}"
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        if self._layout is None or not self._layout.segments:
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Drop a file to inspect memory layout")
            return

        y = 4
        height = MAP_HEIGHT
        width = self._content_width()
        scale = width / self._layout.file_size

        for segment in self._layout.segments:
            x = int(segment.offset * scale)
            segment_width = max(1, int(segment.size * scale))
            if x >= width:
                continue
            if x + segment_width > width:
                segment_width = width - x

            color = QColor(CATEGORY_COLORS.get(segment.category, CATEGORY_COLORS["unknown"]))
            if segment is self._hovered_segment:
                color = color.lighter(130)

            painter.fillRect(x, y, segment_width, height, color)

        painter.setPen(QColor("#555555"))
        painter.drawRect(0, y, width - 1, height)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        segment = self._segment_at_x(int(event.position().x()))
        if segment is not self._hovered_segment:
            self._hovered_segment = segment
            self.update()
            self.segment_hovered.emit(segment)
            if segment is not None:
                self.setToolTip(self._tooltip_for(segment))
            else:
                self.setToolTip("")

    def leaveEvent(self, _event) -> None:
        self._hovered_segment = None
        self.update()
        self.segment_hovered.emit(None)
        self.setToolTip("")

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 0.85 if delta > 0 else 1.18
            self.set_bytes_per_pixel(self._bytes_per_pixel * factor)
            event.accept()
            return
        super().wheelEvent(event)


class SegmentListRow(QWidget):
    def __init__(
        self,
        text: str,
        segment: FileSegment,
        color: QColor,
        list_widget: QListWidget,
        item: QListWidgetItem,
    ) -> None:
        super().__init__()
        self._list_widget = list_widget
        self._item = item
        self._segment = segment

        self._label = QLabel(text)
        self._label.setStyleSheet(f"color: {color.name()};")

        self._settings_button = QPushButton("\u2699")
        self._settings_button.setToolTip("Segment settings")
        self._settings_button.setFixedSize(28, 28)
        self._settings_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                font-size: 16px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #3a3a3d;
            }
            """
        )
        self._settings_button.clicked.connect(self._open_settings)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(self._settings_button)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet("background-color: #094771; border-radius: 4px;")
            self._label.setStyleSheet("color: #ffffff;")
        else:
            self.setStyleSheet("")
            color = QColor(CATEGORY_COLORS.get(self._segment.category, CATEGORY_COLORS["unknown"]))
            self._label.setStyleSheet(f"color: {color.lighter(130).name()};")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._list_widget.setCurrentItem(self._item)
        super().mousePressEvent(event)

    def _open_settings(self) -> None:
        dialog = SegmentInfoDialog(self._segment, self.window())
        dialog.exec()


class SegmentListPanel(QWidget):
    segment_selected = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setStyleSheet(
            """
            QListWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 0;
                border-radius: 4px;
            }
            """
        )

        hint = QLabel("Click a segment to inspect its contents.")
        hint.setStyleSheet("color: #777777; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list, stretch=1)
        layout.addWidget(hint)

    def set_layout(self, layout: FileLayout | None) -> None:
        self._list.clear()
        if layout is None:
            return

        total = len(layout.segments)
        number_width = len(str(total))

        for index, segment in enumerate(layout.segments, start=1):
            category = CATEGORY_LABELS.get(segment.category, segment.category.title())
            number = f"{index:>{number_width}}."
            mark = format_edit_safety_mark(segment)
            text = f"{number} {mark} {segment.label}  |  {_format_bytes(segment.size)}  |  {category}"
            color = QColor(CATEGORY_COLORS.get(segment.category, CATEGORY_COLORS["unknown"]))

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, segment)
            item.setToolTip(
                f"Segment {index} of {total}\n"
                f"{segment.path_label}\n"
                f"Offset: {_format_offset(segment.offset)}\n"
                f"Size: {_format_bytes(segment.size)}\n\n"
                f"{_edit_safety_tooltip(segment)}\n\n"
                f"{get_atom_description(segment)[1]}"
            )

            row = SegmentListRow(text, segment, color, self._list, item)
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)

    def _on_selection_changed(self) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            row = self._list.itemWidget(item)
            if isinstance(row, SegmentListRow):
                row.set_selected(item.isSelected())
        self._emit_selection()

    def clear_selection(self) -> None:
        self._list.clearSelection()

    def selected_segment(self) -> FileSegment | None:
        selected_items = self._list.selectedItems()
        if not selected_items:
            return None
        return selected_items[0].data(Qt.ItemDataRole.UserRole)

    def _emit_selection(self) -> None:
        selected_items = self._list.selectedItems()
        if not selected_items:
            self.segment_selected.emit(None)
            return
        self.segment_selected.emit(selected_items[0].data(Qt.ItemDataRole.UserRole))


class MemoryLayoutPanel(QWidget):
    zoom_changed = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()
        self._layout: FileLayout | None = None
        self._source_path: Path | None = None

        title = QLabel("Memory Layout")
        title.setStyleSheet("color: #cccccc; font-weight: bold;")

        self._info_label = QLabel("Drop a file to inspect its memory map.")
        self._info_label.setStyleSheet("color: #aaaaaa;")
        self._info_label.setWordWrap(True)

        self._scale_label = QLabel("1 px = 4.0 KB")
        self._scale_label.setStyleSheet("color: #aaaaaa;")

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(0, 1000)
        self._zoom_slider.setValue(self._slider_value_for_bytes_per_pixel(4096))
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)

        zoom_caption = QLabel("Zoom")
        zoom_caption.setStyleSheet("color: #cccccc;")

        self._canvas = MemoryMapCanvas()
        self._canvas.segment_hovered.connect(self._on_segment_hovered)

        self._segment_list = SegmentListPanel()
        self._segment_list.segment_selected.connect(self._on_segment_selected)

        self._segment_detail = SegmentDetailPanel()

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._canvas)
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(MAP_HEIGHT + 28)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            """
            QScrollArea {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
            }
            """
        )

        legend = self._build_legend()

        map_hint = QLabel("Hover segments on the map. Ctrl + scroll to zoom.")
        map_hint.setStyleSheet("color: #777777; font-size: 11px;")

        self._map_tab = QWidget()
        map_layout = QVBoxLayout(self._map_tab)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.addWidget(legend)
        map_layout.addWidget(self._scroll)
        map_layout.addWidget(zoom_caption)
        map_layout.addWidget(self._zoom_slider)
        map_layout.addWidget(self._scale_label)
        map_layout.addWidget(map_hint)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 14px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #094771;
                color: #ffffff;
            }
            """
        )
        self._tabs.addTab(self._map_tab, "Map")
        self._tabs.addTab(self._segment_list, "List")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(title)
        root.addWidget(self._info_label)
        root.addWidget(self._tabs, stretch=1)
        root.addWidget(self._segment_detail, stretch=2)

    def _build_legend(self) -> QWidget:
        frame = QWidget()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)

        category_row = QHBoxLayout()
        category_row.setContentsMargins(0, 0, 0, 0)
        for category, label in CATEGORY_LABELS.items():
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background-color: {CATEGORY_COLORS[category]}; border: 1px solid #555555; border-radius: 2px;"
            )
            text = QLabel(label)
            text.setStyleSheet("color: #bbbbbb; font-size: 11px;")
            category_row.addWidget(swatch)
            category_row.addWidget(text)
        category_row.addStretch()
        outer.addLayout(category_row)

        safety_row = QHBoxLayout()
        safety_row.setContentsMargins(0, 0, 0, 0)
        safety_caption = QLabel("Edit safety:")
        safety_caption.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        safety_row.addWidget(safety_caption)
        for level, label in EDIT_SAFETY_LABELS.items():
            mark = QLabel(EDIT_SAFETY_MARKS[level])
            mark.setStyleSheet(f"color: {EDIT_SAFETY_COLORS[level]}; font-size: 11px; font-weight: bold;")
            text = QLabel(label)
            text.setStyleSheet("color: #bbbbbb; font-size: 11px;")
            safety_row.addWidget(mark)
            safety_row.addWidget(text)
        safety_row.addStretch()
        outer.addLayout(safety_row)

        return frame

    def _slider_value_for_bytes_per_pixel(self, bpp: float) -> int:
        min_log = math.log(MIN_BYTES_PER_PIXEL)
        max_log = math.log(MAX_BYTES_PER_PIXEL)
        value = (math.log(bpp) - min_log) / (max_log - min_log)
        return int(max(0, min(1000, round(value * 1000))))

    def _bytes_per_pixel_for_slider(self, value: int) -> float:
        min_log = math.log(MIN_BYTES_PER_PIXEL)
        max_log = math.log(MAX_BYTES_PER_PIXEL)
        ratio = value / 1000
        return math.exp(min_log + (max_log - min_log) * ratio)

    def _update_scale_label(self, bpp: float) -> None:
        if bpp < 1024:
            self._scale_label.setText(f"1 px = {bpp:.0f} B")
        elif bpp < 1024 * 1024:
            self._scale_label.setText(f"1 px = {bpp / 1024:.1f} KB")
        else:
            self._scale_label.setText(f"1 px = {bpp / (1024 * 1024):.1f} MB")

    def _on_zoom_changed(self, value: int) -> None:
        bpp = self._bytes_per_pixel_for_slider(value)
        self._canvas.set_bytes_per_pixel(bpp)
        self._update_scale_label(bpp)
        self.zoom_changed.emit(bpp)

    def _on_segment_hovered(self, segment: FileSegment | None) -> None:
        if self._tabs.currentWidget() is not self._map_tab:
            return
        self._present_segment(segment, clear_on_empty=True)

    def _on_segment_selected(self, segment: FileSegment | None) -> None:
        if self._tabs.currentWidget() is not self._segment_list:
            return
        self._present_segment(segment, clear_on_empty=True)

    def _on_tab_changed(self, _index: int) -> None:
        if self._layout is None:
            self._segment_detail.clear()
            return

        if self._tabs.currentWidget() is self._map_tab:
            self._segment_list.clear_selection()
            self._info_label.setText(
                f"File size: {_format_bytes(self._layout.file_size)} | "
                f"Segments: {len(self._layout.segments)}"
            )
            self._segment_detail.clear()
            return

        selected_segment = self._segment_list.selected_segment()
        if selected_segment is not None:
            self._present_segment(selected_segment, clear_on_empty=False)
        else:
            self._info_label.setText(
                f"File size: {_format_bytes(self._layout.file_size)} | "
                f"Segments: {len(self._layout.segments)}"
            )
            self._segment_detail.clear()

    def _present_segment(self, segment: FileSegment | None, clear_on_empty: bool) -> None:
        if self._layout is None:
            return

        if segment is None:
            if clear_on_empty:
                self._info_label.setText(
                    f"File size: {_format_bytes(self._layout.file_size)} | "
                    f"Segments: {len(self._layout.segments)}"
                )
                self._segment_detail.clear()
            return

        category = CATEGORY_LABELS.get(segment.category, segment.category.title())
        safety = format_edit_safety_summary(segment)
        self._info_label.setText(
            f"{segment.label} | {category} | {safety} | "
            f"{_format_offset(segment.offset)} | {_format_bytes(segment.size)}"
        )

        if self._source_path is not None:
            self._segment_detail.show_segment(self._source_path, segment)

    def set_layout(self, layout: FileLayout | None, source_path: Path | None = None) -> None:
        self._layout = layout
        self._source_path = source_path
        self._canvas.set_layout(layout)
        self._segment_list.set_layout(layout)
        self._segment_detail.clear()
        if layout is None:
            self._info_label.setText("Drop a file to inspect its memory map.")
            return

        self._info_label.setText(
            f"File size: {_format_bytes(layout.file_size)} | Segments: {len(layout.segments)}"
        )

    def fit_to_width(self, viewport_width: int) -> None:
        if self._layout is None or self._layout.file_size == 0:
            return
        usable_width = max(1, viewport_width - 8)
        bpp = self._layout.file_size / usable_width
        slider_value = self._slider_value_for_bytes_per_pixel(bpp)
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(slider_value)
        self._zoom_slider.blockSignals(False)
        self._on_zoom_changed(slider_value)

    def fit_to_current_width(self) -> None:
        self.fit_to_width(self._scroll.viewport().width())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._layout is not None and self._tabs.currentWidget() is self._map_tab:
            self.fit_to_current_width()
