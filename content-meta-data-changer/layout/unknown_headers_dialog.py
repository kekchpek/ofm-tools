"""Dialogs listing unknown atom headers and memory segments."""

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class _ReadOnlyTextDialog(QDialog):
    def __init__(
        self,
        title: str,
        caption: str,
        text: str,
        placeholder: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 360)

        caption_label = QLabel(caption)
        caption_label.setWordWrap(True)
        caption_label.setStyleSheet("color: #aaaaaa;")

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setPlainText(text)
        self._text_view.setPlaceholderText(placeholder)
        self._text_view.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 8px;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
            }
            """
        )

        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self._copy_text)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)

        buttons = QDialogButtonBox()
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)

        layout = QVBoxLayout(self)
        layout.addWidget(caption_label)
        layout.addWidget(self._text_view, stretch=1)
        layout.addWidget(buttons)

        self.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")

    def _copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self._text_view.toPlainText())


class UnknownHeadersDialog(_ReadOnlyTextDialog):
    def __init__(self, headers_text: str, parent=None) -> None:
        super().__init__(
            "Unknown Headers",
            "These atom headers from the loaded file are not in the descriptions database.",
            headers_text,
            "No unknown headers found.",
            parent,
        )


class UnknownMemoryDialog(_ReadOnlyTextDialog):
    def __init__(self, memory_text: str, parent=None) -> None:
        super().__init__(
            "Unknown Memory",
            "These memory layout segments are classified as Unknown in the memory list.",
            memory_text,
            "No unknown memory segments found.",
            parent,
        )
