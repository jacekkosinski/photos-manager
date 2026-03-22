"""info - Show archive statistics from JSON metadata files.

This module reads existing JSON index files (produced by the index tool)
and an optional .version.json manifest to present a human-readable summary
of archive contents without touching or re-hashing the actual photo files.

Usage:
    photos info /path/to/archive
    photos info /path/to/archive --stats
    photos info /path/to/archive --stats --top-n 20

Example output (photos info /path/to/archive):
    Archive:        /Volumes/backup/photos
    Version:        photos-2.456-234
    Last modified:  Saturday, 15 March 2025  (7 days ago)
    Last verified:  Saturday, 22 March 2025  (2 hours ago)

    Index files:       3       1.2 MB    0.04%
    Total files:   12 345     2.9 TB   99.96%
    Grand total:   12 348     2.9 TB

    Date range:  2018-03-01  →  2024-11-15  (6 years, 8 months)

    Index files:
      archive1.json    5 000 files    1.2 TB   45.00%
      archive2.json    7 345 files    1.7 TB   55.00%

Exit codes:
    0 (os.EX_OK): Success
    1 (SystemExit): Error occurred (invalid directory, no JSON files found)
"""

import argparse
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from tabulate import tabulate

from photos_manager.common import (
    TABLE_FMT,
    date_span,
    find_json_files,
    find_version_file,
    format_count,
    format_date_verbose,
    human_size,
    load_metadata_json,
    load_version_json_lenient,
    validate_directory,
)


def _gather_stats(
    json_files: list[Path],
    records_per_file: dict[Path, list[dict[str, str | int]]],
) -> dict[str, Any]:
    """Aggregate statistics from all loaded index records.

    Iterates over every record in every index file to compute totals, date
    ranges, per-year breakdowns, per-extension breakdowns, and per-file
    summaries. Records with a missing or malformed ``date`` field are counted
    in all totals but silently excluded from date and year aggregation.

    Args:
        json_files: Ordered list of index JSON file paths; order determines the
            sequence of rows in the ``per_index`` summary.
        records_per_file: Mapping from each JSON path to its validated records
            as returned by ``load_metadata_json()``.

    Returns:
        Dictionary with the following keys:

        - ``total_files`` (int): Total number of records across all index files.
        - ``total_size`` (int): Combined size of all indexed files in bytes.
        - ``date_min`` (str | None): Earliest date found (``YYYY-MM-DD``), or
          None if no records contain a parseable date.
        - ``date_max`` (str | None): Latest date found (``YYYY-MM-DD``), or
          None if no records contain a parseable date.
        - ``by_year`` (dict[str, tuple[int, int]]): Maps four-digit year string
          to ``(count, bytes)`` for all records with a parseable date.
        - ``by_extension`` (dict[str, tuple[int, int]]): Maps lowercase file
          extension (e.g. ``'.jpg'``) to ``(count, bytes)``; files without an
          extension are grouped under ``'(no ext)'``.
        - ``index_files_size`` (int): Combined on-disk size of the JSON index
          files themselves in bytes.
        - ``grand_total_size`` (int): ``total_size + index_files_size``.
        - ``per_index`` (list[tuple[str, int, int]]): One entry per index file
          as ``(filename, record_count, total_bytes)``, in input order.
        - ``index_file_count`` (int): Number of index JSON files processed.
    """
    date_min: str | None = None
    date_max: str | None = None
    by_year: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_extension: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_index: list[tuple[str, int, int]] = []

    for json_file in json_files:
        records = records_per_file[json_file]
        file_size = 0

        for record in records:
            size = int(record.get("size", 0))
            file_size += size

            # Date handling — skip silently if missing or malformed
            date_val = record.get("date")
            if isinstance(date_val, str) and len(date_val) >= 10:
                date_str = date_val[:10]
                if date_min is None or date_str < date_min:
                    date_min = date_str
                if date_max is None or date_str > date_max:
                    date_max = date_str
                year = date_str[:4]
                by_year[year][0] += 1
                by_year[year][1] += size

            ext = Path(str(record.get("path", ""))).suffix.lower() or "(no ext)"
            by_extension[ext][0] += 1
            by_extension[ext][1] += size

        per_index.append((json_file.name, len(records), file_size))

    total_files = sum(cnt for _, cnt, _ in per_index)
    total_size = sum(size for _, _, size in per_index)
    index_files_size = sum(f.stat().st_size for f in json_files)

    return {
        "total_files": total_files,
        "total_size": total_size,
        "date_min": date_min,
        "date_max": date_max,
        "by_year": {k: tuple(v) for k, v in by_year.items()},
        "by_extension": {k: tuple(v) for k, v in by_extension.items()},
        "index_files_size": index_files_size,
        "grand_total_size": total_size + index_files_size,
        "per_index": per_index,
        "index_file_count": len(json_files),
    }


def _print_table(
    heading: str,
    rows: list[tuple[str, int, int]],
    denominator: int,
    top_n: int,
) -> None:
    """Print a labelled stats table to stdout with count, size, and percentage columns.

    Prints ``heading`` as a plain line, then up to ``top_n`` rows indented by
    two spaces, each showing label, file count, human-readable size, and
    percentage of ``denominator``. If the total number of rows exceeds
    ``top_n``, appends an overflow hint (e.g. ``… and 5 more``).

    Args:
        heading: Section header printed as-is, e.g. ``'By year:'``.
        rows: Pre-sorted list of ``(label, count, bytes)`` tuples.
        denominator: Total bytes used as the percentage denominator; treated
            as 1 when zero to avoid division by zero.
        top_n: Maximum number of data rows to display before the overflow hint.
    """
    print(heading)
    table_rows = [
        (
            label,
            f"{format_count(count)} files",
            human_size(size),
            f"{size / denominator * 100 if denominator else 0:.2f}%",
        )
        for label, count, size in rows[:top_n]
    ]
    for line in tabulate(
        table_rows, tablefmt=TABLE_FMT, colalign=("left", "right", "right", "right")
    ).splitlines():
        print(f"  {line}")
    if len(rows) > top_n:
        print(f"  \u2026 and {len(rows) - top_n} more")


def _print_summary(
    directory: Path,
    version_info: dict[str, Any] | None,
    stats: dict[str, Any],
) -> None:
    """Print the basic archive summary to stdout.

    Outputs up to four sections, all label columns padded to a common width:

    1. **Header** — resolved archive path; if a manifest is present: version
       string, last-modified timestamp, and last-verified timestamp.
    2. **Summary table** — index file count and size, total indexed file count
       and size, and the grand total (index + indexed), each with a percentage
       of the grand total.
    3. **Date range** — earliest and latest file dates with the span between
       them; omitted if no records contain a parseable date.
    4. **Per-index breakdown** — one indented row per JSON file showing its
       record count, size, and percentage of the grand total.

    Args:
        directory: Path to the archive directory; displayed as its resolved
            absolute path.
        version_info: Parsed ``.version.json`` data, or None if the manifest
            is absent or cannot be loaded.
        stats: Aggregated statistics dict produced by ``_gather_stats()``.
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
        date_rows = [("Date range:", date_span(date_min, date_max))]

    max_label = max(len(r[0]) for r in (*header_rows, *summary_rows, *date_rows))

    print(
        tabulate(
            [(r[0].ljust(max_label), r[1]) for r in header_rows],
            tablefmt=TABLE_FMT,
            colalign=("left", "left"),
        )
    )
    print()
    print(
        tabulate(
            [(r[0].ljust(max_label), r[1], r[2], r[3]) for r in summary_rows],
            tablefmt=TABLE_FMT,
            colalign=("left", "right", "right", "right"),
        )
    )
    print()
    if date_rows:
        print(
            tabulate(
                [(r[0].ljust(max_label), r[1]) for r in date_rows],
                tablefmt=TABLE_FMT,
                colalign=("left", "left"),
            )
        )
        print()

    per_index: list[tuple[str, int, int]] = stats["per_index"]
    if per_index:
        _print_table("Index files:", per_index, grand_total_size, len(per_index))


def _print_detail(stats: dict[str, Any], top_n: int) -> None:
    """Print by-year and by-extension breakdown tables to stdout.

    Outputs two sections separated by a blank line, each via ``_print_table``:

    1. **By year** — file count and size per calendar year, sorted
       chronologically; percentages are relative to ``total_size``.
    2. **By extension** — file count and size per lowercase file extension,
       sorted by size descending; percentages are relative to
       ``grand_total_size``. Files without an extension are grouped as
       ``'(no ext)'``.

    Each section is capped at ``top_n`` rows; an overflow hint is appended
    when there are more rows than the cap.

    Args:
        stats: Aggregated statistics dict produced by ``_gather_stats()``.
        top_n: Maximum rows to display per table before showing an overflow
            hint.
    """
    total_size: int = stats["total_size"]
    grand_total_size: int = stats["grand_total_size"]

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


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for info command.

    Adds all command-line arguments for the info tool to the provided parser.

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


def run(args: argparse.Namespace) -> int:
    """Execute info command with parsed arguments.

    Reads index JSON files and an optional .version.json manifest from the
    given archive directory and prints a human-readable summary to stdout.

    Workflow:
        1. Validates that the archive directory exists and is readable.
        2. Looks for a .version.json manifest in the directory (lenient —
           a missing or malformed manifest is silently ignored).
        3. Finds all JSON index files in the directory tree, excluding files
           whose names end with ``'version.json'``.
        4. Loads and validates every index file via ``load_metadata_json()``.
        5. Aggregates statistics across all records with ``_gather_stats()``.
        6. Prints the basic summary (always).
        7. If ``--stats`` is set, prints by-year and by-extension tables.

    Args:
        args: Parsed command-line arguments with fields:

            - ``directory`` (str): Path to the archive directory to inspect.
            - ``stats`` (bool): Whether to print detailed year/extension
              breakdown tables.
            - ``top_n`` (int): Maximum rows per breakdown table (default: 10).

    Returns:
        int: Exit code indicating success or failure:

            - ``os.EX_OK`` (0): Summary printed successfully.
            - 1 (``SystemExit``): Error occurred during processing.

    Raises:
        SystemExit: If any of the following errors occur:

            - Archive directory does not exist, is not a directory, or is not
              readable.
            - No JSON index files are found in the archive directory.
            - An index file contains invalid JSON or is missing required fields.

    Examples:
        >>> args = parser.parse_args(['/path/to/archive'])
        >>> exit_code = run(args)
        Archive:  /path/to/archive
        ...
    """
    directory = validate_directory(args.directory, check_readable=True)

    version_file = find_version_file(str(directory))
    version_info: dict[str, Any] | None = (
        load_version_json_lenient(version_file) if version_file is not None else None
    )

    try:
        json_file_paths = find_json_files(str(directory))
    except SystemExit:
        raise SystemExit(f"Error: no JSON index files found in '{directory}'") from None

    json_files = [Path(p) for p in json_file_paths]
    records_per_file = {f: load_metadata_json(str(f)) for f in json_files}

    stats = _gather_stats(json_files, records_per_file)
    _print_summary(directory, version_info, stats)
    if args.stats:
        _print_detail(stats, args.top_n)
    return os.EX_OK
