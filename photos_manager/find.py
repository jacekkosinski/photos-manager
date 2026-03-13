"""Find duplicate and missing files by comparing with archive metadata.

This module provides functionality to compare files in a directory against
archive metadata (JSON created by index) to identify:
- Duplicates: Files that exist in the archive
- Missing: Files that do NOT exist in the archive

The comparison uses file size as a first filter, then SHA1 and MD5 checksums
for exact matching. Optional filename and timestamp comparison can provide
additional warnings when files differ in these attributes.
"""

import argparse
import concurrent.futures
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

from photos_manager.common import (
    TIME_FMT,
    TS_FMT,
    calculate_checksums,
    format_count,
    human_size,
    load_json,
)


def scan_directory(directory: str) -> list[dict[str, str | int]]:
    """Scan directory recursively and collect file metadata.

    Args:
        directory: Path to directory to scan

    Returns:
        List of file metadata dictionaries with keys:
        path (str), sha1 (str), md5 (str), date (str), size (int)
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        raise SystemExit(f"Error: Directory not found: {directory}")
    if not dir_path.is_dir():
        raise SystemExit(f"Error: Not a directory: {directory}")

    # Phase 1: collect paths and stat info (sequential)
    file_entries: list[tuple[str, str, int]] = []
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            stat_result = file_path.stat()
            date = datetime.fromtimestamp(stat_result.st_mtime).astimezone().isoformat()
            file_entries.append((str(file_path.resolve()), date, stat_result.st_size))
        except OSError as e:
            print(f"Warning: Could not process {file_path}: {e}", file=sys.stderr)

    # Phase 2: compute checksums in parallel (hashlib releases the GIL)
    workers = os.cpu_count() or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        checksums = list(executor.map(calculate_checksums, [p for p, _, _ in file_entries]))

    # Phase 3: assemble results (order preserved by executor.map)
    files: list[dict[str, str | int]] = []
    for (path, date, size), (sha1, md5) in zip(file_entries, checksums, strict=True):
        if sha1 is None or md5 is None:
            continue
        files.append({"path": path, "sha1": sha1, "md5": md5, "date": date, "size": size})

    return files


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


def display_commands(commands: list[str]) -> None:
    """Print commands one per line.

    Args:
        commands: List of shell commands to print
    """
    for cmd in commands:
        print(cmd)


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
    except ValueError:
        return False


def format_list_line(
    display_path: str,
    tag: str,
    scanned: dict[str, str | int],
    archive: dict[str, str | int] | None = None,
    tolerance: int = 0,
) -> str:
    """Format one ``--list`` output line for a ``[DUP]`` or ``[MISS]`` entry.

    For ``[MISS]``: shows date and human-readable size.
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
        return f"{prefix}  [date: {date_display}, size: {size_display}]"

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
                    delta_s = int((archive_dt - scanned_dt).total_seconds())
                    delta_str = f"+{delta_s}s" if delta_s >= 0 else f"{delta_s}s"
                    if scanned_dt.date() != archive_dt.date():
                        old_str = scanned_dt.strftime(TS_FMT)
                        new_str = archive_dt.strftime(TS_FMT)
                    else:
                        old_str = scanned_dt.strftime(TIME_FMT)
                        new_str = archive_dt.strftime(TIME_FMT)
                    parts.append(f"{old_str} -> {new_str} (delta: {delta_str})")
            except ValueError:
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


def display_duplicates(
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    tolerance: int,
) -> tuple[int, int]:
    """Display duplicate files with warnings.

    Args:
        duplicates: List of (scanned_entry, archive_entry) tuples
        tolerance: Timestamp tolerance in seconds

    Returns:
        Tuple of (filename_warnings, timestamp_warnings) counts
    """
    if not duplicates:
        return 0, 0

    print("\nDuplicates (files found in archive):\n")

    filename_warnings = 0
    timestamp_warnings = 0

    for idx, (scanned, archive) in enumerate(duplicates, 1):
        size = int(scanned["size"])

        # Date field — show delta inline if dates differ beyond tolerance
        scanned_date_str = str(scanned.get("date", ""))
        archive_date_str = str(archive.get("date", ""))
        date_display = scanned_date_str
        try:
            scanned_dt = datetime.fromisoformat(scanned_date_str)
            archive_dt = datetime.fromisoformat(archive_date_str)
            date_display = scanned_dt.isoformat(sep=" ")
            delta_s = int((archive_dt - scanned_dt).total_seconds())
            if abs(delta_s) > tolerance:
                timestamp_warnings += 1
                delta_str = f"+{delta_s}s" if delta_s >= 0 else f"{delta_s}s"
                date_display = (
                    f"{date_display} -> {archive_dt.isoformat(sep=' ')} (delta: {delta_str})"
                )
        except ValueError:
            pass

        # Filename check — case-insensitive; only flag real name changes
        scanned_name = Path(str(scanned["path"])).name
        archive_name = Path(str(archive["path"])).name
        has_name_diff = scanned_name.lower() != archive_name.lower()
        if has_name_diff:
            filename_warnings += 1

        print(f"  [{idx}/{len(duplicates)}] {scanned['path']}")
        print(f"         date: {date_display}")
        print(f"         size: {size:_} bytes ({human_size(size)})".replace("_", " "))
        print(f"         SHA1: {scanned['sha1']}")
        print(f"         MD5:  {scanned['md5']}")
        if has_name_diff:
            print(f"         name: {scanned_name} -> {archive_name}")
        print(f"         ref:  {archive['path']}")
        print()

    return filename_warnings, timestamp_warnings


def display_missing(missing: list[dict[str, str | int]]) -> None:
    """Display files missing from archive.

    Args:
        missing: List of scanned file entries not in archive
    """
    if not missing:
        return

    print("\nMissing from archive (files NOT in archive):\n")

    for idx, entry in enumerate(missing, 1):
        size = int(entry["size"])
        try:
            date_display = datetime.fromisoformat(str(entry.get("date", ""))).isoformat(sep=" ")
        except ValueError:
            date_display = str(entry.get("date", ""))
        print(f"  [{idx}/{len(missing)}] {entry['path']}")
        print(f"        date: {date_display}")
        print(f"        size: {size:_} bytes ({human_size(size)})".replace("_", " "))
        print(f"        SHA1: {entry['sha1']}")
        print(f"        MD5:  {entry['md5']}")
        print()


def display_summary(
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> None:
    """Display summary statistics.

    Args:
        duplicates: List of duplicate entries.
        missing: List of missing entries.
    """
    dup_size = sum(int(scanned["size"]) for scanned, _ in duplicates)
    miss_size = sum(int(entry["size"]) for entry in missing)

    print()
    print(f"{format_count(len(duplicates))} duplicates found ({human_size(dup_size)}).")
    print(f"{format_count(len(missing))} files missing ({human_size(miss_size)}).")


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
        "--show-duplicates",
        action="store_true",
        help="Display files found in archive (duplicates)",
    )
    parser.add_argument(
        "-m",
        "--show-missing",
        action="store_true",
        help="Display files NOT found in archive (missing)",
    )
    parser.add_argument(
        "--check-filenames",
        action="store_true",
        help=(
            "Filter --list output to duplicates with filename differences"
            " (basename, case-insensitive)"
        ),
    )
    parser.add_argument(
        "--check-timestamps",
        action="store_true",
        help="Filter --list output to duplicates with date differences",
    )
    parser.add_argument(
        "-T",
        "--tolerance",
        type=int,
        default=1,
        help="Timestamp tolerance in seconds (default: 1)",
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


def validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed command-line arguments

    Raises:
        SystemExit: On any validation error
    """
    # -d/-m required for --move/--copy (need to know which files to process)
    if (args.move or args.copy) and not args.show_duplicates and not args.show_missing:
        raise SystemExit(
            "Error: At least one of -d/--show-duplicates or -m/--show-missing is required "
            "when using --move or --copy\n"
            "Use -h or --help for usage information"
        )

    # Validate mutually exclusive options
    if args.move and args.copy:
        raise SystemExit("Error: --move and --copy are mutually exclusive")
    if (args.move or args.copy) and args.list:
        raise SystemExit("Error: --move/--copy cannot be used with --list")
    if args.move and not Path(args.move).is_dir():
        raise SystemExit(f"Error: Target directory does not exist: {args.move}")
    if args.copy and not Path(args.copy).is_dir():
        raise SystemExit(f"Error: Target directory does not exist: {args.copy}")

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
    files_to_process: list[dict[str, str | int]] = []
    if args.show_duplicates:
        files_to_process.extend([scanned for scanned, _ in duplicates])
    if args.show_missing:
        files_to_process.extend(missing)

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

    # Print umask first, then commands
    print("umask 022")
    display_commands(commands)


def process_list_mode(
    args: argparse.Namespace,
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> None:
    """Process list mode (--list).

    Displays one line per file with tag and contextual info.  ``--check-filenames``
    and ``--check-timestamps`` act as filters: when set, only duplicate entries
    that have a filename change or a date change (respectively) are shown.
    Both flags together form an AND filter.  Missing entries are always shown.

    Args:
        args: Parsed command-line arguments
        duplicates: List of duplicate file pairs
        missing: List of missing files
    """
    show_all = not args.show_duplicates and not args.show_missing

    if args.show_duplicates or show_all:
        filtered: list[tuple[dict[str, str | int], dict[str, str | int]]] = list(duplicates)
        if args.check_filenames:
            filtered = [d for d in filtered if _dup_has_name_change(d)]
        if args.check_timestamps:
            filtered = [d for d in filtered if _dup_has_date_change(d, args.tolerance)]
        for scanned, archive in filtered:
            line = format_list_line(
                _display_path(str(scanned["path"])), "[DUP]", scanned, archive, args.tolerance
            )
            print(line)

    if args.show_missing or show_all:
        for entry in missing:
            line = format_list_line(_display_path(str(entry["path"])), "[MISS]", entry)
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

        if args.show_duplicates:
            display_duplicates(duplicates, args.tolerance)
        if args.show_missing:
            display_missing(missing)

        display_summary(duplicates, missing)

    return os.EX_OK
