"""locate - Find archive directories for new photos using series-based gap-fitting.

Groups new photos by filename prefix into series, then finds gaps in
archive numbering where each series fits. Validates matches with temporal
ordering at series boundaries. Splits series when archive already contains
files within the series range.

Usage:
    photos locate /path/to/new/photos archive.json
    photos locate /path/to/new/photos archive.json --list
    photos locate /path/to/new/photos archive.json -f canon-eos -f apple-ipad
    photos locate /path/to/new/photos archive.json --output move.sh
    photos locate /path/to/new/photos archive.json --no-prefix
    photos locate /path/to/new/photos archive.json --exif
"""

import argparse
import bisect
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from photos_manager.common import load_json, validate_directory

# Optional EXIF support
try:
    import piexif

    _PIEXIF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIEXIF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NewFile:
    """A new file to be placed into the archive."""

    path: str
    prefix: str | None  # e.g. "IMG_", None if no seq number
    seq: int | None
    date: datetime


@dataclass
class Series:
    """A group of new files sharing the same filename prefix."""

    prefix: str | None
    files: list[NewFile]
    seq_range: tuple[int, int] | None  # (min_seq, max_seq), None if no seq


@dataclass
class Collision:
    """A new file whose prefix+seq already exists in the archive."""

    new_file: NewFile
    archive_path: str  # full path in archive


@dataclass
class GapMatch:
    """A matched gap in an archive directory for a series."""

    directory: str
    gap: tuple[int | None, int | None]  # (before_seq, after_seq)
    time_ok: bool
    time_detail: str  # e.g. "ok", "FAIL", description


@dataclass
class SeriesResult:
    """Result of matching a series to archive directories."""

    series: Series
    matches: list[GapMatch] = field(default_factory=list)
    best_directory: str | None = None
    ambiguous: bool = False


# ---------------------------------------------------------------------------
# EXIF date reading
# ---------------------------------------------------------------------------


def _read_exif_date(path: str) -> datetime | None:
    """Try reading EXIF DateTimeOriginal. Returns None on any failure."""
    try:
        exif_dict = piexif.load(path)
        exif_ifd = exif_dict.get("Exif", {})
        dt_bytes = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        if dt_bytes:
            dt_str = dt_bytes.decode("ascii", errors="replace").strip("\x00 ")
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
            return dt.replace(tzinfo=UTC).astimezone()
    except Exception:
        return None
    return None


def read_file_date(path: str, *, use_exif: bool = False) -> datetime:
    """Read file date from EXIF (optional) or mtime.

    Args:
        path: Path to the file.
        use_exif: If True, try EXIF DateTimeOriginal first.

    Returns:
        Timezone-aware datetime.
    """
    if use_exif and _PIEXIF_AVAILABLE:
        exif_dt = _read_exif_date(path)
        if exif_dt is not None:
            return exif_dt
    mtime = Path(path).stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=UTC).astimezone()


# ---------------------------------------------------------------------------
# Series grouping
# ---------------------------------------------------------------------------

_PREFIX_SEQ_RE = re.compile(r"^(.*?)(\d+)\.[^.]+$")


def group_into_series(
    files: list[tuple[str, datetime]],
) -> list[Series]:
    """Group new files by filename prefix into series.

    Files with the same prefix form one series. Files without a sequence
    number become single-element series with prefix=None.

    Args:
        files: List of (path, date) tuples for new files.

    Returns:
        List of Series objects, sorted by prefix (None-prefix series last).
    """
    by_prefix: dict[str | None, list[NewFile]] = {}
    for path, date in files:
        name = Path(path).name
        m = _PREFIX_SEQ_RE.match(name)
        if m:
            prefix = m.group(1)
            seq = int(m.group(2))
        else:
            prefix = None
            seq = None
        nf = NewFile(path=path, prefix=prefix, seq=seq, date=date)
        by_prefix.setdefault(prefix, []).append(nf)

    result: list[Series] = []
    for prefix, nf_list in by_prefix.items():
        if prefix is None:
            # Each file without seq is its own single-element series
            for nf in nf_list:
                result.append(Series(prefix=None, files=[nf], seq_range=None))
        else:
            nf_list.sort(key=lambda f: f.seq or 0)
            seqs = [f.seq for f in nf_list if f.seq is not None]
            seq_range = (min(seqs), max(seqs)) if seqs else None
            result.append(Series(prefix=prefix, files=nf_list, seq_range=seq_range))

    # Sort: prefixed series first (alphabetically), then None-prefix
    result.sort(key=lambda s: (s.prefix is None, s.prefix or ""))
    return result


# ---------------------------------------------------------------------------
# Series splitting against archive
# ---------------------------------------------------------------------------


def _find_archive_entry_date(
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    directory: str,
    prefix: str,
    target_seq: int,
    *,
    match_prefix: bool = True,
) -> datetime | None:
    """Find datetime of an archive entry by prefix and sequence number.

    Args:
        dir_entries: Mapping of directory to sorted entry lists.
        directory: Archive directory to search.
        prefix: Filename prefix to match.
        target_seq: Sequence number to find.
        match_prefix: If True, require prefix match.

    Returns:
        Datetime of the matching entry, or None.
    """
    for dt, entry in dir_entries.get(directory, []):
        name = Path(str(entry["path"])).name
        m = _PREFIX_SEQ_RE.match(name)
        if m:
            p, s = m.group(1), int(m.group(2))
            if s == target_seq and (not match_prefix or p == prefix):
                return dt
    return None


def _make_sub_series(prefix: str, files: list[NewFile]) -> Series:
    """Create a Series from a group of files sharing a prefix."""
    seqs = [f.seq for f in files if f.seq is not None]
    return Series(prefix=prefix, files=files, seq_range=(min(seqs), max(seqs)))


def _split_at_barriers(remaining: list[NewFile], barriers: list[int], prefix: str) -> list[Series]:
    """Split files into sub-series at barrier positions."""
    remaining.sort(key=lambda f: f.seq or 0)
    sub_series: list[Series] = []
    current_files: list[NewFile] = []

    for f in remaining:
        cur_seq = f.seq or 0
        if current_files:
            last_seq = current_files[-1].seq or 0
            if any(b for b in barriers if last_seq < b < cur_seq):
                sub_series.append(_make_sub_series(prefix, current_files))
                current_files = []
        current_files.append(f)

    if current_files:
        sub_series.append(_make_sub_series(prefix, current_files))
    return sub_series


def split_series_against_archive(
    series: Series,
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    *,
    match_prefix: bool = True,
) -> tuple[list[Series], list[Collision]]:
    """Split a series at collision points with archive entries.

    Checks if any sequence numbers in the series range exist in the archive
    (with matching prefix). Colliding new files are removed, and the remaining
    files are split into sub-series at collision boundaries.

    Args:
        series: The series to split.
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        match_prefix: If True, only check entries with matching prefix.

    Returns:
        Tuple of (sub_series_list, collision_list).
    """
    if series.prefix is None or series.seq_range is None:
        return [series], []

    prefix = series.prefix
    min_seq, max_seq = series.seq_range

    # Collect all archive seqs with this prefix across all directories
    archive_seqs_in_range: set[int] = set()
    archive_seq_dirs: dict[int, str] = {}  # seq -> first directory found
    for d, pairs in dir_seqs.items():
        for p, s in pairs:
            if match_prefix and p != prefix:
                continue
            if min_seq <= s <= max_seq:
                archive_seqs_in_range.add(s)
                if s not in archive_seq_dirs:
                    archive_seq_dirs[s] = d

    if not archive_seqs_in_range:
        return [series], []

    # Separate collisions from remaining files
    new_seqs = {f.seq for f in series.files if f.seq is not None}
    collision_seqs = new_seqs & archive_seqs_in_range
    collisions: list[Collision] = []
    remaining: list[NewFile] = []
    for f in series.files:
        if f.seq in collision_seqs:
            # Find archive path for collision reporting
            d = archive_seq_dirs.get(f.seq, "")
            # Build approximate archive path
            archive_path = f"{d}/{prefix}{f.seq:04d}" if d else f"{prefix}{f.seq}"
            collisions.append(Collision(new_file=f, archive_path=archive_path))
        else:
            remaining.append(f)

    if not remaining:
        return [], collisions

    barriers = sorted(archive_seqs_in_range)
    sub_series = _split_at_barriers(remaining, barriers, prefix)
    return sub_series, collisions


# ---------------------------------------------------------------------------
# Gap-fitting
# ---------------------------------------------------------------------------


def find_gap_match(
    series: Series,
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    *,
    match_prefix: bool = True,
) -> list[GapMatch]:
    """Find archive directories with a matching gap for a series.

    For each directory containing files with the same prefix, checks whether
    the series range fits in a gap in the archive numbering. Validates
    temporal ordering at gap boundaries.

    Args:
        series: The series to match.
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        dir_entries: Mapping of directory to sorted entry lists.
        match_prefix: If True, only match entries with the same prefix.

    Returns:
        List of GapMatch objects, sorted by gap tightness (tightest first).
    """
    if series.prefix is None or series.seq_range is None:
        return []

    prefix = series.prefix
    min_seq, max_seq = series.seq_range
    first_file = min(series.files, key=lambda f: f.seq or 0)
    last_file = max(series.files, key=lambda f: f.seq or 0)
    matches: list[GapMatch] = []

    for d, pairs in dir_seqs.items():
        # Filter seqs by prefix (pairs are already sorted by seq)
        seqs = [s for p, s in pairs if p == prefix] if match_prefix else [s for _, s in pairs]
        if not seqs:
            continue

        # Check for clean gap: no archive entries in [min_seq, max_seq]
        pos_lo = bisect.bisect_left(seqs, min_seq)
        pos_hi = bisect.bisect_right(seqs, max_seq)
        if pos_lo != pos_hi:
            continue

        before_seq: int | None = seqs[pos_lo - 1] if pos_lo > 0 else None
        after_seq: int | None = seqs[pos_lo] if pos_lo < len(seqs) else None
        if before_seq is None and after_seq is None:
            continue

        # Temporal validation at both gap boundaries
        time_ok = True
        time_detail = "ok"
        for boundary_seq, edge_file, is_before in [
            (before_seq, first_file, True),
            (after_seq, last_file, False),
        ]:
            if not time_ok or boundary_seq is None:
                continue
            boundary_dt = _find_archive_entry_date(
                dir_entries, d, prefix, boundary_seq, match_prefix=match_prefix
            )
            if boundary_dt is None:
                continue
            bad = edge_file.date <= boundary_dt if is_before else edge_file.date >= boundary_dt
            if bad:
                time_ok = False
                label = "before" if is_before else "after"
                time_detail = (
                    f"{Path(edge_file.path).name}"
                    f" ({edge_file.date.strftime('%Y-%m-%d')})"
                    f" {label} archive seq {boundary_seq}"
                    f" ({boundary_dt.strftime('%Y-%m-%d')})"
                )

        matches.append(GapMatch(d, (before_seq, after_seq), time_ok, time_detail))

    # Sort by gap tightness (tightest first)
    def gap_size(m: GapMatch) -> int:
        lo, hi = m.gap
        if lo is not None and hi is not None:
            return hi - lo
        return 999_999_999

    matches.sort(key=gap_size)
    return matches


def match_single_file(
    nf: NewFile,
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    context: int,
) -> str | None:
    """Match a single file without sequence number by timestamp proximity.

    Args:
        nf: The new file to match.
        sorted_entries: Archive entries sorted by date.
        context: Number of neighbors to consider.

    Returns:
        Best matching directory path, or None.
    """
    pos = bisect.bisect_left([dt for dt, _ in sorted_entries], nf.date)
    start = max(0, pos - context)
    end = min(len(sorted_entries), pos + context)
    neighbors = sorted_entries[start:end]
    if not neighbors:
        return None
    _, closest = min(neighbors, key=lambda x: abs((nf.date - x[0]).total_seconds()))
    return str(Path(str(closest["path"])).parent)


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


def scan_new_files(directory: str, *, use_exif: bool = False) -> list[tuple[str, datetime]]:
    """Scan directory recursively for files and return paths with datetimes.

    Args:
        directory: Path to directory with new photos.
        use_exif: If True, read dates from EXIF metadata (fallback to mtime).

    Returns:
        List of (file_path, datetime) tuples sorted by date.
    """
    results: list[tuple[str, datetime]] = []
    dir_path = Path(directory)
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            dt = read_file_date(str(file_path), use_exif=use_exif)
        except OSError as e:
            print(f"Warning: Cannot stat {file_path}: {e}", file=sys.stderr)
            continue
        results.append((str(file_path), dt))
    results.sort(key=lambda x: x[1])
    return results


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


def build_directory_seqs(
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
) -> dict[str, list[tuple[str | None, int]]]:
    """Pre-compute sorted (prefix, sequence_number) pairs per directory.

    Extracts filename prefix and sequence number from every archive entry
    once, so that gap-fitting can do fast lookups without repeated regex calls.

    Args:
        dir_entries: Mapping of directory path to sorted (datetime, entry) lists.

    Returns:
        Mapping of directory path to sorted list of (prefix, seq) tuples.
    """
    result: dict[str, list[tuple[str | None, int]]] = {}
    for d, entries in dir_entries.items():
        pairs: list[tuple[str | None, int]] = []
        for _, e in entries:
            m = _PREFIX_SEQ_RE.match(Path(str(e["path"])).name)
            if m:
                pairs.append((m.group(1), int(m.group(2))))
        if pairs:
            pairs.sort(key=lambda x: x[1])
            result[d] = pairs
    return result


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
        help="Show detailed listing with archive context per series",
    )
    parser.add_argument(
        "-N",
        "--context",
        type=int,
        default=5,
        help="Number of archive entries to show before/after each gap (default: 5)",
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
        "--no-prefix",
        action="store_true",
        help="Disable prefix matching (match by sequence number only)",
    )
    parser.add_argument(
        "--exif",
        action="store_true",
        help="Read dates from EXIF metadata instead of file modification time",
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
    if args.exif and not _PIEXIF_AVAILABLE:  # pragma: no cover
        raise SystemExit("Error: --exif requires piexif (pip install photos-manager-cli[exif])")


# ---------------------------------------------------------------------------
# Series-based matching orchestration
# ---------------------------------------------------------------------------


def _match_all_series(
    series_list: list[Series],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_seqs: dict[str, list[tuple[str | None, int]]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    context: int,
    *,
    match_prefix: bool = True,
) -> list[SeriesResult]:
    """Match all series to archive directories.

    Args:
        series_list: List of (sub-)series to match.
        sorted_entries: Archive entries sorted by date.
        dir_seqs: Pre-built mapping of directory to sorted (prefix, seq) lists.
        dir_entries: Mapping of directory to sorted entry lists.
        context: Number of neighbors for single-file fallback.
        match_prefix: If True, require prefix match in gap-fitting.

    Returns:
        List of SeriesResult objects.
    """
    results: list[SeriesResult] = []
    for s in series_list:
        sr = SeriesResult(series=s)
        if s.prefix is not None and s.seq_range is not None:
            gap_matches = find_gap_match(s, dir_seqs, dir_entries, match_prefix=match_prefix)
            sr.matches = gap_matches
            # Filter to time_ok matches first
            ok_matches = [m for m in gap_matches if m.time_ok]
            if len(ok_matches) == 1:
                sr.best_directory = ok_matches[0].directory
            elif len(ok_matches) > 1:
                sr.best_directory = ok_matches[0].directory  # tightest gap
                sr.ambiguous = True
            elif len(gap_matches) == 1:
                # Single match but time failed — still report it
                sr.best_directory = gap_matches[0].directory
            elif len(gap_matches) > 1:
                sr.ambiguous = True
        else:
            # Single file without seq — timestamp fallback
            nf = s.files[0]
            best_dir = match_single_file(nf, sorted_entries, context)
            if best_dir:
                sr.best_directory = best_dir
        results.append(sr)
    return results


def _format_series_label(s: Series) -> str:
    """Format a series label for output.

    Args:
        s: Series to format.

    Returns:
        Formatted string like "IMG_ [42..44]" or "notes.txt".
    """
    if s.prefix is not None and s.seq_range is not None:
        lo, hi = s.seq_range
        if lo == hi:
            return f"{s.prefix}[{lo}]"
        return f"{s.prefix}[{lo}..{hi}]"
    return Path(s.files[0].path).name


def _print_series_default(
    results: list[SeriesResult],
    collisions: list[Collision],
) -> None:
    """Print default mode output: series -> directory mapping.

    Args:
        results: List of SeriesResult objects.
        collisions: List of collisions.
    """
    labels = [_format_series_label(r.series) for r in results]
    label_w = max((len(lb) for lb in labels), default=0)
    counts = [
        f"{len(r.series.files)} file{'s' if len(r.series.files) != 1 else ''}" for r in results
    ]
    count_w = max((len(c) for c in counts), default=0)

    for r, label, count in zip(results, labels, counts, strict=True):
        if r.series.prefix is not None and r.series.seq_range is not None:
            count_str = f"{count:>{count_w}}"
        else:
            count_str = " " * count_w
        if r.ambiguous:
            dirs = ", ".join(m.directory for m in r.matches)
            print(f"  {label:<{label_w}}  {count_str}  ->  {dirs}  (ambiguous)")
        elif r.best_directory:
            suffix = ""
            if r.series.prefix is None:
                suffix = "  (timestamp)"
            print(f"  {label:<{label_w}}  {count_str}  ->  {r.best_directory}{suffix}")
        else:
            print(f"  {label:<{label_w}}  {count_str}  ->  (no match found)")

    if collisions:
        print(f"\nCollisions ({len(collisions)}):")
        for c in collisions:
            name = Path(c.new_file.path).name
            print(f"  {name:<{label_w}}  ->  {c.archive_path}")


def _print_series_list(
    results: list[SeriesResult],
    collisions: list[Collision],
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    dir_entries: dict[str, list[tuple[datetime, dict[str, str | int]]]],
    context: int,
) -> None:
    """Print list mode output: per-series context with archive entries.

    Args:
        results: List of SeriesResult objects.
        collisions: List of collisions.
        sorted_entries: Archive entries sorted by date.
        dir_entries: Mapping of directory to sorted entry lists.
        context: Number of archive entries to show before/after gap.
    """
    collision_seqs: dict[str, set[int]] = {}
    for c in collisions:
        prefix = c.new_file.prefix or ""
        collision_seqs.setdefault(prefix, set()).add(c.new_file.seq or 0)

    for r in results:
        label = _format_series_label(r.series)

        if r.ambiguous:
            print(f"\n--- {label} -- ambiguous ---\n")
            for i, m in enumerate(r.matches, 1):
                print(
                    f"  Candidate {i}: {m.directory}"
                    f"  gap {_format_gap(m.gap)}  time {m.time_detail}"
                )
            print("  Use -f to narrow results.")
            continue

        if r.best_directory and r.matches:
            best_match = next((m for m in r.matches if m.directory == r.best_directory), None)
            if best_match:
                print(
                    f"\n--- {label} -> {r.best_directory}"
                    f" (gap {_format_gap(best_match.gap)},"
                    f" time {best_match.time_detail}) ---\n"
                )
                _print_gap_context(
                    dir_entries.get(r.best_directory, []),
                    r.series,
                    collision_seqs.get(r.series.prefix or "", set()),
                    context,
                )
                continue

        if r.best_directory and r.series.prefix is None:
            nf = r.series.files[0]
            # Compute nearest delta inline
            pos = bisect.bisect_left([dt for dt, _ in sorted_entries], nf.date)
            deltas = []
            if pos > 0:
                deltas.append(abs((nf.date - sorted_entries[pos - 1][0]).total_seconds()))
            if pos < len(sorted_entries):
                deltas.append(abs((nf.date - sorted_entries[pos][0]).total_seconds()))
            secs = min(deltas) if deltas else 0
            if secs < 60:
                delta = f"{int(secs)}s"
            elif secs < 3600:
                delta = f"{int(secs // 60)}min"
            else:
                delta = f"{secs / 3600:.1f}h"
            print(f"\n--- {label} -> {r.best_directory} (timestamp, nearest ~{delta}) ---\n")
            _print_timestamp_context(nf, sorted_entries, context)
            continue

        print(f"\n--- {label} -> (no match found) ---\n")


def _format_gap(gap: tuple[int | None, int | None]) -> str:
    """Format gap boundary as 'lo..hi' string."""
    lo, hi = gap
    if lo is not None and hi is not None:
        return f"{lo}..{hi}"
    return str(gap)


def _print_gap_context(
    entries: list[tuple[datetime, dict[str, str | int]]],
    series: Series,
    collision_seqs: set[int],
    context: int,
) -> None:
    """Print archive entries around a gap with new files interleaved.

    Args:
        entries: Archive entries for the matched directory, sorted by date.
        series: The series being matched.
        collision_seqs: Sequence numbers that caused collisions.
        context: Number of archive entries to show before/after.
    """
    pat = _PREFIX_SEQ_RE

    # Build timeline items: (datetime, display_text, is_new, seq)
    timeline: list[tuple[datetime, str, bool, int | None]] = []

    for dt, entry in entries:
        path_str = str(entry["path"])
        name = Path(path_str).name
        m = pat.match(name)
        seq = int(m.group(2)) if m else None
        collision_mark = ""
        if seq is not None and seq in collision_seqs:
            collision_mark = f"  [collision: {series.prefix}{seq:04d}]"
        timeline.append((dt, f"{path_str}{collision_mark}", False, seq))

    for nf in series.files:
        timeline.append((nf.date, Path(nf.path).name, True, nf.seq))

    timeline.sort(key=lambda x: x[0])

    # Find indices of new files
    new_indices = [i for i, (_, _, is_new, _) in enumerate(timeline) if is_new]
    if not new_indices:
        return

    # Mark N archive entries before first and after last new file as visible
    visible: set[int] = set()
    for ni in new_indices:
        visible.add(ni)

    first_new = min(new_indices)
    last_new = max(new_indices)

    count = 0
    j = first_new - 1
    while j >= 0 and count < context:
        visible.add(j)
        if not timeline[j][2]:
            count += 1
        j -= 1

    count = 0
    j = last_new + 1
    while j < len(timeline) and count < context:
        visible.add(j)
        if not timeline[j][2]:
            count += 1
        j += 1

    for idx in sorted(visible):
        dt, text, is_new, _seq = timeline[idx]
        marker = ">" if is_new else " "
        suffix = " <" if is_new else ""
        print(f"{marker} {dt.strftime('%Y-%m-%d %H:%M')}  {text}{suffix}")


def _print_timestamp_context(
    nf: NewFile,
    sorted_entries: list[tuple[datetime, dict[str, str | int]]],
    context: int,
) -> None:
    """Print archive context around a timestamp-matched file."""
    pos = bisect.bisect_left([dt for dt, _ in sorted_entries], nf.date)
    start = max(0, pos - context)
    end = min(len(sorted_entries), pos + context)
    for i in range(start, pos):
        dt, entry = sorted_entries[i]
        print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {entry['path']}")
    print(f"> {nf.date.strftime('%Y-%m-%d %H:%M')}  {Path(nf.path).name} <")
    for i in range(pos, end):
        dt, entry = sorted_entries[i]
        print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {entry['path']}")


def run(args: argparse.Namespace) -> int:
    """Execute locate command with parsed arguments.

    Groups new files into series by filename prefix, finds gaps in archive
    numbering where each series fits, and validates with temporal ordering.

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to directory with new photos
            - json_files: Paths to archive JSON metadata files
            - list: Whether to show detailed per-series listing
            - context: Number of archive entries around each gap
            - filter: Optional list of path substring filters (OR logic)
            - output: Optional path to output shell script
            - no_prefix: Whether to disable prefix matching
            - exif: Whether to use EXIF dates

    Returns:
        int: os.EX_OK on success.

    Raises:
        SystemExit: If arguments are invalid or no files found.
    """
    validate_args(args)

    sorted_entries = load_archive_entries(args.json_files, args.filter)
    if not sorted_entries:
        raise SystemExit("Error: No archive entries found (check JSON files and filter)")

    new_files = scan_new_files(args.directory, use_exif=getattr(args, "exif", False))
    if not new_files:
        raise SystemExit(f"Error: No files found in {args.directory}")

    dir_entries = build_directory_entries(sorted_entries)
    dir_seqs = build_directory_seqs(dir_entries)

    print(f"Loaded {len(sorted_entries)} archive entries.")
    print(f"Scanned {len(new_files)} new files in {args.directory}.")
    print()

    match_prefix = not getattr(args, "no_prefix", False)

    # Group into series
    series_list = group_into_series(new_files)

    # Split against archive and collect collisions
    all_sub_series: list[Series] = []
    all_collisions: list[Collision] = []
    for s in series_list:
        sub, colls = split_series_against_archive(s, dir_seqs, match_prefix=match_prefix)
        all_sub_series.extend(sub)
        all_collisions.extend(colls)

    # Match all series
    results = _match_all_series(
        all_sub_series,
        sorted_entries,
        dir_seqs,
        dir_entries,
        args.context,
        match_prefix=match_prefix,
    )

    if args.output:
        # Check for ambiguous placements
        ambiguous = [r for r in results if r.ambiguous]
        if ambiguous:
            print("Error: Ambiguous placement for:", file=sys.stderr)
            for r in ambiguous:
                label = _format_series_label(r.series)
                dirs = ", ".join(m.directory for m in r.matches)
                print(f"  {label}: {dirs}", file=sys.stderr)
            raise SystemExit("Use -f to narrow results")
        # Build placements (exclude unmatched and collisions)
        placements: list[tuple[str, str]] = []
        for r in results:
            if r.best_directory:
                for nf in r.series.files:
                    placements.append((nf.path, r.best_directory))
        if placements:
            _print_series_default(results, all_collisions)
            _write_script(placements, args.output)
    elif args.list:
        _print_series_list(
            results,
            all_collisions,
            sorted_entries,
            dir_entries,
            args.context,
        )
    else:
        _print_series_default(results, all_collisions)

    return os.EX_OK
