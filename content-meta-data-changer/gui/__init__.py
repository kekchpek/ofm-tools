"""GUI entry point for Content Metadata Changer."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from formats.heif_support import register_heif_opener
from gui.common import APP_STYLESHEET
from gui.library_window import MediaLibraryWindow


def run_gui() -> int:
    register_heif_opener()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MediaLibraryWindow()
    window.show()
    return app.exec()
