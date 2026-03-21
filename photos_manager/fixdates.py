"""fixdates - Fix file and directory timestamps based on JSON metadata.

This script updates modification timestamps of files and directories to match
the timestamps stored in JSON metadata files (created by index). It can:
- Fix file timestamps to match the 'date' field in JSON metadata
- Fix directory timestamps to match the newest file in each directory
- Fix JSON file timestamps to match the newest file it describes

This is useful for fixing filesystem timestamps to match the actual photo dates
after copying or restoring files from archives.

Usage:
    photos fixdates archive1.json              # preview changes
    photos fixdates archive1.json --fix        # apply changes
    photos fixdates archive1.json --all --fix  # also fix individual file timestamps
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from photos_manager.common import format_timestamp_change, load_metadata_json

_TAG_WIDTH = 6  # max(len("[FILE]"), len("[JSON]")) — "[DIR]" is 5, padded to 6
_TAG_FILE = "[FILE]"
_TAG_DIR = "[DIR]"
_TAG_JSON = "[JSON]"

# (name, tag, old_ts, new_ts, path, src)  — src is None for [FILE] entries
_PendingChange = tuple[str, str, float, float, Path, str | None]


def _name_col_width(pending: list[_PendingChange]) -> int:
    """Return the max name length for aligned column formatting."""
    return max((len(name) for name, *_ in pending), default=0)


def format_change_line(
    name: str, tag: str, old_ts: float, new_ts: float, name_width: int = 0, src: str | None = None
) -> str:
    """Format one output line describing a timestamp change.

    Args:
        name: Display name — full path of the file or directory (with trailing
            ``/`` for directories).
        tag: Type tag — one of ``[FILE]``, ``[DIR]``, ``[JSON]``.
        old_ts: Current modification time as POSIX timestamp.
        new_ts: Target modification time as POSIX timestamp.
        name_width: When non-zero, left-justifies the name column to this width
            so tags align across all lines in the output block.
        src: Source file whose mtime was used as the new timestamp.  When
            not None, appended as ``src: <path>`` inside the trailing
            parentheses.  None for ``[FILE]`` entries.

    Returns:
        Aligned line with full date when the date changes, time only otherwise:
        ``name  [TAG]  HH:MM:SS → HH:MM:SS (delta: +Xs[, src: path])``

    Examples:
        >>> line = format_change_line("photo.jpg", "[FILE]", 1_000_000_000.0, 1_000_003_600.0)
        >>> "->" in line and "delta:" in line
        True
    """
    extra = f", src: {src}" if src is not None else ""
    return format_timestamp_change(
        name,
        tag,
        datetime.fromtimestamp(old_ts),
        datetime.fromtimestamp(new_ts),
        name_width=name_width,
        tag_width=_TAG_WIDTH,
        extra=extra,
    )


def get_newest_files(
    data: list[dict[str, str | int]],
) -> tuple[dict[str, dict[str, str | int]], dict[str, str | int]]:
    """Retrieve the newest files from loaded JSON data grouped by directory.

    Analyzes JSON metadata to find the newest file in each directory based on
    the 'date' field. Also determines the overall newest file across all entries.

    Args:
        data: Already-loaded JSON metadata entries.

    Returns:
        A tuple containing two elements:
            - dict: Mapping of directory paths (str) to the newest file information
              (dict with path, sha1, md5, date, size fields) in that directory
            - dict: The overall newest file entry across all directories

    Raises:
        SystemExit: If the data is empty, missing required fields (path, date),
            or contains invalid date formats.

    Examples:
        >>> data = [{"path": "dir/a.jpg", "date": "2024-12-31T23:59:59+01:00"}]
        >>> newest_per_dir, newest_overall = get_newest_files(data)
    """
    if not data:
        raise SystemExit("Error: JSON data is empty")

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

    newest_entry = max(newest_files.values(), key=lambda x: datetime.fromisoformat(str(x["date"])))

    return newest_files, newest_entry


def _collect_file_changes(
    json_data: list[dict[str, str | int]], dry_run: bool = False
) -> list[_PendingChange]:
    """Collect file timestamp changes without printing or applying.

    Args:
        json_data: Already-loaded JSON metadata entries.
        dry_run: If True, checks for read access instead of write access.

    Returns:
        List of pending changes as ``(name, tag, old_ts, new_ts, path)`` tuples.
    """
    pending: list[_PendingChange] = []
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
            print(f"Error: Failed to parse date for {file_path}: {e}", file=sys.stderr)
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
            pending.append(
                (
                    str(file_path),
                    _TAG_FILE,
                    float(current_mtime),
                    float(expected_timestamp),
                    path,
                    None,
                )
            )
    return pending


def _collect_dir_changes(
    newest_files: dict[str, dict[str, str | int]],
) -> list[_PendingChange]:
    """Collect directory timestamp changes without printing or applying.

    Args:
        newest_files: Dictionary mapping directory paths to their newest file info.

    Returns:
        List of pending changes as ``(name, tag, old_ts, new_ts, path)`` tuples.
    """
    pending: list[_PendingChange] = []
    for directory, file_info in newest_files.items():
        dir_path = Path(directory)

        try:
            current_time = dir_path.stat().st_mtime
        except FileNotFoundError:
            print(
                f"Error: Directory '{directory}' does not exist",
                file=sys.stderr,
            )
            continue
        except PermissionError:
            print(
                f"Error: Permission denied accessing '{directory}'",
                file=sys.stderr,
            )
            continue

        try:
            new_time = datetime.fromisoformat(str(file_info["date"])).timestamp()
        except (KeyError, ValueError):
            print(f"Error: Invalid or missing date for '{directory}'", file=sys.stderr)
            continue

        if int(new_time) != int(current_time):
            pending.append(
                (
                    directory + "/",
                    _TAG_DIR,
                    current_time,
                    new_time,
                    dir_path,
                    str(file_info["path"]),
                )
            )
    return pending


def _collect_json_changes(
    json_file: str, dir_name: str, newest_entry: dict[str, str | int]
) -> list[_PendingChange]:
    """Collect JSON file and root directory timestamp changes.

    Args:
        json_file: Path to the JSON metadata file.
        dir_name: Path to the directory corresponding to the JSON file.
        newest_entry: Dictionary containing the newest file entry with a 'path' field.

    Returns:
        List of pending changes as ``(name, tag, old_ts, new_ts, path)`` tuples.

    Raises:
        OSError: If stat() calls fail on the json file or directory.
    """
    reference_path_str = newest_entry.get("path")
    if not reference_path_str:
        print("Error: Missing 'path' in newest entry", file=sys.stderr)
        return []

    date_str = newest_entry.get("date")
    if not date_str:
        print("Error: Missing 'date' in newest entry", file=sys.stderr)
        return []

    try:
        reference_mtime = datetime.fromisoformat(str(date_str)).timestamp()
    except ValueError:
        print(f"Error: Invalid date in newest entry: {date_str}", file=sys.stderr)
        return []

    src = str(reference_path_str)
    pending: list[_PendingChange] = []

    json_path = Path(json_file)
    json_mtime = json_path.stat().st_mtime  # may raise OSError
    if int(json_mtime) != int(reference_mtime):
        pending.append((json_file, _TAG_JSON, json_mtime, reference_mtime, json_path, src))

    dir_path = Path(dir_name)
    dir_mtime = dir_path.stat().st_mtime
    if int(dir_mtime) != int(reference_mtime):
        pending.append((dir_name + "/", _TAG_DIR, dir_mtime, reference_mtime, dir_path, src))

    return pending


def _apply_changes(pending: list[_PendingChange], name_width: int, dry_run: bool) -> int:
    """Print aligned output and optionally apply timestamp changes.

    Args:
        pending: List of ``(name, tag, old_ts, new_ts, path)`` tuples.
        name_width: Column width for the name field; 0 means no padding.
        dry_run: If True, only prints without modifying timestamps.

    Returns:
        Number of changes printed (and applied if not dry_run).
    """
    for name, tag, old_ts, new_ts, _path, src in pending:
        print(format_change_line(name, tag, old_ts, new_ts, name_width=name_width, src=src))
    if not dry_run:
        for name, _tag, _old_ts, new_ts, path, _src in pending:
            try:
                os.utime(path, (new_ts, new_ts))
            except OSError as e:
                print(f"Error: Failed to update timestamps for {name}: {e}", file=sys.stderr)
    return len(pending)


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
    json_data = load_metadata_json(json_file)
    if not json_data:
        raise SystemExit(f"Error: JSON file '{json_file}' is empty")
    pending = _collect_file_changes(json_data, dry_run)
    name_width = _name_col_width(pending)
    return _apply_changes(pending, name_width, dry_run)


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
    pending = _collect_dir_changes(newest_files)
    name_width = _name_col_width(pending)
    return _apply_changes(pending, name_width, dry_run)


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
    try:
        pending = _collect_json_changes(json_file, dir_name, newest_entry)
    except OSError as e:
        print(f"Error: Failed to set timestamps for '{dir_name}': {e}", file=sys.stderr)
        return 0
    name_width = _name_col_width(pending)
    return _apply_changes(pending, name_width, dry_run)


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
    errors = 0
    total_changes = 0
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
            all_pending: list[_PendingChange] = []

            json_data = load_metadata_json(json_file)
            if not json_data:
                raise SystemExit(f"Error: JSON file '{json_file}' is empty")

            if args.all:
                all_pending.extend(_collect_file_changes(json_data, dry_run))

            newest_files, newest_entry = get_newest_files(json_data)

            # Exclude root dir — _collect_json_changes handles it with overall newest.
            # Process subdirs deepest-first so parent timestamps are written last.
            newest_subdirs = {d: f for d, f in newest_files.items() if d != dir_name}
            sorted_subdirs = dict(
                sorted(newest_subdirs.items(), key=lambda x: x[0].count(os.sep), reverse=True)
            )
            all_pending.extend(_collect_dir_changes(sorted_subdirs))

            try:
                all_pending.extend(_collect_json_changes(json_file, dir_name, newest_entry))
            except OSError as e:
                print(f"Error: Failed to set timestamps for '{dir_name}': {e}", file=sys.stderr)
                errors += 1
                continue

            if not all_pending:
                print(f"All timestamps already correct for {json_file}")
            else:
                global_width = _name_col_width(all_pending)
                total_changes += _apply_changes(all_pending, global_width, dry_run)

        except SystemExit as e:
            print(str(e), file=sys.stderr)
            errors += 1
            continue

    verb = "applied" if args.fix else "detected"
    print(f"\n{total_changes} change(s) {verb}.")
    if total_changes:
        if not args.fix:
            print("Dry-run: use --fix to apply changes.")
        else:
            print("Run 'photos manifest' to regenerate it.")

    return os.EX_OK if errors == 0 else 1
