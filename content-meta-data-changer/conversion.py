"""Video conversion via FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ConversionError(RuntimeError):
    """Raised when FFmpeg conversion fails."""


@dataclass(frozen=True)
class ConversionTarget:
    label: str
    extension: str
    file_filter: str
    ffmpeg_args: tuple[str, ...]


CONVERSION_TARGETS: tuple[ConversionTarget, ...] = (
    ConversionTarget(
        label="Convert to MP4",
        extension=".mp4",
        file_filter="MP4 Video (*.mp4)",
        ffmpeg_args=("-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"),
    ),
    ConversionTarget(
        label="Convert to MOV",
        extension=".mov",
        file_filter="QuickTime Video (*.mov)",
        ffmpeg_args=("-c:v", "libx264", "-c:a", "aac"),
    ),
    ConversionTarget(
        label="Convert to MKV",
        extension=".mkv",
        file_filter="Matroska Video (*.mkv)",
        ffmpeg_args=("-c:v", "libx264", "-c:a", "aac"),
    ),
    ConversionTarget(
        label="Convert to WebM",
        extension=".webm",
        file_filter="WebM Video (*.webm)",
        ffmpeg_args=("-c:v", "libvpx-vp9", "-c:a", "libopus"),
    ),
)


def find_ffmpeg() -> Path | None:
    ffmpeg_path = shutil.which("ffmpeg")
    return Path(ffmpeg_path) if ffmpeg_path else None


def ensure_output_path(path: Path, extension: str) -> Path:
    if path.suffix.lower() != extension:
        return path.with_suffix(extension)
    return path


def convert_video(
    source: Path,
    destination: Path,
    target: ConversionTarget,
    ffmpeg: Path | None = None,
) -> None:
    ffmpeg_path = ffmpeg or find_ffmpeg()
    if ffmpeg_path is None:
        raise ConversionError("FFmpeg was not found. Install it with: brew install ffmpeg")

    destination = ensure_output_path(destination, target.extension)
    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        *target.ffmpeg_args,
        str(destination),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "Unknown FFmpeg error").strip()
        raise ConversionError(details) from exc

    if not destination.is_file():
        raise ConversionError("FFmpeg finished without creating an output file.")
