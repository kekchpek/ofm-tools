"""Main library window for managing and opening media files."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.common import supported_extension_hint
from gui.metadata_transfer_window import MetadataTransferWindow
from gui.editor_window import MediaEditorWindow
from metadata import supported_extensions

ROW_BUTTON_STYLE = """
QPushButton {
    background-color: #2d2d30;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 0px;
}
QPushButton:hover {
    background-color: #3a3a3d;
}
"""


class MediaFileRow(QWidget):
    transfer_requested = pyqtSignal(Path)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path.resolve()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        name_label = QLabel(path.name)
        name_label.setStyleSheet("color: #d4d4d4;")
        layout.addWidget(name_label, stretch=1)

        transfer_button = QPushButton("Transfer Metadata")
        transfer_button.setStyleSheet(ROW_BUTTON_STYLE)
        transfer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        transfer_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        transfer_button.clicked.connect(self._emit_transfer)
        layout.addWidget(transfer_button)
        self.transfer_button = transfer_button

    @property
    def path(self) -> Path:
        return self._path

    def _emit_transfer(self) -> None:
        self.transfer_requested.emit(self._path)


class MediaFileList(QListWidget):
    """File list that accepts drag-and-drop to add media files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(2)
        self.setStyleSheet(
            """
            QListWidget::item {
                padding: 0px;
                margin: 2px 4px;
            }
            """
        )
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                item = self.itemAt(event.pos())
                if item is not None:
                    row = self.itemWidget(item)
                    if isinstance(row, MediaFileRow):
                        local_pos = row.mapFrom(self.viewport(), event.pos())
                        button = row.transfer_button
                        if button.geometry().contains(local_pos):
                            button.click()
                            return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._paths_from_mime(event)
        if paths:
            window = self.window()
            if isinstance(window, MediaLibraryWindow):
                window.add_files(paths)
            event.acceptProposedAction()
            return

        QMessageBox.warning(
            self,
            "Unsupported file",
            f"Please drop supported video files ({supported_extension_hint()}).",
        )

    @staticmethod
    def _paths_from_mime(event: QDropEvent) -> list[Path]:
        paths: list[Path] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in supported_extensions():
                paths.append(path)
        return paths


class MediaLibraryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Content Metadata Changer")
        self.resize(720, 520)
        self.setMinimumSize(480, 360)

        self._known_paths: set[str] = set()
        self._editors: dict[str, MediaEditorWindow] = {}
        self._transfer_windows: dict[str, MetadataTransferWindow] = {}

        header = QLabel("Media files")
        header.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 14px;")

        hint = QLabel(f"Add files with the button below or drag them here.\nSupported: {supported_extension_hint()}")
        hint.setStyleSheet("color: #888888;")
        hint.setWordWrap(True)

        self.file_list = MediaFileList()
        self.file_list.itemDoubleClicked.connect(self._open_double_clicked_file)

        self._add_button = QPushButton("Add Files…")
        self._add_button.clicked.connect(self._browse_files)

        self._open_button = QPushButton("Open")
        self._open_button.clicked.connect(self._open_selected_file)
        self._open_button.setEnabled(False)

        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._remove_selected_files)
        self._remove_button.setEnabled(False)

        button_row = QHBoxLayout()
        button_row.addWidget(self._add_button)
        button_row.addWidget(self._open_button)
        button_row.addWidget(self._remove_button)
        button_row.addStretch()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(header)
        layout.addWidget(hint)
        layout.addWidget(self.file_list, stretch=1)
        layout.addLayout(button_row)
        self.setCentralWidget(container)

        self.file_list.itemSelectionChanged.connect(self._update_buttons)
        self.statusBar().showMessage("Add media files to begin.")

    def add_files(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        unsupported = 0

        for path in paths:
            if path.suffix.lower() not in supported_extensions():
                unsupported += 1
                continue

            resolved = str(path.resolve())
            if resolved in self._known_paths:
                skipped += 1
                continue

            item, row = self._create_list_row(path)
            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, row)
            self._update_row_size_hint(item, row)
            self._known_paths.add(resolved)
            added += 1

        if added:
            self.file_list.setCurrentRow(self.file_list.count() - 1)

        messages: list[str] = []
        if added:
            messages.append(f"Added {added} file{'s' if added != 1 else ''}.")
        if skipped:
            messages.append(f"Skipped {skipped} duplicate{'s' if skipped != 1 else ''}.")
        if unsupported:
            messages.append(f"Ignored {unsupported} unsupported file{'s' if unsupported != 1 else ''}.")
        if messages:
            self.statusBar().showMessage(" ".join(messages), 5000)

        self._update_buttons()

    def _create_list_row(self, path: Path) -> tuple[QListWidgetItem, MediaFileRow]:
        resolved = str(path.resolve())

        item = QListWidgetItem()
        item.setToolTip(resolved)
        item.setData(Qt.ItemDataRole.UserRole, resolved)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        row = MediaFileRow(path)
        row.transfer_requested.connect(self._open_metadata_transfer)
        return item, row

    def _update_row_size_hint(self, item: QListWidgetItem, row: MediaFileRow) -> None:
        row.adjustSize()
        height = max(row.sizeHint().height(), row.minimumSizeHint().height(), 44)
        width = max(self.file_list.viewport().width() - 12, 200)
        item.setSizeHint(QSize(width, height))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            row = self.file_list.itemWidget(item)
            if isinstance(row, MediaFileRow):
                self._update_row_size_hint(item, row)

    def _library_paths(self) -> list[Path]:
        paths: list[Path] = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            raw = item.data(Qt.ItemDataRole.UserRole)
            if raw:
                paths.append(Path(str(raw)))
        return paths

    def _open_metadata_transfer(self, target_path: Path) -> None:
        resolved = str(target_path.resolve())
        existing = self._transfer_windows.get(resolved)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return

        window = MetadataTransferWindow(
            target_path,
            self._library_paths(),
            parent=None,
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.destroyed.connect(lambda *_args, key=resolved: self._transfer_windows.pop(key, None))
        self._transfer_windows[resolved] = window
        window.show()
        window.raise_()
        window.activateWindow()

    def _browse_files(self) -> None:
        extensions = " ".join(f"*{ext}" for ext in sorted(supported_extensions()))
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Add media files",
            "",
            f"Video files ({extensions});;All files (*)",
        )
        if selected:
            self.add_files([Path(path) for path in selected])

    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self.file_list.selectedItems():
            raw = item.data(Qt.ItemDataRole.UserRole)
            if raw:
                paths.append(Path(str(raw)))
        return paths

    def _open_double_clicked_file(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.open_editor(Path(str(raw)))

    def _open_selected_file(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "No file selected", "Select a file from the list to open.")
            return

        for path in paths:
            self.open_editor(path)

    def open_editor(self, path: Path) -> None:
        resolved = str(path.resolve())
        existing = self._editors.get(resolved)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return

        editor = MediaEditorWindow(path, parent=None)
        editor.closed.connect(lambda key=resolved: self._editors.pop(key, None))
        self._editors[resolved] = editor
        editor.show()

    def _remove_selected_files(self) -> None:
        for item in self.file_list.selectedItems():
            raw = item.data(Qt.ItemDataRole.UserRole)
            if raw:
                self._known_paths.discard(str(raw))
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

        self._update_buttons()
        count = self.file_list.count()
        self.statusBar().showMessage(
            f"{count} file{'s' if count != 1 else ''} in library.",
            3000,
        )

    def _update_buttons(self) -> None:
        has_selection = bool(self.file_list.selectedItems())
        self._open_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)
