"""Register HEIF/HEIC support for Pillow."""

from __future__ import annotations

_heif_registered = False


def register_heif_opener() -> None:
    global _heif_registered
    if _heif_registered:
        return
    try:
        from pillow_heif import register_heif_opener as _register

        _register()
        _heif_registered = True
    except ImportError:
        pass


def heif_support_available() -> bool:
    register_heif_opener()
    return _heif_registered
