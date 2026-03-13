"""locate - Find archive directories for new photos based on timestamps.

Scans a directory of new photos and searches archive JSON metadata to find
where each file belongs based on modification timestamp proximity. Can display
proposed target directories, interleaved file listings, or generate shell
scripts with move commands.

Usage:
    photos locate /path/to/new/photos archive.json
    photos locate /path/to/new/photos archive.json --list
    photos locate /path/to/new/photos archive.json -f canon-eos -f apple-ipad
    photos locate /path/to/new/photos archive.json --output move.sh
    photos locate /path/to/new/photos archive.json --seq
    photos locate /path/to/new/photos archive.json --seq --prefix
"""

import argparse
import bisect
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from photos_manager.common import load_json, validate_directory


def load_archive_entries(
    json_files: list[str], path_filters: list[str] | None
) -> list[tuple[datetime, dict[str, str | int]]]:
    """Load and merge archive entries from JSON files, sorted by date.

    Args:
        json_files: Paths to JSON metadata files.
        path_filters: If set, only include entries whose path contains
            at least one of these strings (OR logic).

    Returns:
        List of (datetime, entry) tuples sorted by date.
    """
    entries: list[tuple[datetime, dict[str, str | int]]] = []
    for json_file in json_files:
        data = load_json(json_file)
        for entry in data:
            path_str = str(entry.get("path", ""))
            if path_filters and not any(f in path_str for f in path_filters):
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
        try:
            mtime = file_path.stat().st_mtime
        except OSError as e:
            print(f"Warning: Cannot stat {file_path}: {e}", file=sys.stderr)
            continue
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


_PREFIX_SEQ_RE = re.compile(r"^(.*?)(\d+)\.[^.]+$")


def build_directory_seqs(
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
) -> dict[str, list[tuple[str | None, int]]]:
    """Pre-compute sorted (prefix, sequence_number) pairs per directory.

    Extracts filename prefix and sequence number from every archive entry
    once, so that ``find_seq_matches`` can do fast lookups without repeated
    regex calls.

    Args:
        dir_entries: Mapping of directory path to sorted (datetime, entry) lists.

    Returns:
        Mapping of directory path to sorted list of (prefix, seq) tuples.
    """
    pat = _PREFIX_SEQ_RE
    result: dict[str, list[tuple[str | None, int]]] = {}
    for d, entries in dir_entries.items():
        pairs: list[tuple[str | None, int]] = []
        for _, e in entries:
            path_str = str(e["path"])
            # Extract filename without Path object overhead
            slash = path_str.rfind("/")
            name = path_str[slash + 1 :] if slash >= 0 else path_str
            m = pat.match(name)
            if m:
                pairs.append((m.group(1), int(m.group(2))))
        if pairs:
            pairs.sort(key=lambda x: x[1])
            result[d] = pairs
    return result


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


def extract_filename_prefix(filename: str) -> str | None:
    """Extract the prefix before the last digit run in a filename.

    For example, "img_6767.jpg" returns "img_", "DSC05242.jpg" returns "DSC".

    Args:
        filename: Filename (not full path).

    Returns:
        Prefix string, or None if no digits found.
    """
    stem = Path(filename).stem
    match = re.match(r"^(.*?)\d+$", stem)
    if not match:
        return None
    return match.group(1)


def find_seq_matches(
    directories: list[str],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    target_name: str,
    *,
    match_prefix: bool = False,
) -> list[str]:
    """Find directories where the target file's sequence number fits.

    Uses pre-computed sequence data from ``build_directory_seqs`` for fast
    lookup. For each directory, uses binary search to find the entries
    immediately before and after the target sequence number.

    When ``match_prefix`` is True, only entries whose filename prefix matches
    the target file are considered (e.g. "img_" entries for "img_6767.jpg").

    When multiple directories match, only those with the tightest gap
    (smallest difference between adjacent sequence numbers) are returned.

    Args:
        directories: Directory paths to check.
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        target_name: Filename of the new file.
        match_prefix: If True, only compare entries with the same filename prefix.

    Returns:
        Sorted list of directories where sequence number fits.
    """
    target_seq = extract_sequence_number(target_name)
    if target_seq is None:
        return []
    target_prefix = extract_filename_prefix(target_name) if match_prefix else None

    strong: list[tuple[str, int]] = []  # (dir, gap) — both boundaries present
    weak: list[str] = []  # one boundary missing
    for d in directories:
        pairs = dir_seqs.get(d, [])
        if not pairs:
            continue
        if target_prefix is not None:
            seqs = [s for p, s in pairs if p == target_prefix]
        else:
            seqs = [s for _, s in pairs]
        if not seqs:
            continue
        # seqs already sorted (from build_directory_seqs)
        pos = bisect.bisect_left(seqs, target_seq)
        before_seq: int | None = seqs[pos - 1] if pos > 0 else None
        after_seq: int | None = seqs[pos] if pos < len(seqs) else None
        if before_seq is not None and after_seq is not None:
            if before_seq <= target_seq <= after_seq:
                strong.append((d, after_seq - before_seq))
        elif (before_seq is not None and before_seq <= target_seq) or (
            after_seq is not None and target_seq <= after_seq
        ):
            weak.append(d)

    if strong:
        min_gap = min(gap for _, gap in strong)
        return sorted(d for d, gap in strong if gap == min_gap)
    return sorted(weak)


def _resolve_candidates(
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    target_dt: datetime,
    context: int,
    *,
    use_seq: bool = False,
    match_prefix: bool = False,
    filename: str = "",
) -> list[str]:
    """Find candidate directories for a single file.

    Without --seq: uses hybrid range + neighbor matching.
    With --seq: checks all range-matched directories for sequence fit;
    if found, uses those. Otherwise falls back to hybrid. If hybrid also
    returns nothing, tries sequence match against all directories.

    Args:
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        target_dt: Timestamp of the new file.
        context: Number of neighbors to consider.
        use_seq: If True, use sequence number matching.
        match_prefix: If True, only compare entries with the same filename prefix.
        filename: Filename of the new file (used with use_seq).

    Returns:
        Sorted list of candidate directory paths.
    """
    candidates = propose_directories(sorted_entries, dir_ranges, target_dt, context)
    if not use_seq:
        return candidates

    # Check all range-matched dirs for sequence fit (broader than hybrid)
    range_matches = sorted(d for d, (lo, hi) in dir_ranges.items() if lo <= target_dt <= hi)
    seq_candidates = find_seq_matches(
        range_matches,
        dir_seqs,
        filename,
        match_prefix=match_prefix,
    )
    if seq_candidates:
        return seq_candidates

    # No seq match in range — keep hybrid candidates if available
    if candidates:
        return candidates

    # File outside all ranges — try all dirs by sequence
    return find_seq_matches(
        sorted(dir_seqs.keys()),
        dir_seqs,
        filename,
        match_prefix=match_prefix,
    )


def _build_placements(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    context: int,
    *,
    use_seq: bool = False,
    match_prefix: bool = False,
) -> list[tuple[str, list[str]]]:
    """Build (file_path, candidate_dirs) pairs without printing.

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        context: Number of neighbors to consider.
        use_seq: If True, filter candidates by sequence number continuity.
        match_prefix: If True, only compare entries with the same filename prefix.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    placements: list[tuple[str, list[str]]] = []
    for file_path, dt in new_files:
        candidates = _resolve_candidates(
            sorted_entries,
            dir_ranges,
            dir_seqs,
            dt,
            context,
            use_seq=use_seq,
            match_prefix=match_prefix,
            filename=Path(file_path).name,
        )
        if candidates:
            placements.append((file_path, candidates))
    return placements


def _print_default(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    context: int,
    *,
    use_seq: bool = False,
    match_prefix: bool = False,
) -> list[tuple[str, list[str]]]:
    """Print default mode output and return (file_path, candidate_dirs) pairs.

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Archive entries sorted by date.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        context: Number of neighbors to consider.
        use_seq: If True, filter candidates by sequence number continuity.
        match_prefix: If True, only compare entries with the same filename prefix.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    placements = _build_placements(
        new_files,
        sorted_entries,
        dir_ranges,
        dir_seqs,
        context,
        use_seq=use_seq,
        match_prefix=match_prefix,
    )
    placed = dict(placements)
    for file_path, _ in new_files:
        name = Path(file_path).name
        candidates = placed.get(file_path)
        if candidates:
            print(f"{name}  \u2192  {', '.join(candidates)}")
        else:
            print(f"{name}  \u2192  (no match found)")
    return placements


def _print_list(
    new_files: list[tuple[str, datetime]],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_ranges: dict[str, tuple[datetime, datetime]],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    context: int,
    *,
    use_seq: bool = False,
    match_prefix: bool = False,
    base_dir: str = "",
) -> list[tuple[str, list[str]]]:
    """Print merged listing of archive and new files with context.

    Merges all new files into the sorted archive timeline, then shows
    N archive entries before and after each new file, with "---"
    separators between non-contiguous groups. New files are marked
    with ">" and " <" suffix.

    Args:
        new_files: List of (path, datetime) for new files.
        sorted_entries: Sorted archive entries.
        dir_ranges: Mapping of directory path to (min_date, max_date).
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        context: Number of archive entries to show before and after the new files.
        use_seq: If True, filter candidates by sequence number continuity.
        match_prefix: If True, only compare entries with the same filename prefix.
        base_dir: Base directory for displaying relative paths of new files.

    Returns:
        List of (file_path, candidate_directories) tuples.
    """
    # Build merged timeline: (datetime, path, is_new)
    merged: list[tuple[datetime, str, bool]] = []
    for dt, entry in sorted_entries:
        merged.append((dt, str(entry["path"]), False))
    base = Path(base_dir).parent if base_dir else None
    for file_path, dt in new_files:
        display = str(Path(file_path).relative_to(base)) if base else Path(file_path).name
        merged.append((dt, display, True))
    merged.sort(key=lambda x: x[0])

    # Find indices of new files in the merged list
    new_indices = [i for i, (_, _, is_new) in enumerate(merged) if is_new]
    if not new_indices:
        return []

    # For each new file, mark N archive entries before and after as visible
    visible: set[int] = set()
    for ni in new_indices:
        visible.add(ni)
        count = 0
        j = ni - 1
        while j >= 0 and count < context:
            visible.add(j)
            if not merged[j][2]:
                count += 1
            j -= 1
        count = 0
        j = ni + 1
        while j < len(merged) and count < context:
            visible.add(j)
            if not merged[j][2]:
                count += 1
            j += 1

    # Print visible entries with separator between non-contiguous groups
    prev_idx: int | None = None
    for idx in sorted(visible):
        if prev_idx is not None and idx > prev_idx + 1:
            print("  (...)")
        item_dt, item_path, is_new = merged[idx]
        marker = ">" if is_new else " "
        suffix = " <" if is_new else ""
        print(f"{marker} {item_dt.strftime('%Y-%m-%d %H:%M:%S')}  {item_path}{suffix}")
        prev_idx = idx

    # Aggregate candidates across all new files
    per_file = _build_placements(
        new_files,
        sorted_entries,
        dir_ranges,
        dir_seqs,
        context,
        use_seq=use_seq,
        match_prefix=match_prefix,
    )
    candidates = sorted({d for _, dirs in per_file for d in dirs})
    placements: list[tuple[str, list[str]]] = []
    if candidates:
        print(f"\nProposed directory: {', '.join(candidates)}\n")
        for file_path, _ in new_files:
            placements.append((file_path, candidates))
    else:
        print("\nNo matching directory found\n")
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
        action="append",
        default=None,
        metavar="PATTERN",
        help="Only consider entries whose path contains PATTERN (repeatable, OR logic)",
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
        "-s",
        "--seq",
        action="store_true",
        help="Filter candidates by filename sequence number continuity",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        action="store_true",
        help="Only compare files with same naming pattern (requires --seq)",
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments for locate command.

    Args:
        args: Parsed command-line arguments.

    Raises:
        SystemExit: If any argument is invalid.
    """
    validate_directory(args.directory)
    for json_file in args.json_files:
        if not Path(json_file).is_file():
            raise SystemExit(f"Error: JSON file not found: {json_file}")
    if args.prefix and not args.seq:
        raise SystemExit("Error: --prefix requires --seq")


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
            - filter: Optional list of path substring filters (OR logic)
            - output: Optional path to output shell script
            - seq: Whether to filter by filename sequence continuity
            - prefix: Whether to restrict seq matching to same filename prefix

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
    dir_seqs = build_directory_seqs(dir_entries)

    print(f"Found {len(new_files)} new file(s), {len(sorted_entries)} archive entries")

    use_seq: bool = args.seq
    match_prefix: bool = args.prefix

    if args.output:
        placements = _build_placements(
            new_files,
            sorted_entries,
            dir_ranges,
            dir_seqs,
            args.context,
            use_seq=use_seq,
            match_prefix=match_prefix,
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
            dir_seqs,
            args.context,
            use_seq=use_seq,
            match_prefix=match_prefix,
            base_dir=args.directory,
        )
    else:
        _print_default(
            new_files,
            sorted_entries,
            dir_ranges,
            dir_seqs,
            args.context,
            use_seq=use_seq,
            match_prefix=match_prefix,
        )

    return os.EX_OK
