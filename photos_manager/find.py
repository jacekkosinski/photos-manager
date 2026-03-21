"""Find duplicate and missing files by comparing with archive metadata.

This module provides functionality to compare files in a directory against
archive metadata (JSON created by index) to identify:
- Duplicates: Files that exist in the archive
- Missing: Files that do NOT exist in the archive

The comparison uses file size as a first filter, then SHA1 and MD5 checksums
for exact matching. Optional filters can narrow results to duplicates with
filename or timestamp differences, or to a specific camera model.
"""

import argparse
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

from photos_manager.common import (
    TS_FMT,
    format_count,
    format_datetime_change,
    human_size,
    load_json,
    scan_files,
    validate_directory,
)

# Optional EXIF support (same guard pattern as exifdates.py)
try:
    import piexif

    _PIEXIF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIEXIF_AVAILABLE = False


def scan_directory(directory: str) -> list[dict[str, str | int]]:
    """Scan directory recursively and collect file metadata.

    Args:
        directory: Path to directory to scan

    Returns:
        List of file metadata dictionaries with keys:
        path (str), sha1 (str), md5 (str), date (str), size (int)
    """
    validate_directory(directory)
    return scan_files(directory, resolve_paths=True)


def load_psv(file_path: str) -> list[dict[str, str | int]]:
    """Load file metadata from a PSV file (path|sha1|md5|date|size).

    Args:
        file_path: Path to PSV file

    Returns:
        List of file metadata dictionaries with keys:
        path (str), sha1 (str), md5 (str), date (str), size (int)

    Raises:
        SystemExit: If the file cannot be opened
    """
    files: list[dict[str, str | int]] = []
    try:
        with Path(file_path).open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                if len(parts) != 5:
                    print(
                        f"Warning: Skipping malformed line {lineno} in {file_path}: "
                        f"expected 5 fields, got {len(parts)}",
                        file=sys.stderr,
                    )
                    continue
                path, sha1, md5, date, size_str = parts
                try:
                    size = int(size_str)
                except ValueError:
                    print(
                        f"Warning: Skipping line {lineno} in {file_path}: "
                        f"invalid size value {size_str!r}",
                        file=sys.stderr,
                    )
                    continue
                files.append({"path": path, "sha1": sha1, "md5": md5, "date": date, "size": size})
    except OSError as e:
        raise SystemExit(f"Error: Could not open PSV file {file_path}: {e}") from e
    return files


def build_archive_index(
    archive_data: list[dict[str, str | int]],
) -> tuple[dict[int, list[dict[str, str | int]]], dict[tuple[str, str], dict[str, str | int]]]:
    """Build indexes for efficient archive lookup.

    Args:
        archive_data: List of archive file metadata

    Returns:
        Tuple of (size_index, checksum_index):
        - size_index: Maps file size to list of archive entries
        - checksum_index: Maps (sha1, md5) tuple to archive entry
    """
    size_index: dict[int, list[dict[str, str | int]]] = {}
    checksum_index: dict[tuple[str, str], dict[str, str | int]] = {}

    for entry in archive_data:
        # Build size index
        size = entry["size"]
        if not isinstance(size, int):
            continue
        if size not in size_index:
            size_index[size] = []
        size_index[size].append(entry)

        # Build checksum index
        sha1 = entry.get("sha1")
        md5 = entry.get("md5")
        if isinstance(sha1, str) and isinstance(md5, str):
            checksum_index[(sha1, md5)] = entry

    return size_index, checksum_index


def find_duplicates(
    scanned_files: list[dict[str, str | int]],
    size_index: dict[int, list[dict[str, str | int]]],
    checksum_index: dict[tuple[str, str], dict[str, str | int]],
) -> tuple[list[tuple[dict[str, str | int], dict[str, str | int]]], list[dict[str, str | int]]]:
    """Find duplicates and missing files by comparing scanned files with archive.

    Args:
        scanned_files: List of scanned file metadata
        size_index: Size-based index of archive
        checksum_index: Checksum-based index of archive

    Returns:
        Tuple of (duplicates, missing):
        - duplicates: List of (scanned_entry, archive_entry) tuples
        - missing: List of scanned entries not in archive
    """
    duplicates = []
    missing = []

    for scanned in scanned_files:
        size = scanned["size"]
        if not isinstance(size, int):
            continue

        # First check: size match
        if size not in size_index:
            missing.append(scanned)
            continue

        # Second check: checksum match
        sha1 = scanned.get("sha1")
        md5 = scanned.get("md5")
        if not isinstance(sha1, str) or not isinstance(md5, str):
            missing.append(scanned)
            continue

        checksum_key = (sha1, md5)
        if checksum_key in checksum_index:
            archive_entry = checksum_index[checksum_key]
            duplicates.append((scanned, archive_entry))
        else:
            missing.append(scanned)

    return duplicates, missing


def normalize_camera_slug(make: str, model: str) -> str:
    """Normalise EXIF Make/Model into a URL-safe slug.

    Args:
        make: Camera manufacturer string (e.g. ``"Canon"``).
        model: Camera model string (e.g. ``"Canon EOS 5D Mark IV"``).

    Returns:
        Slug such as ``"canon-eos-5d-mark-iv"``.

    Examples:
        >>> normalize_camera_slug("Canon", "Canon EOS 5D Mark IV")
        'canon-eos-5d-mark-iv'
        >>> normalize_camera_slug("Apple", "iPhone 14 Pro")
        'apple-iphone-14-pro'
        >>> normalize_camera_slug("SONY", "DSC-W170")
        'sony-dsc-w170'
    """
    make_clean = make.strip("\x00 ").lower()
    model_clean = model.strip("\x00 ").lower()

    # Strip make prefix from model if present
    if model_clean.startswith(make_clean):
        model_part = model_clean[len(make_clean) :].strip("\x00 ")
    else:
        model_part = model_clean

    combined = f"{make_clean}-{model_part}" if model_part else make_clean

    # Replace separator characters and collapse repeated hyphens
    for ch in (" ", ".", "_", "/"):
        combined = combined.replace(ch, "-")
    while "--" in combined:
        combined = combined.replace("--", "-")
    return combined.strip("-")


# Marker and TIFF magic bytes used to locate raw EXIF data in HEIC/HEIF files.
_EXIF_HEADER = b"Exif\x00\x00"
_TIFF_HEADERS = (b"II\x2a\x00", b"MM\x00\x2a")
# Read at most 8 MB when searching for an EXIF block in non-JPEG containers.
_EXIF_SCAN_LIMIT = 8 * 1024 * 1024


def _find_exif_in_bytes(data: bytes) -> bytes | None:
    r"""Find a raw EXIF block inside arbitrary binary data.

    Searches for the ``Exif\x00\x00`` marker immediately followed by a valid
    TIFF header (little-endian ``II\x2a\x00`` or big-endian ``MM\x00\x2a``).
    This allows extracting EXIF from HEIC/HEIF files, where the EXIF block is
    embedded inside the ISOBMFF ``mdat`` box.

    Args:
        data: Binary data to search.

    Returns:
        Raw EXIF bytes starting from the TIFF header, or ``None`` if not found.

    Examples:
        >>> _find_exif_in_bytes(b"junk" + b"Exif\x00\x00" + b"II\x2a\x00rest") is not None
        True
        >>> _find_exif_in_bytes(b"no exif here") is None
        True
    """
    offset = 0
    while True:
        idx = data.find(_EXIF_HEADER, offset)
        if idx == -1:
            return None
        start = idx + len(_EXIF_HEADER)
        if data[start : start + 4] in _TIFF_HEADERS:
            return data[start:]
        offset = idx + 1


def read_camera_slug(file_path: str) -> str | None:
    """Read EXIF Make/Model from a JPEG, TIFF, or HEIC/HEIF file and return a normalised slug.

    Tries ``piexif.load()`` first (handles JPEG/TIFF).  When that fails —
    e.g. for HEIC/HEIF files whose container piexif cannot parse — falls back
    to scanning the first ``_EXIF_SCAN_LIMIT`` bytes of the file for a raw
    EXIF block and loading it directly.

    Args:
        file_path: Path to the image file.

    Returns:
        Camera slug (e.g. ``"apple-iphone-14-pro"``) or ``None`` when piexif
        is unavailable, the file has no Make/Model tags, or an error occurs.
    """
    if not _PIEXIF_AVAILABLE:  # pragma: no cover
        return None
    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        # piexif cannot parse this container (e.g. HEIC/HEIF) — search for a
        # raw EXIF block embedded in the binary data.
        try:
            raw_data = Path(file_path).read_bytes()[:_EXIF_SCAN_LIMIT]
            exif_bytes = _find_exif_in_bytes(raw_data)
            if exif_bytes is None:
                return None
            exif_dict = piexif.load(exif_bytes)
        except Exception:
            return None
    try:
        ifd = exif_dict.get("0th", {})
        make_raw = ifd.get(piexif.ImageIFD.Make)
        model_raw = ifd.get(piexif.ImageIFD.Model)
        if not make_raw or not model_raw:
            return None
        make = make_raw.decode("ascii", errors="replace").strip("\x00 ")
        model = model_raw.decode("ascii", errors="replace").strip("\x00 ")
        if not make:
            return None
        return normalize_camera_slug(make, model)
    except Exception:
        return None


def compute_camera_stats(
    files: list[dict[str, str | int]],
) -> dict[str, tuple[int, int, str | None, str | None]]:
    """Aggregate file count, total size, and date range per camera slug.

    Args:
        files: List of file metadata dicts with at least ``"path"``, ``"size"``,
            and ``"date"`` keys.

    Returns:
        Mapping of camera slug → ``(count, total_bytes, date_min, date_max)``.
        Files whose EXIF cannot be read are counted under ``"unknown"``.
    """
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    date_mins: dict[str, str] = {}
    date_maxs: dict[str, str] = {}

    for entry in files:
        slug = read_camera_slug(str(entry["path"])) or "unknown"
        size = int(entry.get("size", 0))
        date_str = str(entry.get("date", ""))
        date_val: str | None = date_str[:10] if len(date_str) >= 10 else None

        counts[slug] = counts.get(slug, 0) + 1
        sizes[slug] = sizes.get(slug, 0) + size
        if date_val is not None:
            date_mins[slug] = min(date_mins.get(slug, date_val), date_val)
            date_maxs[slug] = max(date_maxs.get(slug, date_val), date_val)

    return {
        slug: (counts[slug], sizes[slug], date_mins.get(slug), date_maxs.get(slug))
        for slug in counts
    }


def group_files_by_directory(
    files: list[dict[str, str | int]],
) -> dict[str, list[dict[str, str | int]]]:
    """Group files by their parent directory.

    Args:
        files: List of file metadata dictionaries

    Returns:
        Dictionary mapping parent directory paths to lists of file entries
    """
    groups: dict[str, list[dict[str, str | int]]] = {}
    for file_entry in files:
        parent_dir = str(Path(str(file_entry["path"])).parent)
        if parent_dir not in groups:
            groups[parent_dir] = []
        groups[parent_dir].append(file_entry)
    return groups


def assign_directory_numbers(
    file_groups: dict[str, list[dict[str, str | int]]], start: int = 1
) -> dict[str, str]:
    """Assign sequential directory numbers to each source directory.

    Args:
        file_groups: Dictionary mapping source directories to file lists
        start: Starting number for directory numbering (default: 1)

    Returns:
        Dictionary mapping source directory paths to numbered subdirectory names (e.g., "dir00001")
    """
    dir_mapping: dict[str, str] = {}
    for idx, source_dir in enumerate(sorted(file_groups.keys()), start=start):
        dir_mapping[source_dir] = f"dir{idx:05d}"
    return dir_mapping


def generate_file_operation_commands(
    files: list[dict[str, str | int]],
    target_dir: str,
    dir_mapping: dict[str, str],
    operation: str = "mv",
) -> list[str]:
    """Generate file operation commands (mv or cp) for organizing files.

    Args:
        files: List of file metadata dictionaries
        target_dir: Target directory path
        dir_mapping: Mapping of source directories to numbered subdirectories
        operation: File operation to use - "mv" for move or "cp" for copy

    Returns:
        List of shell commands (mkdir and mv/cp)

    Raises:
        ValueError: If operation is not "mv" or "cp"
    """
    if operation not in ("mv", "cp"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'mv' or 'cp'")

    commands: list[str] = []
    created_dirs: set[str] = set()
    cmd_flags = "-iv" if operation == "mv" else "-pv"

    # Group files by source directory
    file_groups = group_files_by_directory(files)

    # Generate commands for each source directory
    for source_dir in sorted(file_groups.keys()):
        target_subdir = dir_mapping[source_dir]
        target_path = Path(target_dir) / target_subdir

        # Add mkdir command if not already created
        if target_subdir not in created_dirs:
            commands.append(f"mkdir -p {shlex.quote(str(target_path))}")
            created_dirs.add(target_subdir)

        # Add file operation commands for each file
        for file_entry in file_groups[source_dir]:
            source_path = str(file_entry["path"])
            filename = Path(source_path).name
            target_file = target_path / filename
            quoted_source = shlex.quote(source_path)
            quoted_target = shlex.quote(str(target_file))
            commands.append(f"{operation} {cmd_flags} {quoted_source} {quoted_target}")

    return commands


def _display_path(abs_path: str) -> str:
    """Return path relative to the current working directory.

    Args:
        abs_path: Absolute path to make relative.

    Returns:
        Path relative to CWD, or abs_path if not possible.

    Examples:
        >>> import os
        >>> _display_path(os.path.join(os.getcwd(), "scan", "file.txt"))
        'scan/file.txt'
    """
    try:
        return str(Path(abs_path).relative_to(Path.cwd()))
    except ValueError:
        return abs_path


def _file_camera_slug(entry: dict[str, str | int]) -> str:
    """Return camera slug for a file entry, defaulting to ``"unknown"``.

    Args:
        entry: File metadata dict with at least ``"path"`` key.

    Returns:
        Camera slug string, never ``None``.
    """
    return read_camera_slug(str(entry["path"])) or "unknown"


def _apply_filters(
    args: argparse.Namespace,
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> tuple[list[tuple[dict[str, str | int], dict[str, str | int]]], list[dict[str, str | int]]]:
    """Apply all user-selected filters to duplicate and missing lists.

    Handles ``-d``/``-m`` selection, ``-n``/``-D`` duplicate sub-filters,
    and ``-k`` camera filter.

    Args:
        args: Parsed command-line arguments.
        duplicates: Unfiltered duplicate pairs.
        missing: Unfiltered missing entries.

    Returns:
        Tuple of (filtered_dups, filtered_miss).
    """
    show_all = not args.duplicates and not args.missing
    filtered_dups = list(duplicates) if args.duplicates or show_all else []
    filtered_miss = list(missing) if args.missing or show_all else []

    if args.name_changed:
        filtered_dups = [d for d in filtered_dups if _dup_has_name_change(d)]
    if args.date_changed:
        filtered_dups = [d for d in filtered_dups if _dup_has_date_change(d, args.tolerance)]
    if args.camera:
        filtered_dups = [d for d in filtered_dups if _file_camera_slug(d[0]) == args.camera]
        filtered_miss = [m for m in filtered_miss if _file_camera_slug(m) == args.camera]

    return filtered_dups, filtered_miss


def _dup_has_name_change(dup: tuple[dict[str, str | int], dict[str, str | int]]) -> bool:
    """Return True if filenames differ (case-insensitive) between scanned and archive.

    Args:
        dup: ``(scanned_entry, archive_entry)`` tuple.

    Returns:
        True if basename differs case-insensitively.

    Examples:
        >>> _dup_has_name_change(({"path": "IMG.JPG"}, {"path": "img.jpg"}))
        False
        >>> _dup_has_name_change(({"path": "IMG_1.JPG"}, {"path": "img_2.jpg"}))
        True
    """
    scanned_name = Path(str(dup[0].get("path", ""))).name
    archive_name = Path(str(dup[1].get("path", ""))).name
    return scanned_name.lower() != archive_name.lower()


def _dup_has_date_change(
    dup: tuple[dict[str, str | int], dict[str, str | int]], tolerance: int
) -> bool:
    """Return True if dates differ beyond tolerance between scanned and archive.

    Args:
        dup: ``(scanned_entry, archive_entry)`` tuple.
        tolerance: Allowed difference in seconds.

    Returns:
        True if date difference exceeds tolerance.

    Examples:
        >>> from datetime import datetime, UTC, timedelta
        >>> now = datetime.now(UTC)
        >>> later = now + timedelta(seconds=100)
        >>> _dup_has_date_change(({"date": now.isoformat()}, {"date": later.isoformat()}), 1)
        True
    """
    try:
        s_dt = datetime.fromisoformat(str(dup[0].get("date", "")))
        a_dt = datetime.fromisoformat(str(dup[1].get("date", "")))
        return abs((a_dt - s_dt).total_seconds()) > tolerance
    except (ValueError, TypeError):
        return False


def format_list_line(
    display_path: str,
    tag: str,
    scanned: dict[str, str | int],
    archive: dict[str, str | int] | None = None,
    tolerance: int = 0,
    camera_slug: str | None = None,
) -> str:
    """Format one ``--list`` output line for a ``[DUP]`` or ``[MISS]`` entry.

    For ``[MISS]``: shows date, human-readable size, and optional camera slug.
    For ``[DUP]``: shows date delta (when dates differ beyond tolerance),
    filename change (when basenames differ case-insensitively), and the
    archive reference path.
    Date format follows the same conditional logic as fixdates/exifdates:
    time-only when both timestamps share the same calendar date, full
    ``YYYY-MM-DD HH:MM:SS`` when they cross midnight.

    Args:
        display_path: Path to display (typically relative to source parent).
        tag: ``"[DUP]"`` or ``"[MISS]"``.
        scanned: Scanned file metadata dict.
        archive: Archive file metadata dict; ``None`` for ``[MISS]`` entries.
        tolerance: Timestamp tolerance in seconds; date delta shown only when
            the difference exceeds this value (default: 0).
        camera_slug: Camera slug for ``[MISS]`` entries; omitted when ``None``.

    Returns:
        Formatted output line.

    Examples:
        >>> entry = {"date": "2023-01-01T10:00:00", "size": 100}
        >>> line = format_list_line("dir/a.jpg", "[MISS]", entry)
        >>> "[MISS]" in line and "2023" in line and "100 B" in line
        True
    """
    prefix = f"{display_path}  {tag:<6}"

    if tag == "[MISS]":
        date_str = str(scanned.get("date", ""))
        try:
            dt = datetime.fromisoformat(date_str)
            date_display = dt.strftime(TS_FMT)
        except ValueError:
            date_display = date_str
        size_display = human_size(int(scanned.get("size", 0)))
        camera_part = f", camera: {camera_slug}" if camera_slug else ""
        return f"{prefix}  [date: {date_display}, size: {size_display}{camera_part}]"

    # [DUP]
    parts: list[str] = []

    if archive is not None:
        # Date comparison: scanned_date -> archive_date, delta = archive - scanned
        scanned_date = str(scanned.get("date", ""))
        archive_date = str(archive.get("date", ""))
        if scanned_date and archive_date:
            try:
                scanned_dt = datetime.fromisoformat(scanned_date)
                archive_dt = datetime.fromisoformat(archive_date)
                if abs((archive_dt - scanned_dt).total_seconds()) > tolerance:
                    parts.append(format_datetime_change(scanned_dt, archive_dt))
            except (ValueError, TypeError):
                pass

        # Filename comparison (case-insensitive)
        scanned_name = Path(str(scanned.get("path", ""))).name
        archive_name = Path(str(archive.get("path", ""))).name
        if scanned_name.lower() != archive_name.lower():
            parts.append(f"{scanned_name} -> {archive_name}")

        # Ref path - always shown for DUP
        archive_path = str(archive.get("path", ""))
        if archive_path:
            parts.append(f"[ref: {archive_path}]")

    suffix = "  ".join(parts)
    return f"{prefix}  {suffix}" if suffix else prefix


def display_summary(
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
    camera_stats: dict[str, tuple[int, int, str | None, str | None]] | None = None,
) -> None:
    """Display summary statistics.

    Args:
        duplicates: List of duplicate entries.
        missing: List of missing entries.
        camera_stats: Optional mapping of camera slug to
            ``(count, total_bytes, date_min, date_max)``.  When provided and
            non-empty, a ``Cameras detected:`` table is appended.
    """
    dup_size = sum(int(scanned["size"]) for scanned, _ in duplicates)
    miss_size = sum(int(entry["size"]) for entry in missing)

    print()
    if duplicates:
        print(f"{format_count(len(duplicates))} duplicates found ({human_size(dup_size)}).")
    if missing:
        print(f"{format_count(len(missing))} files missing ({human_size(miss_size)}).")

    if not camera_stats:
        return

    print("\nCameras detected:")
    rows = sorted(camera_stats.items(), key=lambda kv: -kv[1][0])
    slug_w = max(len(slug) for slug, _ in rows)
    count_w = max(len(format_count(v[0])) for _, v in rows)
    size_w = max(len(human_size(v[1])) for _, v in rows)
    for slug, (count, total_bytes, date_min, date_max) in rows:
        count_str = format_count(count)
        size_str = human_size(total_bytes)
        date_part = f"    {date_min}  \u2192  {date_max}" if date_min and date_max else ""
        print(
            f"  {slug:<{slug_w}}    {count_str:>{count_w}} files    {size_str:>{size_w}}{date_part}"
        )


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for find command.

    Args:
        parser: ArgumentParser to configure
    """
    parser.add_argument(
        "json_file",
        help="Archive JSON metadata file (created by index)",
    )
    parser.add_argument(
        "source",
        nargs="+",
        help=(
            "Directories to scan and/or PSV files with pre-computed metadata"
            " (path|sha1|md5|date|size); multiple values may be mixed freely"
        ),
    )
    parser.add_argument(
        "-d",
        "--duplicates",
        action="store_true",
        help="Limit results to files found in archive (duplicates)",
    )
    parser.add_argument(
        "-m",
        "--missing",
        action="store_true",
        help="Limit results to files NOT found in archive (missing)",
    )
    parser.add_argument(
        "-n",
        "--name-changed",
        action="store_true",
        help=("Filter output to duplicates with filename differences (basename, case-insensitive)"),
    )
    parser.add_argument(
        "-D",
        "--date-changed",
        action="store_true",
        help="Filter output to duplicates with date differences",
    )
    parser.add_argument(
        "-T",
        "--tolerance",
        type=int,
        default=0,
        help="Timestamp tolerance in seconds (default: 0)",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Output one tagged line per file with date, size, and archive ref (no summary)",
    )
    parser.add_argument(
        "-M",
        "--move",
        type=str,
        metavar="TARGET_DIR",
        help="Generate mv commands to move files to target directory structure",
    )
    parser.add_argument(
        "-C",
        "--copy",
        type=str,
        metavar="TARGET_DIR",
        help="Generate cp commands to copy files to target directory structure",
    )
    parser.add_argument(
        "-S",
        "--start",
        type=int,
        default=1,
        metavar="N",
        help="Starting number for target directory numbering (default: 1)",
    )
    parser.add_argument(
        "-k",
        "--camera",
        type=str,
        metavar="SLUG",
        help="Filter results to files matching this camera slug (e.g. canon-eos-5d-mark-iv)",
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed command-line arguments

    Raises:
        SystemExit: On any validation error
    """
    # Validate mutually exclusive options
    if args.move and args.copy:
        raise SystemExit("Error: --move and --copy are mutually exclusive")
    if (args.move or args.copy) and args.list:
        raise SystemExit("Error: --move/--copy cannot be used with --list")

    # -n/--name-changed, -D/--date-changed require -d/--duplicates
    if (args.name_changed or args.date_changed) and not args.duplicates:
        raise SystemExit(
            "Error: --name-changed and --date-changed require -d/--duplicates\n"
            "Use -h or --help for usage information"
        )
    # Validate inputs
    if not Path(args.json_file).exists():
        raise SystemExit(f"Error: JSON file not found: {args.json_file}")
    for src in args.source:
        source = Path(src)
        if not source.exists():
            raise SystemExit(f"Error: Source not found: {src}")
        if not source.is_dir() and not source.is_file():
            raise SystemExit(f"Error: Source must be a directory or PSV file: {src}")


def process_command_mode(
    args: argparse.Namespace,
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> None:
    """Process command generation mode (--move or --copy).

    Args:
        args: Parsed command-line arguments
        duplicates: List of duplicate file pairs
        missing: List of missing files
    """
    filtered_dups, filtered_miss = _apply_filters(args, duplicates, missing)
    files_to_process = [s for s, _ in filtered_dups] + filtered_miss

    if not files_to_process:
        return

    # Group files and assign directory numbers
    file_groups = group_files_by_directory(files_to_process)
    dir_mapping = assign_directory_numbers(file_groups, start=args.start)

    # Generate commands
    target_dir = args.move or args.copy
    operation = "mv" if args.move else "cp"
    commands = generate_file_operation_commands(
        files_to_process, target_dir, dir_mapping, operation
    )

    print("umask 022")
    for cmd in commands:
        print(cmd)


def _list_date_sort_key(date_str: str) -> float:
    """Return a sort key (epoch seconds) for an ISO 8601 date string.

    Args:
        date_str: ISO 8601 date string, timezone-aware or naive.

    Returns:
        Seconds since epoch as a float; 0.0 on parse failure.
    """
    try:
        return datetime.fromisoformat(date_str).timestamp()
    except ValueError:
        return 0.0


def process_list_mode(
    args: argparse.Namespace,
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> None:
    """Process list mode (--list).

    Displays one line per file with tag and contextual info, sorted by
    file modification date ascending.  ``--name-changed`` and
    ``--date-changed`` act as filters: when set, only duplicate entries
    that have a filename change or a date change (respectively) are shown.
    Both flags together form an AND filter.  Missing entries are always shown.

    Args:
        args: Parsed command-line arguments
        duplicates: List of duplicate file pairs
        missing: List of missing files
    """
    filtered_dups, filtered_miss = _apply_filters(args, duplicates, missing)

    # Collect (sort_key, line) pairs so the combined output can be sorted by date.
    entries: list[tuple[float, str]] = []

    for scanned, archive in filtered_dups:
        line = format_list_line(
            _display_path(str(scanned["path"])), "[DUP]", scanned, archive, args.tolerance
        )
        entries.append((_list_date_sort_key(str(scanned.get("date", ""))), line))

    for entry in filtered_miss:
        slug = read_camera_slug(str(entry["path"]))
        line = format_list_line(
            _display_path(str(entry["path"])), "[MISS]", entry, camera_slug=slug
        )
        entries.append((_list_date_sort_key(str(entry.get("date", ""))), line))

    entries.sort(key=lambda t: t[0])
    for _, line in entries:
        print(line)


def run(args: argparse.Namespace) -> int:
    """Execute find command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (os.EX_OK on success)

    Raises:
        SystemExit: On validation or runtime errors
    """
    validate_args(args)

    archive_data = load_json(args.json_file)
    size_index, checksum_index = build_archive_index(archive_data)

    scanned_files: list[dict[str, str | int]] = []
    for src in args.source:
        source = Path(src)
        scanned_files.extend(scan_directory(src) if source.is_dir() else load_psv(src))

    duplicates, missing = find_duplicates(scanned_files, size_index, checksum_index)

    if args.move or args.copy:
        process_command_mode(args, duplicates, missing)
    elif args.list:
        process_list_mode(args, duplicates, missing)
    else:
        archive_size = sum(int(e.get("size", 0)) for e in archive_data)
        print(
            f"Loaded {Path(args.json_file).name} with "
            f"{format_count(len(archive_data))} files ({human_size(archive_size)})."
        )
        for src in args.source:
            source = Path(src)
            if source.is_dir():
                print(f"Scanned directory {src}.")
            else:
                print(f"Loaded {source.name}.")
        print(f"Total: {format_count(len(scanned_files))} files scanned.")

        filtered_dups, filtered_miss = _apply_filters(args, duplicates, missing)
        all_files: list[dict[str, str | int]] = [s for s, _ in filtered_dups] + filtered_miss
        camera_stats = compute_camera_stats(all_files) if all_files else None
        display_summary(filtered_dups, filtered_miss, camera_stats)

    return os.EX_OK
