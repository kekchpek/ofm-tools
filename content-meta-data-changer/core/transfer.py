"""Metadata transfer operations."""

from __future__ import annotations

from pathlib import Path

from core.errors import TransferError, wrap_transfer_error
from metadata_transfer import MetadataTransferError, transfer_metadata


def transfer_metadata_files(target: Path, source: Path, destination: Path) -> Path:
    try:
        return transfer_metadata(target, source, destination)
    except MetadataTransferError as exc:
        raise wrap_transfer_error(exc) from exc
