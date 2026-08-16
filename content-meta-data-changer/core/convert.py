"""Media conversion operations."""

from __future__ import annotations

from pathlib import Path

from conversion import (
    CONVERSION_TARGETS,
    ConversionError as VideoConversionError,
    can_remux,
    convert_video,
    remux_video,
)
from core.errors import ConversionError, wrap_conversion_error
from image_conversion import IMAGE_CONVERSION_TARGETS, ImageConversionError, convert_image


VIDEO_TARGET_KEYS = {target.extension.lstrip("."): target for target in CONVERSION_TARGETS}
IMAGE_TARGET_KEYS = {target.extension.lstrip("."): target for target in IMAGE_CONVERSION_TARGETS}
IMAGE_TARGET_KEYS["jpeg"] = IMAGE_TARGET_KEYS["jpg"]


def convert_video_file(source: Path, destination: Path, target_key: str) -> Path:
    key = target_key.lower().lstrip(".")
    target = VIDEO_TARGET_KEYS.get(key)
    if target is None:
        raise ConversionError(f"Unsupported video conversion target: {target_key}")
    try:
        convert_video(source, destination, target)
    except VideoConversionError as exc:
        raise wrap_conversion_error(exc) from exc
    return destination


def convert_image_file(source: Path, destination: Path, target_key: str) -> Path:
    key = target_key.lower().lstrip(".")
    if key == "jpeg":
        key = "jpg"
    target = IMAGE_TARGET_KEYS.get(key)
    if target is None:
        raise ConversionError(f"Unsupported image conversion target: {target_key}")
    try:
        convert_image(source, destination, target)
    except ImageConversionError as exc:
        raise wrap_conversion_error(exc) from exc
    return destination


def supported_video_targets() -> list[str]:
    return [target.extension.lstrip(".") for target in CONVERSION_TARGETS]


def supported_image_targets() -> list[str]:
    return sorted({target.extension.lstrip(".") for target in IMAGE_CONVERSION_TARGETS} | {"jpeg"})


def rewrap_or_convert_video(source: Path, destination: Path, target_key: str) -> Path:
    """Change a video's container, re-encoding only when unavoidable.

    MP4, M4V and MOV are all ISO base media containers, so their streams can be
    moved across byte-for-byte. That keeps the picture identical — which is the
    whole point when only the container and metadata are meant to change — and
    avoids an libx264 pass that is slow and memory-hungry enough to be killed on
    a small host.
    """
    key = target_key.lower().lstrip(".")
    if can_remux(source, f".{key}"):
        try:
            remux_video(source, destination)
            return destination
        except VideoConversionError:
            # Exotic stream the target container will not accept: fall back to
            # a real re-encode rather than failing outright.
            destination.unlink(missing_ok=True)
    return convert_video_file(source, destination, key)
