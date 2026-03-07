"""sequences - Detect and separate interleaved photo sequences.

Analyzes archive JSON metadata to find interleaved camera sequences.
Files from all matching directories are pooled together and partitioned
into coherent sequences where both filename numbers and dates increase
monotonically. A single sequence may span multiple directories.

Usage:
    photos sequences archive.json
    photos sequences archive.json -f apple-ipad-2
    photos sequences archive.json -f apple-ipad-2 -l
    photos sequences archive.json -f apple-ipad-2 -o move.sh -S 2
    photos sequences archive.json -f apple-ipad-2 -o move.sh -S 2 -S 3
"""

import argparse
import bisect
import os
import re
import stat
from collections import Counter
from datetime import datetime
from pathlib import Path

from photos_manager.common import load_json

_SEQ_RE = re.compile(r"^(.*?)(\d+)\.[^.]+$")


def load_files(
    json_files: list[str], path_filters: list[str] | None
) -> list[tuple[str, str, int, datetime]]:
    """Load archive entries with sequence numbers, sorted by date.

    Args:
        json_files: Paths to JSON metadata files.
        path_filters: If set, only include entries whose path contains
            at least one of these strings (OR logic).

    Returns:
        List of (file_path, prefix, seq, date) tuples sorted by date.
    """
    results: list[tuple[str, str, int, datetime]] = []
    for json_file in json_files:
        data = load_json(json_file)
        for entry in data:
            path_str = str(entry.get("path", ""))
            if path_filters and not any(f in path_str for f in path_filters):
                continue
            date_str = str(entry.get("date", ""))
            if not date_str:
                continue
            name = Path(path_str).name
            m = _SEQ_RE.match(name)
            if not m:
                continue
            prefix = m.group(1)
            seq = int(m.group(2))
            dt = datetime.fromisoformat(date_str)
            results.append((path_str, prefix, seq, dt))

    results.sort(key=lambda x: x[3])
    return results


def detect_sequences(
    files: list[tuple[str, str, int, datetime]],
) -> list[list[tuple[str, str, int, datetime]]]:
    """Partition files into minimum monotonic increasing subsequences.

    Files must be pre-sorted by date. A sequence is coherent when both
    sequence numbers and dates increase (dates already sorted, so only
    sequence number monotonicity needs checking).

    Uses greedy assignment: each file joins the sequence whose last
    sequence number is the largest value still <= the file's number
    (tightest fit), minimizing the total number of sequences.

    Args:
        files: List of (path, prefix, seq, date) tuples sorted by date.

    Returns:
        List of sequences, each a list of (path, prefix, seq, date) tuples.
        Sorted by sequence length descending (longest first).
    """
    # Track last seq number per active sequence for binary search
    last_seqs: list[int] = []
    sequences: list[list[tuple[str, str, int, datetime]]] = []

    for item in files:
        seq = item[2]
        # Find rightmost sequence whose last_seq <= seq (tightest fit)
        pos = bisect.bisect_right(last_seqs, seq)
        if pos > 0:
            idx = pos - 1
            sequences[idx].append(item)
            # Maintain sorted order of last_seqs
            del last_seqs[idx]
            new_pos = bisect.bisect_left(last_seqs, seq)
            last_seqs.insert(new_pos, seq)
            # Move the sequence reference to match
            seq_ref = sequences.pop(idx)
            sequences.insert(new_pos, seq_ref)
        else:
            # No sequence can accept this — start a new one
            new_pos = bisect.bisect_left(last_seqs, seq)
            last_seqs.insert(new_pos, seq)
            sequences.insert(new_pos, [item])

    # Sort by length descending (longest = main sequence first)
    sequences.sort(key=len, reverse=True)
    return sequences


def _seq_directories(seq: list[tuple[str, str, int, datetime]]) -> list[str]:
    """Extract unique directory names from a sequence, ordered by frequency."""
    dirs = Counter(str(Path(path).parent) for path, _, _, _ in seq)
    return [d for d, _ in dirs.most_common()]


def count_missing(seq: list[tuple[str, str, int, datetime]]) -> int:
    """Count missing sequence numbers in a sequence.

    Args:
        seq: List of (path, prefix, seq_num, date) tuples for one sequence.

    Returns:
        Number of integers absent from the range [min_seq, max_seq].
    """
    if len(seq) < 2:
        return 0
    seq_nums = sorted({item[2] for item in seq})
    return seq_nums[-1] - seq_nums[0] + 1 - len(seq_nums)


def find_gaps(seq: list[tuple[str, str, int, datetime]]) -> list[str]:
    """Find gaps in sequence numbers within a single sequence.

    Compares consecutive sequence numbers and identifies missing values.
    Isolated missing numbers (1 or 2 in a row) are returned individually;
    runs of 3 or more are aggregated as "start-end (count)".

    Args:
        seq: List of (path, prefix, seq_num, date) tuples for one sequence.

    Returns:
        List of gap description strings, e.g. ["6837", "6839-6845 (7)"].

    Examples:
        >>> seq = [("a", "p", 1, dt), ("a", "p", 2, dt), ("a", "p", 5, dt)]
        >>> find_gaps(seq)
        ['3', '4']
        >>> seq = [("a", "p", 1, dt), ("a", "p", 10, dt)]
        >>> find_gaps(seq)
        ['2-9 (8)']
    """
    if len(seq) < 2:
        return []
    seq_nums = sorted({item[2] for item in seq})
    gaps: list[str] = []
    for i in range(len(seq_nums) - 1):
        current = seq_nums[i]
        nxt = seq_nums[i + 1]
        missing = nxt - current - 1
        if missing == 0:
            continue
        missing_start = current + 1
        missing_end = nxt - 1
        if missing <= 2:
            for n in range(missing_start, missing_end + 1):
                gaps.append(str(n))
        else:
            gaps.append(f"{missing_start}-{missing_end} ({missing})")
    return gaps


def print_summary(
    files: list[tuple[str, str, int, datetime]],
    seqs: list[list[tuple[str, str, int, datetime]]],
    show_gaps: bool = False,
) -> None:
    """Print summary table of detected sequences.

    For a single sequence the missing count appears on the header line.
    For multiple sequences it appears as an aligned column in each row.

    Args:
        files: All input files.
        seqs: Detected sequences sorted by length.
        show_gaps: If True, always show the per-sequence table (even for a
            single sequence) and add a line of missing sequence numbers under
            each sequence that has gaps.
    """
    n_seqs = len(seqs)
    missing_counts = [count_missing(seq) for seq in seqs]

    if n_seqs == 1:
        print(f"{len(files)} files, 1 sequence [{missing_counts[0]} missing]")
    else:
        print(f"{len(files)} files, {n_seqs} sequences")

    if n_seqs <= 1 and not show_gaps:
        return

    print()
    max_missing_width = max((len(f"[{m} missing]") for m in missing_counts), default=0)
    for i, (seq, missing) in enumerate(zip(seqs, missing_counts, strict=True), 1):
        first_seq, last_seq = seq[0][2], seq[-1][2]
        first_dt = seq[0][3].strftime("%Y-%m-%d")
        last_dt = seq[-1][3].strftime("%Y-%m-%d")
        dirs = _seq_directories(seq)
        dirs_str = ", ".join(dirs)
        missing_str = f"[{missing} missing]".ljust(max_missing_width)
        print(
            f"  {i:3d}  {len(seq):5d} files  seq {first_seq}..{last_seq}"
            f"  {missing_str}  ({first_dt} .. {last_dt})  [{dirs_str}]"
        )
        if show_gaps:
            gaps = find_gaps(seq)
            if gaps:
                print(f"         {', '.join(gaps)} missing in seq")
    print()


def print_columns(
    seqs: list[list[tuple[str, str, int, datetime]]],
) -> None:
    """Print sequences side by side in columnar format.

    Args:
        seqs: List of sequences to display in columns.
    """
    if not seqs:
        return
    columns: list[list[str]] = []
    col_widths: list[int] = []
    for i, seq in enumerate(seqs, 1):
        header = f"Seq {i} ({len(seq)})"
        lines = [header, "-" * len(header)]
        for path, _prefix, seq_num, dt in seq:
            name = Path(path).name
            dir_name = Path(path).parent.name
            lines.append(f"{seq_num:5d} {dt.strftime('%Y-%m-%d')} {dir_name}/{name}")
        columns.append(lines)
        col_widths.append(max(len(ln) for ln in lines))

    max_rows = max(len(c) for c in columns)
    gap = "  "
    for row in range(max_rows):
        parts = []
        for ci, col in enumerate(columns):
            cell = col[row] if row < len(col) else ""
            parts.append(cell.ljust(col_widths[ci]))
        print(gap.join(parts).rstrip())


def write_script(
    seqs: list[list[tuple[str, str, int, datetime]]],
    selected: list[int],
    target_base: str,
    output_path: str,
) -> None:
    """Write shell script to move selected sequences to separate directories.

    Selected sequences are moved to ``{target_base}_s{n}`` directories.

    Args:
        seqs: All detected sequences.
        selected: 1-based sequence indices to move.
        target_base: Base path for target directories.
        output_path: Path to output shell script.

    Raises:
        SystemExit: If script cannot be written or indices are invalid.
    """
    for s in selected:
        if s < 1 or s > len(seqs):
            raise SystemExit(f"Error: Sequence {s} out of range (1..{len(seqs)})")

    lines = ["#!/bin/bash", "umask 022", ""]
    for s in sorted(selected):
        target = f"{target_base}_s{s}"
        lines.append(f'mkdir -p "{target}"')
        for path, _prefix, _seq, _dt in seqs[s - 1]:
            name = Path(path).name
            dest = str(Path(target) / name)
            lines.append(f'mv -iv "{path}" "{dest}"')
        lines.append("")

    try:
        script = Path(output_path)
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"To review commands, see: {output_path}")
    except OSError as e:
        raise SystemExit(f"Error: Cannot write script '{output_path}': {e}") from e


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for sequences command.

    Args:
        parser: ArgumentParser instance to configure.
    """
    parser.add_argument(
        "json_files",
        nargs="+",
        help="One or more archive JSON metadata files",
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
        "-g",
        "--gaps",
        action="store_true",
        help="Show missing sequence numbers under each sequence in the summary",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Show full columnar listing of sequences",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        metavar="FILE",
        help="Write move commands to shell script",
    )
    parser.add_argument(
        "-S",
        "--select",
        type=int,
        action="append",
        default=None,
        metavar="N",
        help="Sequence number to move (1-based, repeatable; requires -o)",
    )
    parser.add_argument(
        "-t",
        "--target",
        type=str,
        default=None,
        metavar="DIR",
        help="Base directory for moved sequences (default: most common dir of seq 1)",
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed command-line arguments.

    Raises:
        SystemExit: If any argument is invalid.
    """
    for json_file in args.json_files:
        if not Path(json_file).is_file():
            raise SystemExit(f"Error: JSON file not found: {json_file}")
    if args.select and not args.output:
        raise SystemExit("Error: -S/--select requires -o/--output")
    if args.output and not args.select:
        raise SystemExit("Error: -o/--output requires -S/--select")


def run(args: argparse.Namespace) -> int:
    """Execute sequences command with parsed arguments.

    Pools all matching files, detects interleaved sequences, and optionally
    generates move commands to separate them.

    Args:
        args: Parsed command-line arguments with fields:
            - json_files: Paths to archive JSON metadata files
            - filter: Optional list of path substring filters
            - gaps: Whether to show missing sequence numbers in the summary
            - list: Whether to show columnar listing
            - output: Optional path to output shell script
            - select: Optional list of sequence indices to move
            - target: Optional base directory for moved sequences

    Returns:
        int: os.EX_OK on success.

    Raises:
        SystemExit: If arguments are invalid or no data found.
    """
    validate_args(args)

    files = load_files(args.json_files, args.filter)
    if not files:
        raise SystemExit("Error: No entries with sequence numbers found")

    seqs = detect_sequences(files)
    print_summary(files, seqs, show_gaps=args.gaps)

    if args.list:
        print_columns(seqs)
        print()

    if args.output:
        if len(seqs) <= 1:
            raise SystemExit("Error: Only one sequence found, nothing to separate")
        # Derive target base from most common dir of main sequence, or user override
        target_base = args.target
        if not target_base:
            main_dirs = _seq_directories(seqs[0])
            target_base = main_dirs[0] if main_dirs else "sequences"
        write_script(seqs, args.select, target_base, args.output)

    return os.EX_OK
