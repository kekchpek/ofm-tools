"""Media conversion operations."""

from __future__ import annotations

from pathlib import Path

from conversion import CONVERSION_TARGETS, ConversionError as VideoConversionError, convert_video
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
