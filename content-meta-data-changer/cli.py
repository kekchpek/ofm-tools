"""Command-line interface for inspecting video files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.errors import LayoutError, UnsupportedMediaError
from core.inspect import (
    format_layout_summary_text,
    inspect_file_report,
    inspect_layout,
    inspect_metadata,
    inspect_payload_metadata,
    inspect_unknown_headers,
    inspect_unknown_memory,
)
from layout.base import CATEGORY_LABELS
from metadata import supported_extensions


def run_command(command: str, path: Path, *, category: str | None = None) -> str:
    if command == "metadata":
        return inspect_metadata(path).as_text()

    layout = inspect_layout(path)

    if command == "headers":
        return inspect_unknown_headers(path).text

    if command == "memory":
        return inspect_unknown_memory(path).text

    if command == "layout":
        return layout.as_text(category=category)

    if command == "summary":
        return format_layout_summary_text(layout)

    if command == "payload":
        return inspect_payload_metadata(path).text

    if command == "inspect":
        return inspect_file_report(path)

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
    except UnsupportedMediaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except LayoutError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(output, end="" if output.endswith("\n") else "\n")
    return 0
