"""index - Generate JSON file with file metadata from directory.

This script recursively scans a directory and generates a JSON file containing
metadata for each file found:
- Path to the file
- SHA1 and MD5 checksums
- File size in bytes
- Modification timestamp with timezone

Supports merging with existing JSON files and provides multiple sorting options.

Usage:
    photos index /path/to/directory
    photos index /path/to/directory --merge existing.json
    photos index /path/to/directory --sort-by-number
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from photos_manager.common import calculate_checksums


def get_file_info(directory: str, time_zone: str) -> list[dict[str, str | int]]:
    """Collect information about all files in a given directory.

    Recursively walks through the directory tree starting from the specified
    directory and collects metadata for each file found. For each file,
    calculates SHA1 and MD5 checksums, retrieves file size and modification
    time with timezone information.

    Args:
        directory: Directory path to scan recursively. Can be an absolute or
            relative path string.
        time_zone: Time zone identifier (e.g., 'UTC', 'Europe/Warsaw') for
            formatting modification timestamps. Uses zoneinfo for timezone handling.

    Returns:
        A list of dictionaries, where each dictionary contains file metadata
        with the following keys:
            - path (str): Absolute path to the file
            - sha1 (str): SHA1 checksum as hex string
            - md5 (str): MD5 checksum as hex string
            - date (str): Modification time in ISO 8601 format with timezone
            - size (int): File size in bytes

    Warnings:
        Files that cannot be accessed due to permission errors or OS errors
        during checksum calculation are skipped with a warning message. The
        function continues processing other files.

        If the directory itself cannot be accessed, a warning is printed to
        stderr and an empty list is returned.

    Examples:
        >>> files = get_file_info("/path/to/photos", "Europe/Warsaw")
        >>> files[0]
        {
            'path': '/path/to/photos/image.jpg',
            'sha1': 'a1b2c3...',
            'md5': 'd4e5f6...',
            'date': '2025-01-04T12:34:56+01:00',
            'size': 1234567
        }
    """
    local_tz = ZoneInfo(time_zone)
    file_info_list: list[dict[str, str | int]] = []

    # Phase 1: collect paths and stat info (sequential)
    file_entries: list[tuple[str, float, int]] = []
    dir_path = Path(directory)
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            stat_info = file_path.stat()
            file_entries.append((str(file_path), stat_info.st_mtime, stat_info.st_size))
        except OSError as e:
            print(f"Warning: Cannot stat {file_path}: {e}", file=sys.stderr)

    # Phase 2: compute checksums in parallel (hashlib releases the GIL)
    workers = os.cpu_count() or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        checksums = list(executor.map(calculate_checksums, [path for path, _, _ in file_entries]))

    # Phase 3: assemble results (order preserved by executor.map)
    for (path, mtime, size), (sha1, md5) in zip(file_entries, checksums, strict=True):
        if sha1 is None or md5 is None:
            continue
        mod_time_with_tz = datetime.fromtimestamp(mtime, local_tz).isoformat()
        file_info_list.append(
            {
                "path": path,
                "sha1": sha1,
                "md5": md5,
                "date": mod_time_with_tz,
                "size": size,
            }
        )

    return file_info_list


def extract_numbers(path: str) -> tuple[int, int, str]:
    """Extract numbers from a given path for numerical sorting.

    Searches for numeric patterns in the parent directory name and filename,
    extracting the first number found in each. This is used for sorting files
    numerically rather than alphabetically.

    Args:
        path: Path string to extract numbers from. Can be absolute or relative.

    Returns:
        A tuple containing three elements:
            - int: First number found in parent directory name, or 0 if none
            - int: First number found in filename, or 0 if none
            - str: The filename (basename of the path)

    Examples:
        >>> extract_numbers("/archive/batch_42/photo_123.jpg")
        (42, 123, 'photo_123.jpg')
        >>> extract_numbers("/photos/no_numbers/image.png")
        (0, 0, 'image.png')
    """
    # Extract numbers from the second directory
    path_obj = Path(path)
    dirname = path_obj.parent.name
    match = re.search(r"\d+", dirname)
    dir_number = int(match.group()) if match else 0

    # Extract numbers from the filename
    filename = path_obj.name
    match = re.search(r"\d+", filename)
    filename_number = int(match.group()) if match else 0

    return dir_number, filename_number, filename


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for index command.

    Adds all command-line arguments for the index tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with index arguments.
    """
    parser.add_argument("directory", type=str, help="Path to the source directory")
    parser.add_argument(
        "-m", "--merge", required=False, metavar="JSON", help="Path to the JSON file to merge"
    )
    parser.add_argument(
        "-z",
        "--time-zone",
        default="Europe/Warsaw",
        metavar="TZ",
        help="Time zone for modification time (default: Europe/Warsaw)",
    )
    parser.add_argument(
        "-n",
        "--sort-by-number",
        action="store_true",
        help="Sort files numerically by number in second directory and filename",
    )
    parser.add_argument(
        "-D",
        "--sort-by-dir",
        action="store_true",
        help="Sort files first by directory name and then by modification timestamp",
    )


def run(args: argparse.Namespace) -> int:
    """Execute index command with parsed arguments.

    Scans the directory, optionally merges with existing JSON, validates
    for duplicates, sorts results, and writes output JSON file.

    The output JSON file is named after the source directory (e.g., scanning
    '/path/to/photos' creates 'photos.json') and contains an array of objects
    with file metadata (path, sha1, md5, date, size).

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to source directory
            - merge: Optional path to JSON file to merge with
            - time_zone: Timezone for timestamps
            - sort_by_number: Sort by numeric patterns
            - sort_by_dir: Sort by directory name then timestamp

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): Successful execution

    Raises:
        SystemExit: If any of the following errors occur:
            - Source directory does not exist or is not a directory
            - Merge file cannot be read or contains invalid JSON
            - Duplicate paths, SHA1, or MD5 hashes detected
            - Output file cannot be written

    Examples:
        >>> # Scan directory and create JSON
        >>> args = parser.parse_args(['/path/to/photos'])
        >>> exit_code = run(args)
        File information written to photos.json
    """
    if not Path(args.directory).is_dir():
        raise SystemExit(f"Error: The specified path '{args.directory}' is not a valid directory")

    file_info_list = get_file_info(args.directory, args.time_zone)

    if args.merge:
        try:
            merge_path = Path(args.merge)
            with merge_path.open(encoding="utf-8") as json_file:
                merge_data = json.load(json_file)
                file_info_list.extend(merge_data)
        except FileNotFoundError as exception:
            raise SystemExit(
                f"Error: The specified merge file '{args.merge}' does not exist"
            ) from exception
        except json.JSONDecodeError as exception:
            raise SystemExit(
                f"Error: JSON file '{args.merge}' contains invalid format"
            ) from exception

    for key in ["path", "sha1", "md5"]:
        counts = Counter(entry[key] for entry in file_info_list)
        duplicates = sorted(str(item) for item, count in counts.items() if count > 1)

        if duplicates:
            raise SystemExit(f"Error: Duplicate {key} found: {', '.join(duplicates)}")

    if args.sort_by_number:
        file_info_list.sort(key=lambda x: extract_numbers(str(x["path"])))
    elif args.sort_by_dir:
        file_info_list.sort(
            key=lambda x: (
                str(Path(str(x["path"])).parent),
                x["date"],
                str(Path(str(x["path"])).name),
            )
        )
    else:
        file_info_list.sort(key=lambda x: (x["date"], str(Path(str(x["path"])).name)))

    # Reorder keys for consistent JSON output
    key_order = ["path", "sha1", "md5", "date", "size"]
    sorted_file_info = [
        {key: item[key] for key in key_order if key in item} for item in file_info_list
    ]

    dir_path = Path(args.directory)
    dir_name = dir_path.name if dir_path.name else dir_path.resolve().name
    output_json = f"{dir_name}.json"

    try:
        output_path = Path(output_json)
        with output_path.open("w", encoding="utf-8") as json_file:
            json.dump(sorted_file_info, json_file, ensure_ascii=False, indent=4)
            json_file.write("\n")
        output_path.chmod(0o644)
        print(f"File information written to {output_json} ({len(sorted_file_info)} files)")
    except OSError as exception:
        raise SystemExit(
            f"Error: Could not write to output file '{output_json}': {exception}"
        ) from exception

    return os.EX_OK
