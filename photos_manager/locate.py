"""locate - Find archive directories for new photos based on timestamps.

Scans a directory of new photos and searches archive JSON metadata to find
where each file belongs based on modification timestamp proximity. Can display
proposed target directories, interleaved file listings, or generate shell
scripts with move commands.

Usage:
    photos locate /path/to/new/photos archive.json
    photos locate /path/to/new/photos archive.json --list
    photos locate /path/to/new/photos archive.json --filter canon-eos
    photos locate /path/to/new/photos archive.json --output move.sh
"""

import argparse
import bisect
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from photos_manager.common import load_json


def load_archive_entries(
    json_files: list[str], path_filter: str | None
) -> list[tuple[datetime, dict[str, str | int]]]:
    """Load and merge archive entries from JSON files, sorted by date.

    Args:
        json_files: Paths to JSON metadata files.
        path_filter: If set, only include entries whose path contains this string.

    Returns:
        List of (datetime, entry) tuples sorted by date.
    """
    entries: list[tuple[datetime, dict[str, str | int]]] = []
    for json_file in json_files:
        data = load_json(json_file)
        for entry in data:
            path_str = str(entry.get("path", ""))
            if path_filter and path_filter not in path_str:
                continue
            date_str = str(entry.get("date", ""))
            if not date_str:
                continue
            dt = datetime.fromisoformat(date_str)
            entries.append((dt, entry))
    entries.sort(key=lambda x: x[0])
    return entries


def scan_new_files(directory: str) -> list[tuple[str, datetime]]:
    """Scan directory recursively for files and return paths with modification datetimes.

    Args:
        directory: Path to directory with new photos.

    Returns:
        List of (file_path, mtime_datetime) tuples sorted by mtime.
    """
    results: list[tuple[str, datetime]] = []
    dir_path = Path(directory)
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        mtime = file_path.stat().st_mtime
        dt = datetime.fromtimestamp(mtime, tz=UTC).astimezone()
        results.append((str(file_path), dt))
    results.sort(key=lambda x: x[1])
    return results


def find_neighbors(
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    target_dt: datetime,
    count: int,
) -> list[tuple[datetime, dict[str, str | int]]]:
    """Find archive entries closest in time to the target datetime.

    Uses binary search on the sorted entries to find N entries before and
    N entries after the target timestamp.

    Args:
        sorted_entries: Archive entries sorted by date.
        target_dt: Target datetime to search around.
        count: Number of entries to return before and after the target.

    Returns:
        List of (datetime, entry) tuples from the neighborhood.
    """
    dates = [dt for dt, _ in sorted_entries]
    pos = bisect.bisect_left(dates, target_dt)
    start = max(0, pos - count)
    end = min(len(sorted_entries), pos + count)
    return sorted_entries[start:end]


def build_directory_entries(
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
) -> dict[str, list[tuple[datetime, dict[str, str | int]]]]:
    """Group archive entries by parent directory, preserving date order.

    Args:
        sorted_entries: Archive entries sorted by date.

    Returns:
        Mapping of directory path to list of (datetime, entry) tuples.
    """
    by_dir: dict[str, list[tuple[datetime, dict[str, str | int]]]] = {}
    for dt, entry in sorted_entries:
        dir_path = str(Path(str(entry["path"])).parent)
        by_dir.setdefault(dir_path, []).append((dt, entry))
    return by_dir


def build_directory_ranges(
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
) -> dict[str, tuple[datetime, datetime]]:
    """Build date ranges for each archive directory.

    Args:
        dir_entries: Mapping of directory path to sorted (datetime, entry) lists.

    Returns:
        Mapping of directory path to (min_date, max_date) tuple.
    """
    return {d: (entries[0][0], entries[-1][0]) for d, entries in dir_entries.items()}


def propose_directories(
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    target_dt: datetime,
    context: int,
) -> list[str]:
    """Find candidate directories using hybrid range + neighbor matching.

    A directory is a candidate only if both conditions are met:
    1. The file's timestamp falls within the directory's [min, max] date range.
    2. The directory has at least one entry among the N nearest neighbors.

    Args:
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        target_dt: Timestamp of the new file.
        context: Number of neighbors to consider before and after.

    Returns:
        Sorted list of candidate directory paths.
    """
    range_matches = {d for d, (lo, hi) in dir_ranges.items() if lo <= target_dt <= hi}
    neighbors = find_neighbors(sorted_entries, target_dt, context)
    neighbor_dirs = {str(Path(str(e["path"])).parent) for _, e in neighbors}
    return sorted(range_matches & neighbor_dirs)


def extract_sequence_number(filename: str) -> int | None:
    """Extract a numeric sequence number from a filename.

    Returns the last run of digits found in the file stem.

    Args:
        filename: Filename (not full path).

    Returns:
        Integer sequence number, or None if no digits found.
    """
    stem = Path(filename).stem
    matches = re.findall(r"\d+", stem)
    if not matches:
        return None
    return int(matches[-1])


def filter_by_sequence(
    candidates: list[str],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    target_dt: datetime,
    target_name: str,
) -> list[str]:
    """Filter candidate directories by filename sequence number continuity.

    For each candidate directory, uses binary search to find the archive
    entries immediately before and after the target timestamp. If the new
    file's sequence number falls between those entries' sequence numbers,
    the directory is a sequence match.

    Returns only sequence-matched directories. If none match, returns
    the original candidates unchanged.

    Args:
        candidates: Candidate directory paths from hybrid matching.
        dir_entries: Pre-built mapping of directory to sorted (datetime, entry) lists.
        target_dt: Timestamp of the new file.
        target_name: Filename of the new file.

    Returns:
        Filtered list of candidate directory paths.
    """
    target_seq = extract_sequence_number(target_name)
    if target_seq is None:
        return candidates

    seq_matches: list[str] = []
    for candidate in candidates:
        entries = dir_entries.get(candidate, [])
        if not entries:
            continue
        dates = [dt for dt, _ in entries]
        pos = bisect.bisect_left(dates, target_dt)
        before_seq: int | None = None
        after_seq: int | None = None
        if pos > 0:
            before_seq = extract_sequence_number(Path(str(entries[pos - 1][1]["path"])).name)
        if pos < len(entries):
            after_seq = extract_sequence_number(Path(str(entries[pos][1]["path"])).name)
        # Check if target_seq falls between before and after
        if before_seq is not None and before_seq <= target_seq:
            if after_seq is None or target_seq <= after_seq:
                seq_matches.append(candidate)
        elif after_seq is not None and target_seq <= after_seq and before_seq is None:
            seq_matches.append(candidate)

    return sorted(seq_matches) if seq_matches else candidates


def _build_placements(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    context: int,
    *,
    use_seq: bool = False,
) -> list[tuple[str, list[str]]]:
    """Build (file_path, candidate_dirs) pairs without printing.

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_entries: Pre-built mapping of directory to sorted (datetime, entry) lists.
        context: Number of neighbors to consider.
        use_seq: If True, filter candidates by sequence number continuity.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    placements: list[tuple[str, list[str]]] = []
    for file_path, dt in new_files:
        candidates = propose_directories(sorted_entries, dir_ranges, dt, context)
        if use_seq and candidates:
            candidates = filter_by_sequence(candidates, dir_entries, dt, Path(file_path).name)
        if candidates:
            placements.append((file_path, candidates))
    return placements


def _print_default(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    context: int,
    *,
    use_seq: bool = False,
) -> list[tuple[str, list[str]]]:
    """Print default mode output and return (file_path, candidate_dirs) pairs.

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_entries: Pre-built mapping of directory to sorted (datetime, entry) lists.
        context: Number of neighbors to consider.
        use_seq: If True, filter candidates by sequence number continuity.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    placements: list[tuple[str, list[str]]] = []
    for file_path, dt in new_files:
        candidates = propose_directories(sorted_entries, dir_ranges, dt, context)
        if use_seq and candidates:
            candidates = filter_by_sequence(candidates, dir_entries, dt, Path(file_path).name)
        name = Path(file_path).name
        if candidates:
            print(f"{name}  \u2192  {', '.join(candidates)}")
            placements.append((file_path, candidates))
        else:
            print(f"{name}  \u2192  (no match found)", file=sys.stderr)
    return placements


def _print_list(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    context: int,
    *,
    use_seq: bool = False,
) -> list[tuple[str, list[str]]]:
    """Print merged listing of archive and new files with context.

    Merges all new files into the sorted archive timeline, then shows
    N archive entries before the first new file and N after the last,
    with all new files marked with ">".

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Sorted archive entries.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_entries: Pre-built mapping of directory to sorted (datetime, entry) lists.
        context: Number of archive entries to show before and after the new files.
        use_seq: If True, filter candidates by sequence number continuity.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    # Build merged timeline: (datetime, path, is_new, original_file_path)
    merged: list[tuple[datetime, str, bool, str]] = []
    for n_dt, entry in sorted_entries:
        merged.append((n_dt, str(entry["path"]), False, ""))
    for file_path, dt in new_files:
        merged.append((dt, Path(file_path).name, True, file_path))
    merged.sort(key=lambda x: x[0])

    # Find index range of new files in the merged list
    new_indices = [i for i, (_, _, is_new, _) in enumerate(merged) if is_new]
    if not new_indices:
        return []

    first_new = new_indices[0]
    last_new = new_indices[-1]

    # Expand to include N archive entries before and after
    # Count only archive entries (not new files) for context
    start = first_new
    archive_before = 0
    while start > 0 and archive_before < context:
        start -= 1
        if not merged[start][2]:
            archive_before += 1

    end = last_new
    archive_after = 0
    while end < len(merged) - 1 and archive_after < context:
        end += 1
        if not merged[end][2]:
            archive_after += 1

    for i in range(start, end + 1):
        item_dt, item_path, is_new, _ = merged[i]
        marker = ">" if is_new else " "
        print(f"{marker} {item_dt.strftime('%Y-%m-%d %H:%M:%S')}  {item_path}")

    # Find matching directories using hybrid range + neighbor matching
    candidates = propose_directories(sorted_entries, dir_ranges, new_files[0][1], context)
    if use_seq and candidates:
        candidates = filter_by_sequence(
            candidates, dir_entries, new_files[0][1], Path(new_files[0][0]).name
        )

    placements: list[tuple[str, list[str]]] = []
    if candidates:
        print(f"\nProposed directory: {', '.join(candidates)}\n")
        for file_path, _ in new_files:
            placements.append((file_path, candidates))
    else:
        print("\nNo matching directory found\n", file=sys.stderr)
    return placements


def _write_script(placements: list[tuple[str, str]], output_path: str) -> None:
    """Write shell script with mkdir and mv commands.

    Args:
        placements: List of (source_path, target_directory) tuples.
        output_path: Path to output shell script.

    Raises:
        SystemExit: If script cannot be written.
    """
    dirs = sorted({target for _, target in placements})
    lines = ["#!/bin/bash", "umask 022", ""]
    for d in dirs:
        lines.append(f'mkdir -p "{d}"')
    for src, target in placements:
        name = Path(src).name
        dest = str(Path(target) / name)
        lines.append(f'mv -iv "{src}" "{dest}"')

    try:
        script = Path(output_path)
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"To review commands, see: {output_path}")
    except OSError as e:
        raise SystemExit(f"Error: Cannot write script '{output_path}': {e}") from e


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for locate command.

    Adds all command-line arguments for the locate tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with locate arguments.
    """
    parser.add_argument(
        "directory",
        type=str,
        help="Directory with new photos to locate",
    )
    parser.add_argument(
        "json_files",
        nargs="+",
        help="One or more archive JSON metadata files",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Show interleaved file listing sorted by date",
    )
    parser.add_argument(
        "-N",
        "--context",
        type=int,
        default=5,
        help="Number of archive files to show before/after each new file (default: 5)",
    )
    parser.add_argument(
        "-f",
        "--filter",
        type=str,
        default=None,
        metavar="PATTERN",
        help="Only consider JSON entries whose path contains this string",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        metavar="FILE",
        help="Write mkdir and mv commands to shell script",
    )
    parser.add_argument(
        "--seq",
        action="store_true",
        help="Filter candidates by filename sequence number continuity",
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments for locate command.

    Args:
        args: Parsed command-line arguments.

    Raises:
        SystemExit: If any argument is invalid.
    """
    if not Path(args.directory).is_dir():
        raise SystemExit(f"Error: Not a directory: {args.directory}")
    for json_file in args.json_files:
        if not Path(json_file).is_file():
            raise SystemExit(f"Error: JSON file not found: {json_file}")


def run(args: argparse.Namespace) -> int:
    """Execute locate command with parsed arguments.

    Scans the directory for new files, loads archive metadata from JSON,
    and finds the best matching archive directories based on timestamp
    proximity.

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to directory with new photos
            - json_files: Paths to archive JSON metadata files
            - list: Whether to show interleaved listing
            - context: Number of neighbor files to consider
            - filter: Optional path substring filter
            - output: Optional path to output shell script
            - seq: Whether to filter by filename sequence continuity

    Returns:
        int: os.EX_OK on success.

    Raises:
        SystemExit: If arguments are invalid or no files found.
    """
    validate_args(args)

    sorted_entries = load_archive_entries(args.json_files, args.filter)
    if not sorted_entries:
        raise SystemExit("Error: No archive entries found (check JSON files and filter)")

    new_files = scan_new_files(args.directory)
    if not new_files:
        raise SystemExit(f"Error: No files found in {args.directory}")

    dir_entries = build_directory_entries(sorted_entries)
    dir_ranges = build_directory_ranges(dir_entries)

    print(f"Found {len(new_files)} new file(s), {len(sorted_entries)} archive entries")

    use_seq = getattr(args, "seq", False)

    if args.output:
        placements = _build_placements(
            new_files,
            sorted_entries,
            dir_ranges,
            dir_entries,
            args.context,
            use_seq=use_seq,
        )
        ambiguous = [(fp, dirs) for fp, dirs in placements if len(dirs) > 1]
        if ambiguous:
            print("Error: Ambiguous placement for:", file=sys.stderr)
            for fp, dirs in ambiguous:
                print(f"  {Path(fp).name}: {', '.join(dirs)}", file=sys.stderr)
            raise SystemExit("Use -f to narrow results")
        if placements:
            _write_script([(fp, dirs[0]) for fp, dirs in placements], args.output)
    elif args.list:
        _print_list(
            new_files,
            sorted_entries,
            dir_ranges,
            dir_entries,
            args.context,
            use_seq=use_seq,
        )
    else:
        _print_default(
            new_files,
            sorted_entries,
            dir_ranges,
            dir_entries,
            args.context,
            use_seq=use_seq,
        )

    return os.EX_OK
