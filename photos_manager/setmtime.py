#!/usr/bin/env python3
"""setmtime - Set file and directory timestamps based on JSON metadata.

This script updates modification timestamps of files and directories to match
the timestamps stored in JSON metadata files (created by mkjson). It can:
- Update file timestamps to match the 'date' field in JSON metadata
- Update directory timestamps to match the newest file in each directory
- Update JSON file timestamps to match the newest file it describes

This is useful for ensuring filesystem timestamps match the actual photo dates
after copying or restoring files from archives.

Usage:
    ./setmtime.py archive1.json
    ./setmtime.py archive1.json archive2.json --all
    ./setmtime.py archive.json --dry-run
    python -m photos_manager.setmtime archive.json
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast


def load_json(file_path: str) -> list[dict[str, str | int]]:
    """Load JSON data from a file.

    Reads a JSON file and parses it into a list of dictionaries containing
    file metadata. This is a utility function for loading JSON files generated
    by mkjson.

    Args:
        file_path: Path to the JSON file to load. Can be absolute or relative.

    Returns:
        List of dictionaries containing file information with keys matching
        the mkjson output format (path, sha1, md5, date, size).

    Raises:
        SystemExit: If the file cannot be read or contains invalid JSON.

    Examples:
        >>> data = load_json("archive.json")
        >>> data[0]['path']
        '/path/to/photos/image.jpg'
    """
    try:
        path = Path(file_path)
        with path.open(encoding="utf-8") as json_file:
            data: Any = json.load(json_file)
            return cast("list[dict[str, str | int]]", data)
    except FileNotFoundError as exception:
        raise SystemExit(f"Error: JSON file '{file_path}' does not exist.") from exception
    except json.JSONDecodeError as exception:
        raise SystemExit(
            f"Error: JSON file '{file_path}' contains an invalid format."
        ) from exception


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
        {'path': '/photos/2024/img_999.jpg', 'date': '2024-12-31T23:59:59+0100', ...}
        >>> newest_overall['path']
        '/photos/2024/img_999.jpg'
    """
    # Load JSON data from the file
    data = load_json(json_file)
    if not data:
        raise SystemExit(f"Error: JSON file '{json_file}' is empty.")

    # Group entries by directory path
    grouped_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in data:
        try:
            directory = str(Path(str(entry["path"])).parent)
        except KeyError as exception:
            raise SystemExit(f"Error: Missing 'path' key in entry: {entry}") from exception

        if directory not in grouped_files:
            grouped_files[directory] = []
        grouped_files[directory].append(entry)

    # Find the newest file in each directory
    newest_files: dict[str, dict[str, str | int]] = {}
    for directory, files in grouped_files.items():
        try:
            newest_file = max(files, key=lambda x: datetime.fromisoformat(str(x["date"])))
        except KeyError as exception:
            raise SystemExit(f"Error: Missing 'date' key in entry: {files[0]}") from exception
        except ValueError as exception:
            raise SystemExit(f"Error: Invalid date format in entry: {files[0]}") from exception
        newest_files[directory] = newest_file

    # Find the file with the newest timestamp across all entries
    try:
        newest_entry = max(data, key=lambda x: datetime.fromisoformat(str(x["date"])))
    except (KeyError, ValueError) as exception:
        raise SystemExit("Error: Invalid or missing 'date' field in JSON data") from exception

    return newest_files, newest_entry


def set_files_timestamps(json_file: str, dry_run: bool = False) -> None:
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
    # Load JSON data from the file
    json_data = load_json(json_file)
    if not json_data:
        raise SystemExit(f"Error: JSON file '{json_file}' is empty.")

    for entry in json_data:
        file_path = entry.get("path")
        timestamp_str = entry.get("date")

        if not file_path or not timestamp_str:
            print(
                f"Error: Skipping entry due to missing path or date: {entry}",
                file=sys.stderr,
            )
            continue

        # Convert date string to timestamp
        try:
            expected_timestamp = int(datetime.fromisoformat(str(timestamp_str)).timestamp())
        except ValueError as e:
            print(f"Error parsing date for {file_path}: {e}", file=sys.stderr)
            continue

        path = Path(str(file_path))

        # Check if file exists and is writable
        if not path.exists() or not os.access(str(path), os.W_OK):
            print(f"Error: File not found or not writable: {file_path}", file=sys.stderr)
            continue

        # Get current timestamp
        try:
            current_mtime = int(path.stat().st_mtime)
        except OSError as e:
            print(
                f"Error accessing modification timestamp for {file_path}: {e}",
                file=sys.stderr,
            )
            continue

        # Check if update is needed
        if current_mtime != expected_timestamp:
            print(f"Set timestamp for file '{file_path}' to match '{expected_timestamp}' time")
            if not dry_run:
                try:
                    os.utime(str(path), (expected_timestamp, expected_timestamp))
                except OSError as e:
                    print(
                        f"Error: Failed to update timestamps for {file_path}: {e}",
                        file=sys.stderr,
                    )


def set_dirs_timestamps(
    newest_files: dict[str, dict[str, str | int]], dry_run: bool = False
) -> None:
    """Set directory timestamps to match the newest file in each directory.

    Updates the modification time of each directory to match the modification
    time of the newest file it contains. This ensures directory timestamps
    reflect their actual content.

    Args:
        newest_files: Dictionary mapping directory paths to their newest file
            information. Each value should be a dict with at least a 'path' field.
        dry_run: If True, only prints what would be changed without actually
            modifying any timestamps. Defaults to False.

    Warnings:
        Directories or files that don't exist or aren't accessible are skipped
        with warning messages to stderr. Permission errors are handled gracefully.

    Examples:
        >>> newest = {'/photos/2024': {'path': '/photos/2024/img.jpg', ...}}
        >>> set_dirs_timestamps(newest, dry_run=True)
        Set timestamp for directory '/photos/2024' to match file '/photos/2024/img.jpg' (...)
    """
    for directory, file_info in newest_files.items():
        dir_path = Path(directory)
        file_path = Path(str(file_info["path"]))

        try:
            new_time = file_path.stat().st_mtime
            current_time = dir_path.stat().st_mtime
        except FileNotFoundError:
            print(
                f"Error: File or directory '{directory}' does not exist.",
                file=sys.stderr,
            )
            continue
        except PermissionError:
            print(
                f"Error: Permission denied accessing '{directory}'.",
                file=sys.stderr,
            )
            continue

        if new_time != current_time:
            print(
                f"Set timestamp for directory '{directory}' to match file "
                f"'{file_info['path']}' ({datetime.fromtimestamp(new_time)})"
            )
            if not dry_run:
                try:
                    os.utime(str(dir_path), (new_time, new_time))
                except FileNotFoundError:
                    print(f"Error: Directory '{directory}' does not exist.", file=sys.stderr)
                except PermissionError:
                    print(
                        f"Error: Permission denied setting timestamp for '{directory}'.",
                        file=sys.stderr,
                    )
                except OSError as e:
                    print(
                        f"Error setting timestamp for directory '{directory}': {e}",
                        file=sys.stderr,
                    )


def set_json_timestamps(
    json_file: str, dir_name: str, newest_entry: dict[str, str | int], dry_run: bool = False
) -> None:
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

    Warnings:
        If the reference file doesn't exist or timestamps cannot be updated,
        error messages are printed to stderr and the function returns early.

    Examples:
        >>> newest = {'path': '/photos/img.jpg', 'date': '2024-12-31T23:59:59+0100', ...}
        >>> set_json_timestamps("photos.json", "photos", newest, dry_run=True)
        Set timestamp for 'photos.json' to match file '/photos/img.jpg' (...)
        Set timestamp for directory 'photos' to match file '/photos/img.jpg' (...)
    """
    # Get the path from newest_entry
    reference_path_str = newest_entry.get("path")
    if not reference_path_str:
        print("Error: Missing 'path' in newest entry.", file=sys.stderr)
        return

    reference_path = Path(str(reference_path_str))
    if not reference_path.exists():
        print(f"Error: Reference file '{reference_path}' does not exist.", file=sys.stderr)
        return

    try:
        # Get the modification time of the reference file
        reference_mtime = reference_path.stat().st_mtime

        # Check and update JSON file timestamp
        json_path = Path(json_file)
        json_mtime = json_path.stat().st_mtime
        if json_mtime != reference_mtime:
            print(
                f"Set timestamp for '{json_file}' to match file '{reference_path}' "
                f"({datetime.fromtimestamp(reference_mtime)})"
            )
            if not dry_run:
                os.utime(str(json_path), (reference_mtime, reference_mtime))

        # Check and update directory timestamp
        dir_path = Path(dir_name)
        dir_mtime = dir_path.stat().st_mtime
        if dir_mtime != reference_mtime:
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


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for setmtime command.

    Adds all command-line arguments for the setmtime tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with setmtime arguments.
    """
    parser.add_argument(
        "json_files", nargs="+", help="One or more JSON files containing file metadata"
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Update timestamps for all individual files in addition to directories",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print what will be done without actually setting timestamps",
    )


def run(args: argparse.Namespace) -> int:
    """Execute setmtime command with parsed arguments.

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
            - dry_run: Whether to preview changes without modifying

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): Successful execution
            - 1 (SystemExit): Error occurred during processing

    Raises:
        SystemExit: If JSON files are invalid, empty, missing required fields,
            or if corresponding directories don't exist.

    Examples:
        >>> args = parser.parse_args(['archive.json', '--dry-run'])
        >>> exit_code = run(args)
        Set timestamp for directory '/photos' to match file ...
    """
    # Iterate over each JSON file
    for json_file in args.json_files:
        json_path = Path(json_file)

        # Skip if JSON file does not exist or is unreadable
        if not json_path.exists() or not os.access(str(json_path), os.R_OK):
            print(
                f"Error: Skipping non-existent or unreadable JSON file '{json_file}'",
                file=sys.stderr,
            )
            continue

        # Skip empty JSON files or not a regular file
        if json_path.stat().st_size == 0 or not json_path.is_file():
            print(f"Error: Skipping empty or invalid JSON file '{json_file}'", file=sys.stderr)
            continue

        # Take dirname from JSON filename (e.g., 'photos.json' -> 'photos')
        dir_name = str(json_path.with_suffix(""))

        # Check if the corresponding directory exists and is readable
        dir_path = Path(dir_name)
        if not dir_path.is_dir() or not os.access(str(dir_path), os.R_OK):
            print(
                f"Error: Skipping non-existent or unreadable directory '{dir_name}'",
                file=sys.stderr,
            )
            continue

        try:
            # Process timestamps
            if args.all:
                set_files_timestamps(json_file, dry_run=args.dry_run)

            newest_files, newest_entry = get_newest_files(json_file)
            set_dirs_timestamps(newest_files, dry_run=args.dry_run)
            set_json_timestamps(json_file, dir_name, newest_entry, dry_run=args.dry_run)

        except SystemExit as e:
            print(str(e), file=sys.stderr)
            continue

    return os.EX_OK


def main() -> int:
    """Main entry point for standalone execution.

    Creates argument parser, configures it with setup_parser(),
    parses command-line arguments, and executes run().

    This function exists for backward compatibility and standalone
    execution. The unified CLI uses setup_parser() and run() directly.

    Returns:
        int: Exit code from run()
            - os.EX_OK (0): Successful execution
            - 1+: Error occurred during processing
    """
    parser = argparse.ArgumentParser(
        description="Set timestamps for directories and JSON files based on newest file metadata."
    )
    setup_parser(parser)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
