"""Unified domain exceptions."""

from __future__ import annotations

from conversion import ConversionError as _VideoConversionError
from formats.base import UnsupportedFormatError
from image_conversion import ImageConversionError as _ImageConversionError
from layout.base import LayoutParseError, UnsupportedLayoutError
from metadata_transfer import MetadataTransferError
from video_preview import VideoPreviewError


class CoreError(Exception):
    """Base error for domain operations."""


class UnsupportedMediaError(CoreError, UnsupportedFormatError):
    """Raised when a file format is not supported."""


class LayoutError(CoreError):
    """Raised when layout parsing fails."""


class TransferError(CoreError):
    """Raised when metadata transfer fails."""


class ConversionError(CoreError):
    """Raised when media conversion fails."""


class PreviewError(CoreError):
    """Raised when embedded preview update fails."""


def wrap_layout_error(exc: Exception) -> LayoutError:
    return LayoutError(str(exc))


def wrap_transfer_error(exc: Exception) -> TransferError:
    return TransferError(str(exc))


def wrap_conversion_error(exc: Exception) -> ConversionError:
    return ConversionError(str(exc))


def wrap_preview_error(exc: Exception) -> PreviewError:
    return PreviewError(str(exc))


def is_layout_error(exc: Exception) -> bool:
    return isinstance(exc, (LayoutParseError, UnsupportedLayoutError, LayoutError))


def is_unsupported_media(exc: Exception) -> bool:
    return isinstance(exc, (UnsupportedFormatError, UnsupportedMediaError))


def is_transfer_error(exc: Exception) -> bool:
    return isinstance(exc, (MetadataTransferError, TransferError))


def is_conversion_error(exc: Exception) -> bool:
    return isinstance(exc, (_VideoConversionError, _ImageConversionError, ConversionError))


def is_preview_error(exc: Exception) -> bool:
    return isinstance(exc, (VideoPreviewError, PreviewError))
