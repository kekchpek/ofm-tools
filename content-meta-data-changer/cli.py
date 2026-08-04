"""Command-line interface for inspecting video files."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from layout import LayoutParseError, UnsupportedLayoutError, parse_file_layout
from layout.heif import format_payload_metadata_report
from layout.atom_database import format_unknown_atom_keys
from layout.base import CATEGORY_LABELS, format_unknown_memory_segments
from metadata import UnsupportedFormatError, format_metadata, supported_extensions


def _format_layout_segments(
    layout,
    *,
    category: str | None = None,
) -> str:
    total = len(layout.segments)
    number_width = len(str(total))
    lines: list[str] = [
        f"File size: {layout.file_size:,} bytes | Segments: {total}",
        "",
    ]

    for index, segment in enumerate(layout.segments, start=1):
        if category is not None and segment.category != category:
            continue
        category_label = CATEGORY_LABELS.get(segment.category, segment.category.title())
        number = f"{index:>{number_width}}."
        lines.append(
            f"{number} {segment.label}  |  {_format_segment_size(segment.size)}  |  {category_label}"
        )
        lines.append(f"    0x{segment.offset:08X} | {segment.path_label}")

    return "\n".join(lines)


def _format_segment_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _format_layout_summary(layout) -> str:
    counts = Counter(segment.category for segment in layout.segments)
    lines = [
        f"File size: {layout.file_size:,} bytes",
        f"Segments: {len(layout.segments)}",
        "",
        "By category:",
    ]
    for category in ("header", "structure", "metadata", "payload", "padding", "unknown"):
        if counts.get(category):
            label = CATEGORY_LABELS.get(category, category.title())
            lines.append(f"  {label}: {counts[category]}")
    return "\n".join(lines)


def inspect_file(path: Path) -> str:
    sections: list[str] = [f"=== {path.name} ===", ""]

    try:
        sections.extend(["--- Metadata ---", format_metadata(path), ""])
    except UnsupportedFormatError as exc:
        sections.extend(["--- Metadata ---", f"Error: {exc}", ""])
    except Exception as exc:
        sections.extend(["--- Metadata ---", f"Error reading metadata: {exc}", ""])

    try:
        layout = parse_file_layout(path)
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        sections.extend(["--- Layout ---", f"Error: {exc}", ""])
        return "\n".join(sections)

    sections.extend(["--- Layout Summary ---", _format_layout_summary(layout), ""])

    headers_text = format_unknown_atom_keys(layout.segments)
    sections.extend(
        [
            "--- Unknown Headers ---",
            headers_text or "(none)",
            "",
        ]
    )

    memory_text = format_unknown_memory_segments(layout.segments)
    sections.extend(
        [
            "--- Unknown Memory ---",
            memory_text or "(none)",
            "",
        ]
    )

    return "\n".join(sections).rstrip() + "\n"


def run_command(command: str, path: Path, *, category: str | None = None) -> str:
    if command == "metadata":
        return format_metadata(path)

    if command == "headers":
        layout = parse_file_layout(path)
        return format_unknown_atom_keys(layout.segments) or "(none)"

    if command == "memory":
        layout = parse_file_layout(path)
        return format_unknown_memory_segments(layout.segments) or "(none)"

    if command == "layout":
        layout = parse_file_layout(path)
        return _format_layout_segments(layout, category=category)

    if command == "summary":
        layout = parse_file_layout(path)
        return _format_layout_summary(layout)

    if command == "payload":
        layout = parse_file_layout(path)
        return format_payload_metadata_report(path, layout)

    if command == "inspect":
        return inspect_file(path)

    raise ValueError(f"Unknown command: {command}")


def build_parser() -> argparse.ArgumentParser:
    extensions = ", ".join(sorted(supported_extensions()))
    parser = argparse.ArgumentParser(
        description=(
            "Inspect metadata and memory layout of supported video files. "
            f"Supported extensions: {extensions}."
        ),
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the graphical interface",
    )

    subparsers = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("metadata", "Print tag metadata."),
        ("headers", "List atom headers missing from the descriptions database."),
        ("memory", "List memory segments classified as Unknown."),
        ("layout", "List all parsed memory segments."),
        ("summary", "Print memory layout category counts."),
        ("payload", "List metadata found inside payload/mdat segments."),
        ("inspect", "Print metadata, summary, unknown headers, and unknown memory."),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("path", type=Path, help="Path to the video file")

    layout_parser = subparsers.choices["layout"]
    layout_parser.add_argument(
        "--category",
        choices=tuple(CATEGORY_LABELS),
        help="Only show segments with this category.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"metadata", "headers", "memory", "layout", "summary", "payload", "inspect"}
    if (
        argv
        and argv[0] not in commands
        and argv[0] not in ("--gui", "-h", "--help")
        and not argv[0].startswith("-")
    ):
        argv.insert(0, "metadata")

    parser = build_parser()
    args = parser.parse_args(argv)
    path = getattr(args, "path", None)

    if args.gui or (args.command is None and path is None):
        from gui import run_gui

        return run_gui()

    if path is None:
        parser.error("A video file path is required.")

    if not path.is_file():
        print(f"Error: not a file: {path}", file=sys.stderr)
        return 1

    command = args.command or "metadata"
    category = getattr(args, "category", None)

    if command == "metadata" and path.suffix.lower() not in supported_extensions():
        extensions = ", ".join(sorted(supported_extensions()))
        print(
            f"Warning: unsupported extension {path.suffix}. Supported: {extensions}",
            file=sys.stderr,
        )

    try:
        output = run_command(command, path, category=category)
    except UnsupportedFormatError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (LayoutParseError, UnsupportedLayoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(output, end="" if output.endswith("\n") else "\n")
    return 0
