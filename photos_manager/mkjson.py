#!/usr/bin/env python3
"""mkjson - Generate JSON file with file metadata from directory.

This script recursively scans a directory and generates a JSON file containing
metadata for each file found:
- Path to the file
- SHA-1 and MD5 checksums
- File size in bytes
- Modification timestamp with timezone

Supports merging with existing JSON files and provides multiple sorting options.

Usage:
    ./mkjson.py /path/to/directory
    ./mkjson.py /path/to/directory --merge existing.json
    ./mkjson.py /path/to/directory --sort-by-number
    python -m photos_manager.mkjson /path/to/directory
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo


def calculate_checksums(file_path: str) -> tuple[str | None, str | None]:
    """Calculate SHA-1 and MD5 checksums for a given file.

    Args:
        file_path: Path to the file to calculate checksums for.

    Returns:
        Tuple containing SHA-1 and MD5 checksums as hex strings.
        Returns (None, None) if file cannot be read.

    Warnings:
        Files that cannot be accessed due to permission errors or OS errors
        are skipped with a warning message printed to stdout. The function
        returns (None, None) to allow processing to continue with other files.
    """
    sha1_hash = hashlib.sha1(usedforsecurity=False)
    md5_hash = hashlib.md5(usedforsecurity=False)

    try:
        path = Path(file_path)
        with path.open("rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha1_hash.update(byte_block)
                md5_hash.update(byte_block)
    except OSError as e:
        print(f"Warning: Could not access {file_path}: {e}")
        return None, None

    return sha1_hash.hexdigest(), md5_hash.hexdigest()


def get_file_info(directory: str, time_zone: str) -> list[dict[str, str | int]]:
    """Collect information about all files in a given directory.

    Recursively walks through the directory tree starting from the specified
    directory and collects metadata for each file found. For each file,
    calculates SHA-1 and MD5 checksums, retrieves file size and modification
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
            - sha1 (str): SHA-1 checksum as hex string
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
            'date': '2025-01-04T12:34:56+0100',
            'size': 1234567
        }
    """
    local_tz = ZoneInfo(time_zone)
    file_info_list: list[dict[str, str | int]] = []

    try:
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file

                # Calculate checksums
                sha1, md5 = calculate_checksums(str(file_path))
                if sha1 is None or md5 is None:
                    continue

                # Get file size and modification time
                stat_info = file_path.stat()
                size = stat_info.st_size
                mod_time = stat_info.st_mtime
                mod_time_with_tz = datetime.fromtimestamp(mod_time, local_tz).strftime(
                    "%Y-%m-%dT%H:%M:%S%z"
                )

                # Append file information to the list
                file_info_list.append(
                    {
                        "path": str(file_path),
                        "sha1": sha1,
                        "md5": md5,
                        "date": mod_time_with_tz,
                        "size": size,
                    }
                )
    except OSError as e:
        print(f"Warning: Error accessing directory {directory}: {e}", file=sys.stderr)

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


def load_json(file_path: str) -> list[dict[str, str | int]]:
    """Load JSON data from a file.

    Reads a JSON file and parses it into a list of dictionaries containing
    file metadata. This is a utility function for loading previously generated
    JSON files.

    Args:
        file_path: Path to the JSON file to load. Can be absolute or relative.

    Returns:
        List of dictionaries containing file information with keys matching
        the output format (path, sha1, md5, date, size).

    Raises:
        SystemExit: If the file does not exist or contains invalid JSON.

    Examples:
        >>> data = load_json("archive.json")
        >>> print(f"Loaded {len(data)} file entries")
        Loaded 42 file entries
    """
    try:
        path = Path(file_path)
        with path.open(encoding="utf-8") as json_file:
            data: Any = json.load(json_file)
            return cast("list[dict[str, str | int]]", data)
    except FileNotFoundError as exception:
        raise SystemExit(f"Error: JSON file '{file_path}' does not exist") from exception
    except json.JSONDecodeError as exception:
        raise SystemExit(f"Error: JSON file '{file_path}' contains invalid format") from exception


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for mkjson command.

    Adds all command-line arguments for the mkjson tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with mkjson arguments.
    """
    parser.add_argument("directory", type=str, help="Path to the source directory")
    parser.add_argument(
        "--merge", required=False, metavar="JSON", help="Path to the JSON file to merge"
    )
    parser.add_argument(
        "--time-zone",
        default=time.tzname[0],
        metavar="TZ",
        help=f"Time zone for modification time (default: {time.tzname[0]})",
    )
    parser.add_argument(
        "--sort-by-number",
        action="store_true",
        help="Sort files numerically by number in second directory and filename",
    )
    parser.add_argument(
        "--sort-by-dir",
        action="store_true",
        help="Sort files first by directory name and then by modification timestamp",
    )


def run(args: argparse.Namespace) -> int:
    """Execute mkjson command with parsed arguments.

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
            - 1 (SystemExit): Error occurred during processing

    Raises:
        SystemExit: If any of the following errors occur:
            - Source directory does not exist or is not a directory
            - Merge file cannot be read or contains invalid JSON
            - Duplicate paths, SHA-1, or MD5 hashes detected
            - Output file cannot be written

    Examples:
        >>> # Scan directory and create JSON
        >>> args = parser.parse_args(['/path/to/photos'])
        >>> exit_code = run(args)
        File information written to photos.json
    """
    # Ensure the directory exists
    if not Path(args.directory).is_dir():
        raise SystemExit(f"Error: The specified path '{args.directory}' is not a valid directory")

    # Get file information
    file_info_list = get_file_info(args.directory, args.time_zone)

    # Merge information from previous JSON file
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

    # Checks for duplicate 'path', 'sha1', and 'md5' in the list
    for key in ["path", "sha1", "md5"]:
        counts = Counter(entry[key] for entry in file_info_list)
        duplicates = [item for item, count in counts.items() if count > 1]

        if duplicates:
            duplicates_str = sorted(str(dup) for dup in duplicates)
            raise SystemExit(f"Error: Duplicate {key} found: {', '.join(duplicates_str)}")

    # Sort file information
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

    # Make custom keys order in dict data
    custom_order = ["path", "sha1", "md5", "date", "size"]
    sorted_file_info = [
        OrderedDict(sorted(item.items(), key=lambda x: custom_order.index(str(x[0]))))
        for item in file_info_list
    ]

    # Define output JSON file name
    dir_path = Path(args.directory)
    dir_name = dir_path.name if dir_path.name else dir_path.resolve().name
    output_json = f"{dir_name}.json"

    # Write file information to JSON file
    try:
        output_path = Path(output_json)
        with output_path.open("w", encoding="utf-8") as json_file:
            json.dump(sorted_file_info, json_file, ensure_ascii=False, indent=4)
            json_file.write("\n")  # Ensure newline at end of file
        print(f"File information written to {output_json}")
    except OSError as exception:
        raise SystemExit(
            f"Error: Could not write to output file '{output_json}': {exception}"
        ) from exception

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
        description="Generate JSON file with file information from a given directory."
    )
    setup_parser(parser)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
