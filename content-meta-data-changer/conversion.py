"""Video conversion via FFmpeg."""

from __future__ import annotations

import shutil
import signal
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
        "-nostdin",
        # "error" alone frequently produces no output at all, which used to
        # surface as a bare "Unknown FFmpeg error" with nothing to act on.
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(source),
        *target.ffmpeg_args,
        str(destination),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ConversionError(
            describe_ffmpeg_failure(
                returncode=exc.returncode,
                stderr=exc.stderr,
                stdout=exc.stdout,
                source=source,
                target_label=target.extension.lstrip("."),
            )
        ) from exc

    if not destination.is_file():
        raise ConversionError("FFmpeg finished without creating an output file.")


def describe_ffmpeg_failure(
    *,
    returncode: int,
    stderr: str | None,
    stdout: str | None,
    source: Path,
    target_label: str,
) -> str:
    """Turn an FFmpeg failure into something a user can act on.

    A negative return code means the process was killed by a signal rather than
    exiting on its own. On a container that is almost always the out-of-memory
    killer, and it leaves stderr empty — the case that used to read only as
    "Unknown FFmpeg error".
    """
    output = (stderr or stdout or "").strip()
    size_mb = source.stat().st_size / 1_048_576 if source.is_file() else 0

    if returncode < 0:
        signal_number = -returncode
        signal_name = signal.Signals(signal_number).name if signal_number in {
            member.value for member in signal.Signals
        } else f"signal {signal_number}"
        reason = (
            f"FFmpeg was killed by {signal_name} while converting "
            f"{source.name} ({size_mb:.0f} MB) to {target_label}."
        )
        if signal_name == "SIGKILL":
            reason += (
                " On a hosted container this normally means it ran out of memory — "
                "try a smaller file, or give the service more memory."
            )
        return f"{reason} {output}".strip()

    detail = output or "FFmpeg produced no error output."
    return (
        f"FFmpeg exited with code {returncode} converting {source.name} "
        f"({size_mb:.0f} MB) to {target_label}. {detail}"
    )


#: Containers that share the ISO base media format, so H.264/AAC streams can be
#: moved between them byte-for-byte instead of being re-encoded.
REMUXABLE_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov"})


def can_remux(source: Path, destination_extension: str) -> bool:
    return (
        source.suffix.lower() in REMUXABLE_EXTENSIONS
        and destination_extension.lower() in REMUXABLE_EXTENSIONS
    )


def remux_video(source: Path, destination: Path, ffmpeg: Path | None = None) -> None:
    """Rewrap the existing streams into another container without re-encoding.

    Far cheaper than a re-encode — no quality loss, seconds instead of minutes,
    and a fraction of the memory, which matters on a small container where
    libx264 can be killed by the OOM killer.
    """
    ffmpeg_path = ffmpeg or find_ffmpeg()
    if ffmpeg_path is None:
        raise ConversionError("FFmpeg was not found. Install it with: brew install ffmpeg")

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(source),
        "-c",
        "copy",
        # Deliberately no +faststart: it moves `moov` ahead of `mdat`, and the
        # atom graft that runs afterwards mis-reads that layout and emits a file
        # with invalid NAL sizes. Keep the streams where the graft expects them.
        str(destination),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ConversionError(
            describe_ffmpeg_failure(
                returncode=exc.returncode,
                stderr=exc.stderr,
                stdout=exc.stdout,
                source=source,
                target_label=destination.suffix.lstrip("."),
            )
        ) from exc

    if not destination.is_file():
        raise ConversionError("FFmpeg finished without creating an output file.")
