"""info - Show archive statistics from JSON metadata files.

This module reads existing JSON index files (produced by the index tool)
and an optional .version.json manifest to present a human-readable summary
of archive contents without touching or re-hashing the actual photo files.

Usage:
    photos info /path/to/archive
    photos info /path/to/archive --stats
    photos info /path/to/archive --stats --top-n 20

Exit codes:
    0 (os.EX_OK): Success
    1 (SystemExit): Error occurred (invalid directory, no JSON files found)
"""

import argparse
import os
from datetime import date
from pathlib import Path
from typing import Any

from tabulate import tabulate

from photos_manager.common import (
    find_json_files,
    find_version_file,
    format_count,
    format_date_verbose,
    human_size,
    load_metadata_json,
    load_version_json_lenient,
    validate_directory,
)


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for info command.

    Args:
        parser: ArgumentParser instance to configure with info arguments.
    """
    parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=".",
        help="Path to the archive directory (default: current directory)",
    )
    parser.add_argument(
        "-s",
        "--stats",
        action="store_true",
        help="Show detailed stats by year and file extension",
    )
    parser.add_argument(
        "-N",
        "--top-n",
        type=int,
        default=10,
        dest="top_n",
        help="Max rows to show in year/extension tables (default: 10)",
    )


def _gather_stats(
    json_files: list[Path],
    records_per_file: dict[Path, list[dict[str, str | int]]],
) -> dict[str, Any]:
    """Aggregate statistics from all loaded index records.

    Computes total file counts and sizes, date ranges, per-year and
    per-extension breakdowns, and per-index-file summaries.

    Args:
        json_files: List of index JSON file paths (ordered).
        records_per_file: Mapping from each JSON path to its loaded records.

    Returns:
        Dictionary with keys:
            total_files (int), total_size (int), date_min (str|None),
            date_max (str|None), by_year (dict), by_extension (dict),
            index_files_size (int), grand_total_size (int),
            per_index (list), index_file_count (int).
    """
    total_files = 0
    total_size = 0
    dates: list[str] = []
    by_year: dict[str, list[int]] = {}
    by_extension: dict[str, list[int]] = {}
    per_index: list[tuple[str, int, int]] = []

    for json_file in json_files:
        records = records_per_file[json_file]
        file_count = len(records)
        file_size = 0

        for record in records:
            size = int(record.get("size", 0))
            file_size += size
            total_size += size
            total_files += 1

            # Date handling — skip silently if missing or malformed
            date_val = record.get("date")
            if isinstance(date_val, str) and len(date_val) >= 10:
                date_str = date_val[:10]
                dates.append(date_str)
                year = date_val[:4]
                if year not in by_year:
                    by_year[year] = [0, 0]
                by_year[year][0] += 1
                by_year[year][1] += size

            # Extension handling
            path_val = record.get("path", "")
            ext = Path(str(path_val)).suffix.lower()
            ext_key = ext if ext else "(no ext)"
            if ext_key not in by_extension:
                by_extension[ext_key] = [0, 0]
            by_extension[ext_key][0] += 1
            by_extension[ext_key][1] += size

        per_index.append((json_file.name, file_count, file_size))

    index_files_size = sum(f.stat().st_size for f in json_files)
    grand_total_size = total_size + index_files_size
    date_min: str | None = min(dates) if dates else None
    date_max: str | None = max(dates) if dates else None

    return {
        "total_files": total_files,
        "total_size": total_size,
        "date_min": date_min,
        "date_max": date_max,
        "by_year": {k: (v[0], v[1]) for k, v in by_year.items()},
        "by_extension": {k: (v[0], v[1]) for k, v in by_extension.items()},
        "index_files_size": index_files_size,
        "grand_total_size": grand_total_size,
        "per_index": per_index,
        "index_file_count": len(json_files),
    }


def _date_span(date_min: str, date_max: str) -> str:
    """Return human-readable duration between two ISO date strings (YYYY-MM-DD).

    Args:
        date_min: Earlier date string, e.g. '2018-03-01'.
        date_max: Later date string, e.g. '2024-11-15'.

    Returns:
        Human-readable span string, e.g. '6 years, 8 months' or '45 days'.
    """
    d1 = date.fromisoformat(date_min)
    d2 = date.fromisoformat(date_max)
    days = (d2 - d1).days
    if days < 31:
        return f"{days} day{'s' if days != 1 else ''}"
    months_total = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    years, months = divmod(months_total, 12)
    if years == 0:
        return f"{months} month{'s' if months != 1 else ''}"
    if months == 0:
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{years} year{'s' if years != 1 else ''}, {months} month{'s' if months != 1 else ''}"


def _print_table(
    heading: str,
    rows: list[tuple[str, int, int]],
    denominator: int,
    top_n: int,
) -> None:
    """Print a labelled table of (name, count, size) rows with an overflow hint.

    Args:
        heading: Section header text, e.g. 'By year:'.
        rows: Pre-sorted list of (label, count, bytes) tuples.
        denominator: Total bytes used for percentage calculation.
        top_n: Maximum rows to display.
    """
    print(heading)
    shown = rows[:top_n]
    table_rows = [
        (
            label,
            f"{format_count(count)} files",
            human_size(size),
            f"{size / denominator * 100 if denominator else 0:.2f}%",
        )
        for label, count, size in shown
    ]
    for line in tabulate(
        table_rows, tablefmt="plain", colalign=("left", "right", "right", "right")
    ).splitlines():
        print(f"  {line}")
    if len(rows) > top_n:
        print(f"  \u2026 and {len(rows) - top_n} more")


def _print_stats(
    directory: Path,
    version_info: dict[str, Any] | None,
    stats: dict[str, Any],
    show_detailed: bool,
    top_n: int = 10,
) -> None:
    """Print a human-readable archive statistics summary to stdout.

    Args:
        directory: Path to the archive directory.
        version_info: Parsed .version.json data, or None if absent.
        stats: Aggregated statistics from _gather_stats().
        show_detailed: Whether to print by-year and by-extension breakdowns.
        top_n: Maximum rows to show in each breakdown table.
    """
    grand_total_size: int = stats["grand_total_size"]
    total_size: int = stats["total_size"]
    index_files_size: int = stats["index_files_size"]
    total_files: int = stats["total_files"]
    index_file_count: int = stats["index_file_count"]
    date_min: str | None = stats["date_min"]
    date_max: str | None = stats["date_max"]

    header_rows: list[tuple[str, str]] = [("Archive:", str(directory.resolve()))]
    if version_info is not None:
        header_rows.append(("Version:", str(version_info.get("version", "N/A"))))
        for label, key in (
            ("Last modified:", "last_modified"),
            ("Last verified:", "last_verified"),
        ):
            val = version_info.get(key, "")
            if isinstance(val, str) and val:
                header_rows.append((label, format_date_verbose(val)))

    denom = grand_total_size or 1
    summary_rows: list[tuple[str, str, str, str]] = [
        (
            "Index files:",
            format_count(index_file_count),
            human_size(index_files_size),
            f"{index_files_size / denom * 100:.2f}%",
        ),
        (
            "Total files:",
            format_count(total_files),
            human_size(total_size),
            f"{total_size / denom * 100:.2f}%",
        ),
        (
            "Grand total:",
            format_count(index_file_count + total_files),
            human_size(grand_total_size),
            "",
        ),
    ]

    date_rows: list[tuple[str, str]] = []
    if date_min and date_max:
        date_rows = [
            ("Date range:", f"{date_min}  \u2192  {date_max}  ({_date_span(date_min, date_max)})")
        ]

    all_labels = (
        [r[0] for r in header_rows] + [r[0] for r in summary_rows] + [r[0] for r in date_rows]
    )
    max_label = max(len(label) for label in all_labels)

    print(
        tabulate(
            [(r[0].ljust(max_label), r[1]) for r in header_rows],
            tablefmt="plain",
            colalign=("left", "left"),
        )
    )
    print()
    print(
        tabulate(
            [(r[0].ljust(max_label), r[1], r[2], r[3]) for r in summary_rows],
            tablefmt="plain",
            colalign=("left", "right", "right", "right"),
        )
    )
    print()
    if date_rows:
        print(
            tabulate(
                [(r[0].ljust(max_label), r[1]) for r in date_rows],
                tablefmt="plain",
                colalign=("left", "left"),
            )
        )
        print()

    per_index: list[tuple[str, int, int]] = stats["per_index"]
    if per_index:
        print("Index files:")
        table_rows = [
            (
                fname,
                f"{format_count(cnt)} files",
                human_size(size),
                f"{size / grand_total_size * 100 if grand_total_size else 0:.2f}%",
            )
            for fname, cnt, size in per_index
        ]
        for line in tabulate(
            table_rows, tablefmt="plain", colalign=("left", "right", "right", "right")
        ).splitlines():
            print(f"  {line}")

    if show_detailed:
        print()
        by_year: dict[str, tuple[int, int]] = stats["by_year"]
        if by_year:
            _print_table(
                "By year:",
                [(yr, c, s) for yr, (c, s) in sorted(by_year.items())],
                total_size,
                top_n,
            )
        print()
        by_ext: dict[str, tuple[int, int]] = stats["by_extension"]
        if by_ext:
            _print_table(
                "By extension:",
                [
                    (ext, c, s)
                    for ext, (c, s) in sorted(by_ext.items(), key=lambda x: x[1][1], reverse=True)
                ],
                grand_total_size,
                top_n,
            )


def run(args: argparse.Namespace) -> int:
    """Execute info command with parsed arguments.

    Reads index JSON files and an optional .version.json manifest from
    the given archive directory and prints a human-readable summary.

    Args:
        args: Parsed command-line arguments with fields:
            - directory (Path): Archive directory to inspect.
            - stats (bool): Whether to print detailed year/extension tables.
            - top_n (int): Maximum rows in detail tables (default 10).

    Returns:
        os.EX_OK (0) on success.

    Raises:
        SystemExit: If directory is invalid or no JSON index files are found.
    """
    directory = validate_directory(args.directory, check_readable=True)

    # Look for a .version.json manifest
    version_file = find_version_file(str(directory))
    version_info: dict[str, Any] | None = (
        load_version_json_lenient(version_file) if version_file is not None else None
    )

    # Find index JSON files (excludes *version.json automatically)
    try:
        json_file_paths = find_json_files(str(directory))
    except SystemExit:
        raise SystemExit(f"Error: no JSON index files found in '{directory}'") from None

    json_files = [Path(p) for p in json_file_paths]

    # Load records from each index file
    records_per_file: dict[Path, list[dict[str, str | int]]] = {}
    for json_file in json_files:
        records_per_file[json_file] = load_metadata_json(str(json_file))

    stats = _gather_stats(json_files, records_per_file)
    _print_stats(directory, version_info, stats, args.stats, args.top_n)
    return os.EX_OK
