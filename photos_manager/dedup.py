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
import os
import shlex
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from photos_manager.common import calculate_checksums, load_json


def scan_directory(directory: str) -> list[dict[str, str | int]]:
    """Scan directory recursively and collect file metadata.

    Args:
        directory: Path to directory to scan

    Returns:
        List of file metadata dictionaries with keys:
        path (str), sha1 (str), md5 (str), date (str), size (int)
    """
    files: list[dict[str, str | int]] = []
    dir_path = Path(directory)

    if not dir_path.exists():
        raise SystemExit(f"Error: Directory not found: {directory}")
    if not dir_path.is_dir():
        raise SystemExit(f"Error: Not a directory: {directory}")

    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            file_path = Path(root) / filename

            try:
                stat_result = file_path.stat()
                size: int = stat_result.st_size
                mtime = datetime.fromtimestamp(stat_result.st_mtime).astimezone()
                date = mtime.isoformat()

                sha1, md5 = calculate_checksums(str(file_path))
                if sha1 is None or md5 is None:
                    continue  # Skip files we couldn't hash

                files.append(
                    {
                        "path": str(file_path.resolve()),
                        "sha1": sha1,
                        "md5": md5,
                        "date": date,
                        "size": size,
                    }
                )
            except OSError as e:
                print(f"Warning: Could not process {file_path}: {e}", file=sys.stderr)
                continue

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


def compare_filenames(scanned_path: str, archive_path: str) -> tuple[bool, str | None]:
    """Compare filenames (basename only) between scanned and archive files.

    Args:
        scanned_path: Path of scanned file
        archive_path: Path of archive file

    Returns:
        Tuple of (is_same, warning_message):
        - is_same: True if basenames match
        - warning_message: Description if different, None if same
    """
    scanned_name = Path(scanned_path).name
    archive_name = Path(archive_path).name

    if scanned_name == archive_name:
        return True, None

    return False, f"Filename differs - scanned: '{scanned_name}', archive: '{archive_name}'"


def compare_timestamps(
    scanned_date: str, archive_date: str, tolerance: int
) -> tuple[bool, str | None]:
    """Compare timestamps between scanned and archive files.

    Args:
        scanned_date: ISO 8601 timestamp of scanned file
        archive_date: ISO 8601 timestamp of archive file
        tolerance: Allowed difference in seconds

    Returns:
        Tuple of (is_within_tolerance, difference_message):
        - is_within_tolerance: True if within tolerance
        - difference_message: Description of difference, None if within tolerance
    """
    try:
        scanned_dt = datetime.fromisoformat(scanned_date)
        archive_dt = datetime.fromisoformat(archive_date)

        diff_seconds = abs((scanned_dt - archive_dt).total_seconds())

        if diff_seconds <= tolerance:
            return True, None

        return False, f"Timestamp differs by {int(diff_seconds)} seconds"
    except (ValueError, TypeError) as e:
        return False, f"Could not parse timestamps: {e}"


def format_size(size: int) -> str:
    """Format file size with thousands separators.

    Args:
        size: Size in bytes

    Returns:
        Formatted size string
    """
    return f"{size:,}"


def display_duplicates(
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    check_filenames: bool,
    check_timestamps: bool,
    tolerance: int,
) -> tuple[int, int]:
    """Display duplicate files with optional warnings.

    Args:
        duplicates: List of (scanned_entry, archive_entry) tuples
        check_filenames: Whether to check and warn about filename differences
        check_timestamps: Whether to check and warn about timestamp differences
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
        print(f"  [{idx}/{len(duplicates)}] {scanned['path']}")
        print(f"         Size: {format_size(int(scanned['size']))} bytes")
        print(f"         SHA1: {scanned['sha1']}")
        print(f"         MD5: {scanned['md5']}")
        print(f"         Archive: {archive['path']}")

        if check_filenames:
            is_same, warning = compare_filenames(str(scanned["path"]), str(archive["path"]))
            if not is_same and warning:
                print(f"         Warning: {warning}", file=sys.stderr)
                filename_warnings += 1

        if check_timestamps:
            is_within, diff = compare_timestamps(
                str(scanned["date"]), str(archive["date"]), tolerance
            )
            if not is_within and diff:
                print(f"         Warning: {diff}", file=sys.stderr)
                timestamp_warnings += 1

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
        print(f"  [{idx}/{len(missing)}] {entry['path']}")
        print(f"        Size: {format_size(int(entry['size']))} bytes")
        print(f"        SHA1: {entry['sha1']}")
        print(f"        MD5: {entry['md5']}")
        print()


def display_file_paths(
    items: Sequence[dict[str, str | int] | tuple[dict[str, str | int], dict[str, str | int]]],
    extract_path: Callable[[Any], str] = lambda item: item["path"],
) -> None:
    """Display file paths in list format (one per line).

    Args:
        items: Sequence of items to display (dicts or tuples of dicts)
        extract_path: Function to extract path from each item
    """
    for item in items:
        print(extract_path(item))


def display_summary(
    scanned_count: int,
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
    filename_warnings: int,
    timestamp_warnings: int,
) -> None:
    """Display summary statistics.

    Args:
        scanned_count: Total number of files scanned
        duplicates: List of duplicate entries
        missing: List of missing entries
        filename_warnings: Number of filename warnings
        timestamp_warnings: Number of timestamp warnings
    """
    dup_size = sum(int(scanned["size"]) for scanned, _ in duplicates)
    miss_size = sum(int(entry["size"]) for entry in missing)

    print("=" * 64)
    print("Summary:")
    print(f"  Files scanned: {scanned_count}")
    print(f"  Duplicates found: {len(duplicates)} (total size: {format_size(dup_size)} bytes)")
    print(f"  Missing from archive: {len(missing)} (total size: {format_size(miss_size)} bytes)")
    if filename_warnings > 0:
        print(f"  Filename warnings: {filename_warnings}")
    if timestamp_warnings > 0:
        print(f"  Timestamp warnings: {timestamp_warnings}")
    print("=" * 64)


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for dedup command.

    Args:
        parser: ArgumentParser to configure
    """
    parser.add_argument(
        "json_file",
        help="Archive JSON metadata file (created by index)",
    )
    parser.add_argument(
        "source",
        help="Directory to scan, or PSV file with pre-computed metadata (path|sha1|md5|date|size)",
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
        "-f",
        "--check-filenames",
        action="store_true",
        help="Compare filenames and warn if different (basename only)",
    )
    parser.add_argument(
        "-t",
        "--check-timestamps",
        action="store_true",
        help="Compare timestamps and warn if different",
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
        help="Output one file path per line (no details, no summary)",
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
    # Check if at least one display flag is specified
    if not args.show_duplicates and not args.show_missing:
        raise SystemExit(
            "Error: At least one of -d/--show-duplicates or -m/--show-missing is required\n"
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
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Error: Source not found: {args.source}")
    if not source.is_dir() and not source.is_file():
        raise SystemExit(f"Error: Source must be a directory or PSV file: {args.source}")


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

    Args:
        args: Parsed command-line arguments
        duplicates: List of duplicate file pairs
        missing: List of missing files
    """
    if args.show_duplicates:
        display_file_paths(duplicates, extract_path=lambda item: item[0]["path"])
    if args.show_missing:
        display_file_paths(missing)


def process_normal_mode(
    args: argparse.Namespace,
    scanned_files: list[dict[str, str | int]],
    duplicates: list[tuple[dict[str, str | int], dict[str, str | int]]],
    missing: list[dict[str, str | int]],
) -> None:
    """Process normal display mode (detailed output with summary).

    Args:
        args: Parsed command-line arguments
        scanned_files: List of scanned files
        duplicates: List of duplicate file pairs
        missing: List of missing files
    """
    filename_warnings = 0
    timestamp_warnings = 0

    if args.show_duplicates:
        fw, tw = display_duplicates(
            duplicates, args.check_filenames, args.check_timestamps, args.tolerance
        )
        filename_warnings += fw
        timestamp_warnings += tw

    if args.show_missing:
        display_missing(missing)

    # Display summary
    display_summary(len(scanned_files), duplicates, missing, filename_warnings, timestamp_warnings)


def run(args: argparse.Namespace) -> int:
    """Execute dedup command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (os.EX_OK on success)

    Raises:
        SystemExit: On validation or runtime errors
    """
    # Validate arguments
    validate_args(args)

    # Determine if we should suppress progress messages
    suppress_progress = args.list or args.move or args.copy

    # Load archive metadata
    if not suppress_progress:
        print(f"Loading archive metadata from {args.json_file}...")
    archive_data = load_json(args.json_file)
    if not suppress_progress:
        print(f"Loaded {len(archive_data)} files from archive")

    # Build indexes for efficient lookup
    size_index, checksum_index = build_archive_index(archive_data)

    # Collect scanned files from directory or PSV file
    source = Path(args.source)
    if source.is_dir():
        if not suppress_progress:
            print(f"\nScanning directory {args.source}...")
        scanned_files = scan_directory(args.source)
        if not suppress_progress:
            print(f"Scanned {len(scanned_files)} files")
    else:
        if not suppress_progress:
            print(f"\nLoading file list from {args.source}...")
        scanned_files = load_psv(args.source)
        if not suppress_progress:
            print(f"Loaded {len(scanned_files)} files")

    # Find duplicates and missing
    if not suppress_progress:
        print("\nComparing files...")
    duplicates, missing = find_duplicates(scanned_files, size_index, checksum_index)

    # Display results based on flags
    if args.move or args.copy:
        process_command_mode(args, duplicates, missing)
    elif args.list:
        process_list_mode(args, duplicates, missing)
    else:
        process_normal_mode(args, scanned_files, duplicates, missing)

    return os.EX_OK


def main() -> int:
    """CLI entry point for dedup command.

    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(
        description="Find duplicate and missing files by comparing with archive"
    )
    setup_parser(parser)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
