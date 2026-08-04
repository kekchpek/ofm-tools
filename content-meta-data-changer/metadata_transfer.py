"""Copy metadata from one media file onto another."""

from __future__ import annotations

from pathlib import Path

from mutagen.mp4 import MP4
from formats.heif_support import register_heif_opener
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from layout.atom_graft import write_metadata_graft
from media_types import is_image_path, is_video_path
from metadata import supported_extensions


class MetadataTransferError(RuntimeError):
    """Raised when metadata transfer fails."""


def _ensure_supported(path: Path, role: str) -> None:
    if not path.is_file():
        raise MetadataTransferError(f"{role} file does not exist: {path}")
    if path.suffix.lower() not in supported_extensions():
        extensions = ", ".join(sorted(supported_extensions()))
        raise MetadataTransferError(
            f"{role} file type is not supported ({path.suffix or 'no extension'}). "
            f"Supported: {extensions}"
        )


def _copy_mutagen_tags(source: Path, destination: Path) -> None:
    source_media = MP4(source)
    if not source_media.tags:
        return

    destination_media = MP4(destination)
    if destination_media.tags is None:
        destination_media.add_tags()
    else:
        destination_media.tags.clear()

    for key, value in source_media.tags.items():
        destination_media.tags[key] = value

    destination_media.save()


def _save_format_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "JPEG"
    if suffix == ".png":
        return "PNG"
    if suffix in {".heic", ".heif"}:
        return "HEIF"
    raise MetadataTransferError(f"Unsupported image format: {path.suffix}")


def _transfer_image_metadata(target: Path, source: Path, destination: Path) -> None:
    register_heif_opener()
    with Image.open(source) as source_image:
        exif = source_image.getexif()
        png_info: PngInfo | None = None
        if source.suffix.lower() == ".png":
            png_info = PngInfo()
            for key, value in source_image.info.items():
                if isinstance(value, str):
                    png_info.add_text(key, value)

    with Image.open(target) as target_image:
        save_format = _save_format_for_path(destination)
        save_kwargs: dict = {}
        if exif:
            save_kwargs["exif"] = exif
        if save_format == "PNG" and png_info is not None:
            save_kwargs["pnginfo"] = png_info
        if save_format == "JPEG":
            save_kwargs["quality"] = 95
            save_kwargs["subsampling"] = 0
        if save_format == "HEIF":
            save_kwargs["quality"] = 90
        target_image.save(destination, format=save_format, **save_kwargs)


def transfer_metadata(
    target: Path,
    source: Path,
    destination: Path,
) -> Path:
    """Write a new file with media from target and metadata from source."""
    target = target.resolve()
    source = source.resolve()
    destination = destination.resolve()

    _ensure_supported(target, "Target")
    _ensure_supported(source, "Metadata source")

    if target == source:
        raise MetadataTransferError("Target and metadata source must be different files.")

    if destination == target or destination == source:
        raise MetadataTransferError("Destination must differ from both input files.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    target_is_video = is_video_path(target)
    source_is_video = is_video_path(source)
    target_is_image = is_image_path(target)
    source_is_image = is_image_path(source)

    if target_is_video != source_is_video or target_is_image != source_is_image:
        raise MetadataTransferError(
            "Target and metadata source must both be videos or both be images."
        )

    try:
        if target_is_video:
            write_metadata_graft(source, target, destination)
            _copy_mutagen_tags(source, destination)
        else:
            _transfer_image_metadata(target, source, destination)
    except MetadataTransferError:
        raise
    except ValueError as exc:
        raise MetadataTransferError(str(exc)) from exc
    except OSError as exc:
        raise MetadataTransferError(f"Could not write output file: {exc}") from exc
    except Exception as exc:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise MetadataTransferError(f"Could not apply metadata: {exc}") from exc

    if not destination.is_file():
        raise MetadataTransferError("Metadata transfer finished without creating an output file.")

    return destination
