"""Dialog showing segment atom description."""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from layout.atom_database import get_atom_description
from layout.base import FileSegment, CATEGORY_LABELS
from layout.edit_safety import EDIT_SAFETY_COLORS, get_edit_safety


class SegmentInfoDialog(QDialog):
    def __init__(self, segment: FileSegment, parent=None) -> None:
        super().__init__(parent)
        atom_key, description = get_atom_description(segment)
        category = CATEGORY_LABELS.get(segment.category, segment.category.title())
        safety = get_edit_safety(segment)

        self.setWindowTitle(f"Segment Settings — {segment.label}")
        self.resize(520, 360)

        title = QLabel(f"{segment.label}")
        title.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")

        subtitle = QLabel(f"Atom: {atom_key!r}  |  Category: {category}")
        subtitle.setStyleSheet("color: #aaaaaa;")

        path_label = QLabel(segment.path_label)
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color: #888888; font-size: 11px;")

        safety_label = QLabel(f"{safety.label}: {safety.reason}")
        safety_label.setWordWrap(True)
        safety_label.setStyleSheet(
            f"color: {EDIT_SAFETY_COLORS[safety.level]}; font-size: 12px;"
        )

        heading = QLabel("Description")
        heading.setStyleSheet("color: #cccccc; font-weight: bold;")

        self._description_view = QPlainTextEdit()
        self._description_view.setReadOnly(True)
        self._description_view.setPlainText(description)
        self._description_view.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }
            """
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(path_label)
        layout.addWidget(safety_label)
        layout.addWidget(heading)
        layout.addWidget(self._description_view, stretch=1)
        layout.addWidget(buttons)

        self.setStyleSheet("background-color: #1e1e1e;")
