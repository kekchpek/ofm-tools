"""Shared helpers for JPEG and PNG metadata output."""

from __future__ import annotations

from pathlib import Path

from formats.heif_support import register_heif_opener
from PIL import ExifTags, Image


def _open_image(path: Path) -> Image.Image:
    register_heif_opener()
    return Image.open(path)

def _format_exif_value(tag_name: str, value) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace").rstrip("\x00")
        except Exception:
            return value.hex()
    if isinstance(value, tuple):
        return ", ".join(_format_exif_value(tag_name, item) for item in value)
    return str(value)


def _gps_tag_id(name: str) -> int | None:
    for tag_id, tag_name in ExifTags.GPSTAGS.items():
        if tag_name == name:
            return tag_id
    return None


def _gps_value(gps_ifd: dict, name: str):
    tag_id = _gps_tag_id(name)
    if tag_id is None:
        return None
    return gps_ifd.get(tag_id)


def _format_gps_coordinates(gps_ifd: dict) -> list[str]:
    lines: list[str] = []

    def _dms_to_decimal(values, ref) -> float | None:
        if not values or ref is None:
            return None
        try:
            degrees = values[0][0] / values[0][1]
            minutes = values[1][0] / values[1][1]
            seconds = values[2][0] / values[2][1]
        except (IndexError, TypeError, ZeroDivisionError):
            return None
        decimal = degrees + minutes / 60 + seconds / 3600
        ref_text = ref.decode() if isinstance(ref, bytes) else str(ref)
        if ref_text.upper() in {"S", "W"}:
            decimal *= -1
        return decimal

    lat = _dms_to_decimal(
        _gps_value(gps_ifd, "GPSLatitude"),
        _gps_value(gps_ifd, "GPSLatitudeRef"),
    )
    lon = _dms_to_decimal(
        _gps_value(gps_ifd, "GPSLongitude"),
        _gps_value(gps_ifd, "GPSLongitudeRef"),
    )
    if lat is not None:
        lines.append(f"GPS latitude: {lat:.6f}")
    if lon is not None:
        lines.append(f"GPS longitude: {lon:.6f}")
    altitude = _gps_value(gps_ifd, "GPSAltitude")
    if altitude is not None:
        try:
            alt = altitude[0] / altitude[1]
            ref = _gps_value(gps_ifd, "GPSAltitudeRef") or 0
            if ref == 1:
                alt *= -1
            lines.append(f"GPS altitude: {alt:.2f} m")
        except (TypeError, ZeroDivisionError):
            pass
    return lines


def _format_exif_section(image: Image.Image) -> list[str]:
    exif = image.getexif()
    if not exif:
        return []

    lines = ["", "--- EXIF ---"]
    for tag_id, value in exif.items():
        if tag_id == ExifTags.IFD.GPSInfo:
            continue
        tag_name = ExifTags.TAGS.get(tag_id, f"Tag {tag_id}")
        lines.append(f"{tag_name}: {_format_exif_value(tag_name, value)}")

    try:
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except (KeyError, AttributeError):
        gps_ifd = {}

    if gps_ifd:
        lines.append("")
        lines.append("--- GPS ---")
        for tag_id, value in gps_ifd.items():
            tag_name = ExifTags.GPSTAGS.get(tag_id, f"GPS tag {tag_id}")
            lines.append(f"{tag_name}: {_format_exif_value(tag_name, value)}")
        for line in _format_gps_coordinates(gps_ifd):
            lines.append(line)

    return lines


def _format_png_text_section(info: dict) -> list[str]:
    skip = {"exif", "icc_profile", "icc_profile_name", "gamma", "dpi", "aspect", "transparency"}
    text_items = {key: value for key, value in info.items() if key not in skip and isinstance(value, str)}
    if not text_items:
        return []

    lines = ["", "--- PNG text metadata ---"]
    for key in sorted(text_items):
        lines.append(f"{key}: {text_items[key]}")
    return lines


def format_image_metadata(path: Path, format_label: str) -> str:
    stat = path.stat()
    lines = [
        f"File: {path.name}",
        f"Path: {path.resolve()}",
        f"Format: {format_label}",
        f"Size: {stat.st_size:,} bytes",
        "",
        "--- Image info ---",
    ]

    with _open_image(path) as image:
        lines.append(f"Dimensions: {image.width} x {image.height}")
        lines.append(f"Color mode: {image.mode}")
        if image.format:
            lines.append(f"Encoder format: {image.format}")

        dpi = image.info.get("dpi")
        if dpi:
            lines.append(f"DPI: {dpi[0]:.1f} x {dpi[1]:.1f}")

        lines.extend(_format_exif_section(image))
        if format_label == "PNG":
            lines.extend(_format_png_text_section(image.info))

    return "\n".join(lines)
