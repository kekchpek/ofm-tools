"""Shared QuickTime container metadata helpers."""

from pathlib import Path

from mutagen.mp4 import MP4, MP4Tags

from formats.stream_info import extract_media_quality, format_media_quality

TAG_NAMES = {
    "\xa9nam": "Title",
    "\xa9ART": "Artist",
    "\xa9alb": "Album",
    "\xa9day": "Date",
    "\xa9cmt": "Comment",
    "\xa9gen": "Genre",
    "\xa9grp": "Grouping",
    "\xa9lyr": "Lyrics",
    "\xa9too": "Encoder",
    "desc": "Description",
    "ldes": "Long description",
    "cprt": "Copyright",
    "aART": "Album artist",
    "trkn": "Track number",
    "disk": "Disc number",
    "gnre": "Genre (ID3)",
    "covr": "Cover art",
    "\xa9wrt": "Composer",
    "\xa9pub": "Publisher",
    "keyw": "Keywords",
    "pcst": "Podcast",
    "purl": "Podcast URL",
    "egid": "Episode global ID",
    "catg": "Category",
    "purd": "Purchase date",
    "soal": "Album sort order",
    "soaa": "Album artist sort order",
    "soar": "Artist sort order",
    "sonm": "Title sort order",
    "soco": "Composer sort order",
    "sosn": "Show sort order",
    "tvsh": "Show name",
    "\xa9wrk": "Work",
    "\xa9mvn": "Movement",
    "\xa9mvc": "Movement count",
    "\xa9mvi": "Movement index",
    "cpil": "Compilation",
    "pgap": "Gapless album",
    "tmpo": "Tempo (BPM)",
    "stik": "Media kind",
    "hdvd": "HD video",
    "rtng": "Content rating",
    "tves": "TV episode",
    "tvsn": "TV season",
    "shwm": "Show movement",
}

MEDIA_KINDS = {
    0: "Movie",
    1: "Normal (music)",
    2: "Audiobook",
    5: "Whacked bookmark",
    6: "Music video",
    9: "Home video",
    10: "TV show",
    11: "Book",
    14: "PDF",
}


def format_tag_key(key: str) -> str:
    if key in TAG_NAMES:
        return TAG_NAMES[key]

    if key.startswith("----:"):
        parts = key.split(":", 2)
        if len(parts) == 3:
            return f"Custom ({parts[2]})"
        return "Custom tag"

    if len(key) == 4 and ord(key[0]) == 0xA9:
        suffix = key[1:]
        for candidate in (key, f"\xa9{suffix.lower()}", f"\xa9{suffix.upper()}"):
            if candidate in TAG_NAMES:
                return TAG_NAMES[candidate]
        if suffix.isprintable():
            return f"Tag ({suffix})"

    if key.isascii() and key.isprintable():
        return key

    hex_label = " ".join(f"{ord(char):02x}" for char in key)
    return f"Tag [{hex_label}]"


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_tag_value(key: str, value) -> str:
    if key == "trkn" and isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, tuple) and len(item) >= 2:
                parts.append(f"{item[0]}/{item[1]}")
            else:
                parts.append(str(item))
        return ", ".join(parts)

    if key == "disk" and isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, tuple) and len(item) >= 2:
                parts.append(f"{item[0]}/{item[1]}")
            else:
                parts.append(str(item))
        return ", ".join(parts)

    if key == "covr":
        return f"{len(value)} embedded image(s)"

    if key == "stik" and isinstance(value, list) and value:
        label = MEDIA_KINDS.get(value[0], str(value[0]))
        rest = value[1:]
        if rest:
            return ", ".join([label, *(str(item) for item in rest)])
        return label

    if isinstance(value, list):
        return ", ".join(str(item) for item in value)

    return str(value)


def format_tags(tags: MP4Tags) -> list[str]:
    lines: list[str] = []

    for key in sorted(tags.keys()):
        label = format_tag_key(key)
        value = format_tag_value(key, tags[key])
        lines.append(f"{label}: {value}")

    return lines


def format_quicktime_metadata(path: Path, format_label: str) -> str:
    media = MP4(path)
    lines = [
        f"File: {path.name}",
        f"Path: {path.resolve()}",
        f"Format: {format_label}",
        f"Size: {path.stat().st_size:,} bytes",
        "",
        "--- Stream info ---",
    ]

    quality = extract_media_quality(path)
    info = media.info
    if info is None:
        lines.append("(no stream info)")
    else:
        if info.length is not None:
            lines.append(f"Duration: {format_duration(info.length)} ({info.length:.3f} s)")
            file_bitrate = int((path.stat().st_size * 8) / info.length)
            lines.append(f"Overall bitrate: {file_bitrate:,} bps")
        elif info.bitrate:
            lines.append(f"Bitrate: {info.bitrate:,} bps")
        if info.channels and quality is None:
            lines.append(f"Channels: {info.channels}")
        if info.sample_rate and quality is None:
            lines.append(f"Sample rate: {info.sample_rate:,} Hz")
        if getattr(info, "codec", None) and quality is None:
            lines.append(f"Codec: {info.codec}")

    if quality is not None:
        quality_lines = format_media_quality(quality)
        if quality_lines:
            lines.append("")
            lines.extend(quality_lines)

    lines.append("")
    lines.append("--- Tags ---")

    if media.tags:
        tag_lines = format_tags(media.tags)
        lines.extend(tag_lines if tag_lines else ["(empty tags)"])
    else:
        lines.append("(no tags)")

    return "\n".join(lines)
