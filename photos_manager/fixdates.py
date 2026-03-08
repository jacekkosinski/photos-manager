"""fixdates - Fix file and directory timestamps based on JSON metadata.

This script updates modification timestamps of files and directories to match
the timestamps stored in JSON metadata files (created by index). It can:
- Fix file timestamps to match the 'date' field in JSON metadata
- Fix directory timestamps to match the newest file in each directory
- Fix JSON file timestamps to match the newest file it describes

This is useful for fixing filesystem timestamps to match the actual photo dates
after copying or restoring files from archives.

Usage:
    photos fixdates archive1.json
    photos fixdates archive1.json archive2.json --all
    photos fixdates archive.json --dry-run
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from photos_manager.common import load_json


def get_newest_files(
    json_file: str,
) -> tuple[dict[str, dict[str, str | int]], dict[str, str | int]]:
    """Retrieve the newest files from a JSON file grouped by directory.

    Analyzes JSON metadata to find the newest file in each directory based on
    the 'date' field. Also determines the overall newest file across all entries.

    Args:
        json_file: Path to the JSON file containing file metadata.

    Returns:
        A tuple containing two elements:
            - dict: Mapping of directory paths (str) to the newest file information
              (dict with path, sha1, md5, date, size fields) in that directory
            - dict: The overall newest file entry across all directories

    Raises:
        SystemExit: If the JSON file is empty, missing required fields (path, date),
            or contains invalid date formats.

    Examples:
        >>> newest_per_dir, newest_overall = get_newest_files("archive.json")
        >>> newest_per_dir['/photos/2024']
        {'path': '/photos/2024/img_999.jpg', 'date': '2024-12-31T23:59:59+01:00', ...}
        >>> newest_overall['path']
        '/photos/2024/img_999.jpg'
    """
    data = load_json(json_file)
    if not data:
        raise SystemExit(f"Error: JSON file '{json_file}' is empty")

    grouped_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in data:
        try:
            directory = str(Path(str(entry["path"])).parent)
        except KeyError as exception:
            raise SystemExit(f"Error: Missing 'path' key in entry: {entry}") from exception
        grouped_files.setdefault(directory, []).append(entry)

    newest_files: dict[str, dict[str, str | int]] = {}
    for directory, files in grouped_files.items():
        try:
            newest_files[directory] = max(
                files, key=lambda x: datetime.fromisoformat(str(x["date"]))
            )
        except KeyError as exception:
            raise SystemExit(f"Error: Missing 'date' key in entry: {files[0]}") from exception
        except ValueError as exception:
            raise SystemExit(f"Error: Invalid date format in entry: {files[0]}") from exception

    try:
        newest_entry = max(data, key=lambda x: datetime.fromisoformat(str(x["date"])))
    except (KeyError, ValueError) as exception:
        raise SystemExit("Error: Invalid or missing 'date' field in JSON data") from exception

    return newest_files, newest_entry


def set_files_timestamps(json_file: str, dry_run: bool = False) -> int:
    """Update file modification timestamps based on JSON metadata.

    Reads JSON metadata and updates the modification time of each file to match
    the 'date' field in the metadata. This is useful for restoring original
    timestamps after copying files.

    Only updates files where the current modification time differs from the
    expected timestamp. Files that don't exist or aren't writable are skipped
    with a warning message.

    Args:
        json_file: Path to the JSON file containing file metadata with 'path'
            and 'date' fields for each entry.
        dry_run: If True, only prints what would be changed without actually
            modifying any timestamps. Defaults to False.

    Returns:
        Number of timestamps updated (or that would be updated in dry-run).

    Raises:
        SystemExit: If the JSON file is empty or cannot be loaded.

    Warnings:
        Files with missing path/date fields, invalid dates, or that are
        inaccessible are skipped with warning messages to stderr.

    Examples:
        >>> set_files_timestamps("archive.json", dry_run=True)
        Set timestamp for file '/photos/img.jpg' to match '1704376496' time
        >>> set_files_timestamps("archive.json")  # Actually updates files
    """
    json_data = load_json(json_file)
    if not json_data:
        raise SystemExit(f"Error: JSON file '{json_file}' is empty")

    changes = 0
    for entry in json_data:
        file_path = entry.get("path")
        timestamp_str = entry.get("date")

        if not file_path or not timestamp_str:
            print(
                f"Error: Skipping entry due to missing path or date: {entry}",
                file=sys.stderr,
            )
            continue

        try:
            expected_timestamp = int(datetime.fromisoformat(str(timestamp_str)).timestamp())
        except ValueError as e:
            print(f"Error parsing date for {file_path}: {e}", file=sys.stderr)
            continue

        path = Path(str(file_path))
        required_access = os.R_OK if dry_run else os.W_OK
        access_label = "readable" if dry_run else "writable"

        if not path.exists() or not os.access(str(path), required_access):
            print(f"Error: File not found or not {access_label}: {file_path}", file=sys.stderr)
            continue

        try:
            current_mtime = int(path.stat().st_mtime)
        except OSError as e:
            print(
                f"Error accessing modification timestamp for {file_path}: {e}",
                file=sys.stderr,
            )
            continue

        if current_mtime != expected_timestamp:
            changes += 1
            print(f"Set timestamp for file '{file_path}' to match '{expected_timestamp}' time")
            if not dry_run:
                try:
                    os.utime(str(path), (expected_timestamp, expected_timestamp))
                except OSError as e:
                    print(
                        f"Error: Failed to update timestamps for {file_path}: {e}",
                        file=sys.stderr,
                    )
    return changes


def set_dirs_timestamps(
    newest_files: dict[str, dict[str, str | int]], dry_run: bool = False
) -> int:
    """Set directory timestamps to match the newest file in each directory.

    Updates the modification time of each directory to match the modification
    time of the newest file it contains. This ensures directory timestamps
    reflect their actual content.

    Args:
        newest_files: Dictionary mapping directory paths to their newest file
            information. Each value should be a dict with at least a 'path' field.
        dry_run: If True, only prints what would be changed without actually
            modifying any timestamps. Defaults to False.

    Returns:
        Number of timestamps updated (or that would be updated in dry-run).

    Warnings:
        Directories or files that don't exist or aren't accessible are skipped
        with warning messages to stderr. Permission errors are handled gracefully.

    Examples:
        >>> newest = {'/photos/2024': {'path': '/photos/2024/img.jpg', ...}}
        >>> set_dirs_timestamps(newest, dry_run=True)
        Set timestamp for directory '/photos/2024' to match file '/photos/2024/img.jpg' (...)
    """
    changes = 0
    for directory, file_info in newest_files.items():
        dir_path = Path(directory)
        file_path = Path(str(file_info["path"]))

        try:
            new_time = file_path.stat().st_mtime
            current_time = dir_path.stat().st_mtime
        except FileNotFoundError:
            print(
                f"Error: File or directory '{directory}' does not exist",
                file=sys.stderr,
            )
            continue
        except PermissionError:
            print(
                f"Error: Permission denied accessing '{directory}'",
                file=sys.stderr,
            )
            continue

        if new_time != current_time:
            changes += 1
            print(
                f"Set timestamp for directory '{directory}' to match file "
                f"'{file_info['path']}' ({datetime.fromtimestamp(new_time)})"
            )
            if not dry_run:
                try:
                    os.utime(str(dir_path), (new_time, new_time))
                except FileNotFoundError:
                    print(f"Error: Directory '{directory}' does not exist", file=sys.stderr)
                except PermissionError:
                    print(
                        f"Error: Permission denied setting timestamp for '{directory}'",
                        file=sys.stderr,
                    )
                except OSError as e:
                    print(
                        f"Error setting timestamp for directory '{directory}': {e}",
                        file=sys.stderr,
                    )
    return changes


def set_json_timestamps(
    json_file: str, dir_name: str, newest_entry: dict[str, str | int], dry_run: bool = False
) -> int:
    """Set timestamps of JSON file and directory to match newest entry.

    Updates the modification time of both the JSON metadata file and its
    corresponding directory to match the timestamp of the newest file entry.
    This ensures the JSON file and directory timestamps reflect the newest
    content they describe.

    Args:
        json_file: Path to the JSON metadata file.
        dir_name: Path to the directory corresponding to the JSON file.
        newest_entry: Dictionary containing the newest file entry, must have
            a 'path' field pointing to an existing file.
        dry_run: If True, only prints what would be changed without actually
            modifying any timestamps. Defaults to False.

    Returns:
        Number of timestamps updated (or that would be updated in dry-run).

    Warnings:
        If the reference file doesn't exist or timestamps cannot be updated,
        error messages are printed to stderr and the function returns early.

    Examples:
        >>> newest = {'path': '/photos/img.jpg', 'date': '2024-12-31T23:59:59+01:00', ...}
        >>> set_json_timestamps("photos.json", "photos", newest, dry_run=True)
        Set timestamp for 'photos.json' to match file '/photos/img.jpg' (...)
        Set timestamp for directory 'photos' to match file '/photos/img.jpg' (...)
    """
    reference_path_str = newest_entry.get("path")
    if not reference_path_str:
        print("Error: Missing 'path' in newest entry", file=sys.stderr)
        return 0

    reference_path = Path(str(reference_path_str))
    if not reference_path.exists():
        print(f"Error: Reference file '{reference_path}' does not exist", file=sys.stderr)
        return 0

    changes = 0
    try:
        reference_mtime = reference_path.stat().st_mtime

        json_path = Path(json_file)
        json_mtime = json_path.stat().st_mtime
        if json_mtime != reference_mtime:
            changes += 1
            print(
                f"Set timestamp for '{json_file}' to match file '{reference_path}' "
                f"({datetime.fromtimestamp(reference_mtime)})"
            )
            if not dry_run:
                os.utime(str(json_path), (reference_mtime, reference_mtime))

        dir_path = Path(dir_name)
        dir_mtime = dir_path.stat().st_mtime
        if dir_mtime != reference_mtime:
            changes += 1
            print(
                f"Set timestamp for directory '{dir_name}' to match file '{reference_path}' "
                f"({datetime.fromtimestamp(reference_mtime)})"
            )
            if not dry_run:
                os.utime(str(dir_path), (reference_mtime, reference_mtime))

    except OSError as e:
        print(
            f"Error setting timestamps for '{dir_name}': {e}",
            file=sys.stderr,
        )
    return changes


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for fixdates command.

    Adds all command-line arguments for the fixdates tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with fixdates arguments.
    """
    parser.add_argument(
        "json_files",
        nargs="+",
        help="One or more JSON files containing file metadata (preview by default)",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Update timestamps for all individual files in addition to directories",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply changes to the filesystem (default: preview only)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute fixdates command with parsed arguments.

    Processes each JSON file and coordinates timestamp updates for files,
    directories, and JSON metadata files based on the newest file information.

    For each JSON file provided:
    1. Optionally updates all file timestamps (with --all flag)
    2. Updates directory timestamps to match newest file in each directory
    3. Updates JSON file and its corresponding directory timestamps

    The script expects JSON files to have corresponding directories with the
    same base name (e.g., 'photos.json' corresponds to 'photos/' directory).

    Args:
        args: Parsed command-line arguments with fields:
            - json_files: List of JSON files containing file metadata
            - all: Whether to update all individual file timestamps
            - fix: Whether to apply changes (default: preview only)

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): All JSON files processed without errors
            - 1: One or more files were skipped due to errors

    Raises:
        SystemExit: If JSON files are invalid, empty, missing required fields,
            or if corresponding directories don't exist.

    Examples:
        >>> args = parser.parse_args(['archive.json'])
        >>> exit_code = run(args)
        Set timestamp for directory '/photos' to match file ...
    """
    # Iterate over each JSON file
    errors = 0
    for json_file in args.json_files:
        json_path = Path(json_file)

        if not json_path.exists() or not os.access(str(json_path), os.R_OK):
            print(
                f"Error: Skipping non-existent or unreadable JSON file '{json_file}'",
                file=sys.stderr,
            )
            errors += 1
            continue

        if json_path.stat().st_size == 0 or not json_path.is_file():
            print(f"Error: Skipping empty or invalid JSON file '{json_file}'", file=sys.stderr)
            errors += 1
            continue

        dir_name = str(json_path.with_suffix(""))
        dir_path = Path(dir_name)
        if not dir_path.is_dir() or not os.access(str(dir_path), os.R_OK):
            print(
                f"Error: Skipping non-existent or unreadable directory '{dir_name}'",
                file=sys.stderr,
            )
            errors += 1
            continue

        try:
            dry_run = not args.fix
            changes = 0
            if args.all:
                changes += set_files_timestamps(json_file, dry_run=dry_run)

            newest_files, newest_entry = get_newest_files(json_file)

            # Exclude root dir — set_json_timestamps handles it with overall newest.
            # Process subdirs deepest-first so parent timestamps are written last.
            newest_subdirs = {d: f for d, f in newest_files.items() if d != dir_name}
            sorted_subdirs = dict(
                sorted(newest_subdirs.items(), key=lambda x: x[0].count(os.sep), reverse=True)
            )
            changes += set_dirs_timestamps(sorted_subdirs, dry_run=dry_run)
            changes += set_json_timestamps(json_file, dir_name, newest_entry, dry_run=dry_run)
            if changes == 0:
                print(f"All timestamps already correct for {json_file}")

        except SystemExit as e:
            print(str(e), file=sys.stderr)
            errors += 1
            continue

    return os.EX_OK if errors == 0 else 1
