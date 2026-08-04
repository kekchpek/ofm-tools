"""Base types for metadata format strategies."""

from abc import ABC, abstractmethod
from pathlib import Path


class UnsupportedFormatError(ValueError):
    """Raised when no format strategy supports the given file."""


class MetadataFormat(ABC):
    extensions: frozenset[str]

    @classmethod
    def supports(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.extensions

    @abstractmethod
    def format_metadata(self, path: Path) -> str:
        """Return human-readable metadata text for the file."""
