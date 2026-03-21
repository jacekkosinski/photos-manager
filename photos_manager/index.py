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
import os
import re
from collections import Counter
from pathlib import Path

from photos_manager.common import (
    load_metadata_json,
    scan_files,
    validate_directory,
    write_metadata_json,
)


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
    validate_directory(args.directory)

    file_info_list = scan_files(args.directory, time_zone=args.time_zone)

    if args.merge:
        file_info_list.extend(load_metadata_json(args.merge))

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

    dir_path = Path(args.directory)
    dir_name = dir_path.name if dir_path.name else dir_path.resolve().name
    output_json = f"{dir_name}.json"

    write_metadata_json(output_json, file_info_list)
    print(f"File information written to {output_json} ({len(file_info_list)} files)")

    return os.EX_OK
