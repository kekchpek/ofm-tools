"""Extract video and audio quality info from QuickTime/MP4 atoms."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

CONTAINER_BOXES = frozenset({b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"})

CODEC_LABELS = {
    "avc1": "H.264/AVC",
    "avc3": "H.264/AVC",
    "hvc1": "HEVC/H.265",
    "hev1": "HEVC/H.265",
    "mp4v": "MPEG-4 Visual",
    "ap4h": "ProRes 4444",
    "apcn": "ProRes 422",
    "apch": "ProRes 422 HQ",
    "apcs": "ProRes 422 LT",
    "apco": "ProRes 422 Proxy",
    "mp4a": "AAC",
    "alac": "Apple Lossless",
    "ac-3": "AC-3",
    "ec-3": "E-AC-3",
}


@dataclass(frozen=True)
class VideoStreamInfo:
    track_number: int
    codec: str
    codec_label: str
    width: int
    height: int
    frame_rate: float | None
    bitrate_bps: int | None


@dataclass(frozen=True)
class AudioStreamInfo:
    track_number: int
    codec: str
    codec_label: str
    sample_rate: int
    channels: int
    bitrate_bps: int | None


@dataclass(frozen=True)
class MediaQualityInfo:
    video_streams: tuple[VideoStreamInfo, ...]
    audio_streams: tuple[AudioStreamInfo, ...]


def _format_bitrate(bps: int | None) -> str | None:
    if bps is None or bps <= 0:
        return None
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{bps / 1_000:.0f} kbps"


def _codec_label(fourcc: str) -> str:
    return CODEC_LABELS.get(fourcc, fourcc.upper())


def _read_box_header(data: bytes, offset: int, end: int) -> tuple[int, bytes, int, int] | None:
    if offset + 8 > end:
        return None

    size32 = struct.unpack_from(">I", data, offset)[0]
    box_type = data[offset + 4 : offset + 8]
    header_size = 8

    if size32 == 1:
        if offset + 16 > end:
            return None
        size = struct.unpack_from(">Q", data, offset + 8)[0]
        header_size = 16
    elif size32 == 0:
        size = end - offset
    else:
        size = size32

    if size < header_size:
        return None

    box_end = min(offset + size, end)
    return offset, box_type, header_size, box_end


def _iter_boxes(data: bytes, start: int, end: int):
    offset = start
    while offset < end:
        header = _read_box_header(data, offset, end)
        if header is None:
            break
        box_start, box_type, _header_size, box_end = header
        yield box_start, box_end, box_type
        offset = box_end


def _find_boxes(data: bytes, start: int, end: int, box_type: bytes) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []

    for box_start, box_end, current_type in _iter_boxes(data, start, end):
        if current_type == box_type:
            matches.append((box_start, box_end))
        if current_type in CONTAINER_BOXES:
            matches.extend(_find_boxes(data, box_start + 8, box_end, box_type))

    return matches


def _find_first_box(data: bytes, start: int, end: int, box_type: bytes) -> tuple[int, int] | None:
    matches = _find_boxes(data, start, end, box_type)
    return matches[0] if matches else None


def _read_handler_type(data: bytes, trak_start: int, trak_end: int) -> str | None:
    hdlr = _find_first_box(data, trak_start + 8, trak_end, b"hdlr")
    if hdlr is None or hdlr[0] + 20 > hdlr[1]:
        return None
    return data[hdlr[0] + 16 : hdlr[0] + 20].decode("latin-1", errors="replace")


def _read_tkhd_dimensions(data: bytes, trak_start: int, trak_end: int) -> tuple[int, int] | None:
    tkhd = _find_first_box(data, trak_start + 8, trak_end, b"tkhd")
    if tkhd is None:
        return None

    box_start, box_end = tkhd
    if box_start + 92 > box_end:
        return None

    version = data[box_start + 8]
    if version == 0:
        width = struct.unpack_from(">I", data, box_start + 84)[0] / 65536
        height = struct.unpack_from(">I", data, box_start + 88)[0] / 65536
    else:
        width = struct.unpack_from(">I", data, box_start + 96)[0] / 65536
        height = struct.unpack_from(">I", data, box_start + 100)[0] / 65536

    return int(round(width)), int(round(height))


def _read_mdhd(data: bytes, trak_start: int, trak_end: int) -> tuple[int, int] | None:
    mdhd = _find_first_box(data, trak_start + 8, trak_end, b"mdhd")
    if mdhd is None:
        return None

    box_start, box_end = mdhd
    version = data[box_start + 8]
    if version == 0:
        if box_start + 28 > box_end:
            return None
        timescale = struct.unpack_from(">I", data, box_start + 20)[0]
        duration = struct.unpack_from(">I", data, box_start + 24)[0]
    else:
        if box_start + 36 > box_end:
            return None
        timescale = struct.unpack_from(">I", data, box_start + 28)[0]
        duration = struct.unpack_from(">Q", data, box_start + 32)[0]

    if timescale <= 0:
        return None
    return timescale, duration


def _read_stts_frame_rate(data: bytes, trak_start: int, trak_end: int, timescale: int) -> float | None:
    stts = _find_first_box(data, trak_start + 8, trak_end, b"stts")
    if stts is None:
        return None

    box_start, box_end = stts
    if box_start + 16 > box_end:
        return None

    entry_count = struct.unpack_from(">I", data, box_start + 12)[0]
    if entry_count <= 0:
        return None

    offset = box_start + 16
    total_samples = 0
    total_ticks = 0

    for _ in range(entry_count):
        if offset + 8 > box_end:
            break
        sample_count, sample_delta = struct.unpack_from(">II", data, offset)
        total_samples += sample_count
        total_ticks += sample_count * sample_delta
        offset += 8

    if total_samples <= 0 or total_ticks <= 0:
        return None

    return total_samples * timescale / total_ticks


def _read_stsd_entry(data: bytes, trak_start: int, trak_end: int) -> tuple[str, int, int] | None:
    stsd = _find_first_box(data, trak_start + 8, trak_end, b"stsd")
    if stsd is None:
        return None

    box_start, box_end = stsd
    if box_start + 24 > box_end:
        return None

    entry_count = struct.unpack_from(">I", data, box_start + 12)[0]
    if entry_count <= 0:
        return None

    entry_start = box_start + 16
    if entry_start + 36 > box_end:
        return None

    entry_size = struct.unpack_from(">I", data, entry_start)[0]
    codec = data[entry_start + 4 : entry_start + 8].decode("latin-1", errors="replace")
    width, height = struct.unpack_from(">HH", data, entry_start + 32)
    if entry_size < 8 or entry_start + entry_size > box_end:
        return codec.strip(), width, height
    return codec.strip(), width, height


def _read_audio_sample_entry(data: bytes, trak_start: int, trak_end: int) -> tuple[str, int, int] | None:
    stsd = _find_first_box(data, trak_start + 8, trak_end, b"stsd")
    if stsd is None:
        return None

    box_start, box_end = stsd
    if box_start + 28 > box_end:
        return None

    entry_start = box_start + 16
    if entry_start + 36 > box_end:
        return None

    codec = data[entry_start + 4 : entry_start + 8].decode("latin-1", errors="replace")
    channels = struct.unpack_from(">H", data, entry_start + 24)[0]
    sample_rate = struct.unpack_from(">I", data, entry_start + 32)[0] / 65536
    return codec.strip(), int(sample_rate), channels


def _read_stsz_total_bytes(data: bytes, trak_start: int, trak_end: int) -> int | None:
    stsz = _find_first_box(data, trak_start + 8, trak_end, b"stsz")
    if stsz is None:
        return None

    box_start, box_end = stsz
    if box_start + 20 > box_end:
        return None

    sample_size, sample_count = struct.unpack_from(">II", data, box_start + 12)
    if sample_count <= 0:
        return None

    if sample_size != 0:
        return sample_size * sample_count

    offset = box_start + 20
    total = 0
    for _ in range(sample_count):
        if offset + 4 > box_end:
            break
        total += struct.unpack_from(">I", data, offset)[0]
        offset += 4
    return total


def _estimate_bitrate(total_bytes: int | None, timescale: int, duration: int) -> int | None:
    if total_bytes is None or duration <= 0 or timescale <= 0:
        return None
    seconds = duration / timescale
    if seconds <= 0:
        return None
    return int((total_bytes * 8) / seconds)


def extract_media_quality(path: Path) -> MediaQualityInfo | None:
    data = path.read_bytes()
    moov = _find_first_box(data, 0, len(data), b"moov")
    if moov is None:
        return None

    video_streams: list[VideoStreamInfo] = []
    audio_streams: list[AudioStreamInfo] = []
    video_index = 0
    audio_index = 0

    for trak_start, trak_end in (
        (start, end)
        for start, end, box_type in _iter_boxes(data, moov[0] + 8, moov[1])
        if box_type == b"trak"
    ):
        handler = _read_handler_type(data, trak_start, trak_end)
        mdhd = _read_mdhd(data, trak_start, trak_end)
        total_bytes = _read_stsz_total_bytes(data, trak_start, trak_end)
        bitrate = None
        if mdhd is not None:
            bitrate = _estimate_bitrate(total_bytes, mdhd[0], mdhd[1])

        if handler == "vide":
            video_index += 1
            dimensions = _read_tkhd_dimensions(data, trak_start, trak_end)
            stsd = _read_stsd_entry(data, trak_start, trak_end)
            frame_rate = _read_stts_frame_rate(data, trak_start, trak_end, mdhd[0]) if mdhd else None

            if stsd is not None:
                codec, width, height = stsd
            else:
                codec, width, height = "????", 0, 0

            if dimensions is not None:
                width, height = dimensions
            elif width <= 0 or height <= 0:
                continue

            video_streams.append(
                VideoStreamInfo(
                    track_number=video_index,
                    codec=codec,
                    codec_label=_codec_label(codec),
                    width=width,
                    height=height,
                    frame_rate=frame_rate,
                    bitrate_bps=bitrate,
                )
            )
        elif handler == "soun":
            audio_index += 1
            sample = _read_audio_sample_entry(data, trak_start, trak_end)
            if sample is None:
                continue
            codec, sample_rate, channels = sample
            audio_streams.append(
                AudioStreamInfo(
                    track_number=audio_index,
                    codec=codec,
                    codec_label=_codec_label(codec),
                    sample_rate=sample_rate,
                    channels=channels,
                    bitrate_bps=bitrate,
                )
            )

    if not video_streams and not audio_streams:
        return None

    return MediaQualityInfo(
        video_streams=tuple(video_streams),
        audio_streams=tuple(audio_streams),
    )


def format_media_quality(info: MediaQualityInfo) -> list[str]:
    lines: list[str] = []

    if info.video_streams:
        lines.append("--- Video ---")
        for stream in info.video_streams:
            label = f"Track {stream.track_number}"
            resolution = f"{stream.width}x{stream.height}"
            parts = [f"{label}: {stream.codec_label} ({stream.codec})", resolution]
            if stream.frame_rate is not None:
                parts.append(f"{stream.frame_rate:.2f} fps")
            bitrate = _format_bitrate(stream.bitrate_bps)
            if bitrate:
                parts.append(bitrate)
            lines.append(", ".join(parts))

    if info.audio_streams:
        if lines:
            lines.append("")
        lines.append("--- Audio ---")
        for stream in info.audio_streams:
            label = f"Track {stream.track_number}"
            parts = [
                f"{label}: {stream.codec_label} ({stream.codec})",
                f"{stream.sample_rate:,} Hz",
                f"{stream.channels} ch",
            ]
            bitrate = _format_bitrate(stream.bitrate_bps)
            if bitrate:
                parts.append(bitrate)
            lines.append(", ".join(parts))

    return lines
