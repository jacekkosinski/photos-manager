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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from photos_manager.common import (
    find_json_files,
    find_version_file,
    format_count,
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


_TIME_THRESHOLDS: list[tuple[int, int, str]] = [
    (60, 1, "second"),
    (3600, 60, "minute"),
    (86400, 3600, "hour"),
    (86400 * 30, 86400, "day"),
    (86400 * 365, 86400 * 30, "month"),
]


def _time_ago(iso_timestamp: str) -> str:
    """Return human-readable relative time from an ISO 8601 timestamp.

    Computes the difference between the given timestamp and now (UTC) and
    returns a string like '3 days ago', '2 months ago', '1 year ago'.

    Args:
        iso_timestamp: ISO 8601 timestamp string, e.g. '2025-12-30T12:34:56+01:00'.

    Returns:
        Human-readable relative time string.
    """
    dt = datetime.fromisoformat(iso_timestamp)
    seconds = int((datetime.now(tz=UTC) - dt.astimezone(UTC)).total_seconds())
    if seconds < 0:
        return "just now"
    for limit, divisor, unit in _TIME_THRESHOLDS:
        if seconds < limit:
            n = seconds // divisor
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    years = seconds // (86400 * 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


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


def _print_version_section(version_info: dict[str, Any]) -> None:
    """Print version, last-modified, and last-verified lines to stdout.

    Args:
        version_info: Parsed .version.json data.
    """
    print(f"{'Version:':<16}{version_info.get('version', 'N/A')}")
    for label, key in (("Last modified:", "last_modified"), ("Last verified:", "last_verified")):
        val = version_info.get(key, "")
        if isinstance(val, str) and val:
            date_str = datetime.fromisoformat(val).strftime("%A, %d %B %Y")
            print(f"{label:<16}{date_str}  ({_time_ago(val)})")


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
    col_gap: int = 2,
) -> None:
    """Print a labelled table of (name, count, size) rows with an overflow hint.

    Args:
        heading: Section header text, e.g. 'By year:'.
        rows: Pre-sorted list of (label, count, bytes) tuples.
        denominator: Total bytes used for percentage calculation.
        top_n: Maximum rows to display.
        col_gap: Number of spaces between the label and count columns (default: 2).
    """
    print(heading)
    shown = rows[:top_n]
    label_width = max((len(label) for label, _, _ in shown), default=0)
    sep = " " * col_gap
    for label, count, size in shown:
        pct = size / denominator * 100 if denominator > 0 else 0.0
        count_str = format_count(count)
        size_str = human_size(size)
        print(f"  {label:<{label_width}}{sep}{count_str:>8} files  {size_str:>10}  {pct:>8.2f}%")
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
    print(f"{'Archive:':<16}{directory.resolve()}")
    if version_info is not None:
        _print_version_section(version_info)
    print()

    grand_total_size: int = stats["grand_total_size"]
    total_size: int = stats["total_size"]
    index_files_size: int = stats["index_files_size"]
    total_files: int = stats["total_files"]
    index_file_count: int = stats["index_file_count"]

    denom = grand_total_size or 1
    ic_str = format_count(index_file_count)
    tf_str = format_count(total_files)
    print(
        f"{'Index files:':<14}{ic_str:>8}  "
        f"{human_size(index_files_size):>10}  {index_files_size / denom * 100:>8.2f}%"
    )
    print(
        f"{'Total files:':<14}{tf_str:>8}  "
        f"{human_size(total_size):>10}  {total_size / denom * 100:>8.2f}%"
    )
    grand_count = index_file_count + total_files
    gc_str = format_count(grand_count)
    print(f"{'Grand total:':<14}{gc_str:>8}  {human_size(grand_total_size):>10}")
    print()

    date_min: str | None = stats["date_min"]
    date_max: str | None = stats["date_max"]
    if date_min and date_max:
        span = _date_span(date_min, date_max)
        print(f"{'Date range:':<14}{date_min}  \u2192  {date_max}  ({span})")
        print()

    per_index: list[tuple[str, int, int]] = stats["per_index"]
    if per_index:
        print("Index files:")
        rows: list[tuple[str, str, str, str]] = []
        for filename, count, photo_bytes in per_index:
            pct = photo_bytes / grand_total_size * 100 if grand_total_size > 0 else 0.0
            count_str = format_count(count)
            pct_str = f"{pct:.2f}%"
            rows.append((filename, count_str, human_size(photo_bytes), pct_str))
        name_w = max(len(r[0]) for r in rows)
        count_w = max(len(r[1]) for r in rows)
        size_w = max(len(r[2]) for r in rows)
        pct_w = max(len(r[3]) for r in rows)
        for filename, count_str, size_str, pct_str in rows:
            print(
                f"  {filename:<{name_w}}    {count_str:>{count_w}} files"
                f"    {size_str:>{size_w}}    {pct_str:>{pct_w}}"
            )

    if show_detailed:
        print()
        by_year: dict[str, tuple[int, int]] = stats["by_year"]
        if by_year:
            _print_table(
                "By year:",
                [(yr, c, s) for yr, (c, s) in sorted(by_year.items())],
                total_size,
                top_n,
                col_gap=3,
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
