"""index - Generate JSON metadata file from a directory of files.

This script recursively scans a directory and generates a JSON file containing
metadata for each file found. The output file is named after the source directory
(e.g., scanning ``photos/`` produces ``photos.json`` in the current directory).

Each entry in the output JSON array contains the following fields:
    - path: Absolute path to the file
    - sha1: SHA1 checksum of the file contents
    - md5: MD5 checksum of the file contents
    - date: File modification timestamp in ISO 8601 format with timezone offset
    - size: File size in bytes

The script validates the result for duplicate paths, SHA1 hashes, and MD5 hashes
before writing. An optional merge flag allows combining a newly scanned directory
with an existing JSON file (e.g., to build a composite index from multiple sources).

Three mutually exclusive sort orders are available:
    - Default: by modification timestamp, then filename
    - ``--sort-by-number`` (``-n``): numerically by number embedded in the
      parent directory name, then by number in the filename
    - ``--sort-by-dir`` (``-D``): by parent directory path, then by
      modification timestamp, then filename

Usage:
    photos index /path/to/photos
    photos index /path/to/photos --merge existing.json
    photos index /path/to/photos --sort-by-number
    photos index /path/to/photos --sort-by-dir --time-zone UTC

Example output (photos.json):
    [
        {
            "path": "/archive/photos/IMG_0001.jpg",
            "sha1": "a1b2c3d4e5f6...",
            "md5": "f6e5d4c3b2a1...",
            "date": "2024-06-15T14:32:10+02:00",
            "size": 4823041
        }
    ]

Exit codes:
    0 (os.EX_OK): Success
    1 (SystemExit): Error occurred (invalid directory, duplicate hashes, write failure)
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

# Constants
DUPLICATE_CHECK_KEYS = ["path", "sha1", "md5"]


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
    parser.add_argument(
        "directory",
        type=str,
        help="Path to the source directory",
    )
    parser.add_argument(
        "-m",
        "--merge",
        required=False,
        metavar="JSON",
        help="Path to the JSON file to merge",
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

    Scans the source directory recursively, collects file metadata, optionally
    merges with an existing JSON file, validates for duplicates, sorts results,
    and writes the output JSON file to the current working directory.

    Workflow:
        1. Validates that the source directory exists and is a directory
        2. Recursively scans all files and computes SHA1, MD5, size, and
           modification timestamp for each
        3. If ``--merge`` is given, loads and validates the existing JSON file
           and appends its entries to the scanned results
        4. Checks the combined list for duplicate paths, SHA1 hashes, and
           MD5 hashes — aborts if any are found
        5. Sorts the entries according to the selected sort mode
        6. Writes the result to ``<dirname>.json`` in the current directory
           with 644 permissions

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to source directory to scan
            - merge: Optional path to an existing JSON metadata file to merge
            - time_zone: IANA timezone name for modification timestamps
              (default: ``'Europe/Warsaw'``)
            - sort_by_number: If True, sort numerically by number embedded in
              the parent directory name, then by number in the filename
            - sort_by_dir: If True, sort by parent directory path, then by
              modification timestamp, then by filename

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): Successful execution
            - 1 (SystemExit): Error occurred during processing

    Raises:
        SystemExit: If any of the following errors occur:
            - Source directory does not exist or is not a directory
            - Merge file does not exist, cannot be read, or contains invalid JSON
            - Duplicate path, SHA1, or MD5 found in the combined entry list
            - Output file cannot be written

    Output:
        Writes a JSON array to ``<dirname>.json`` in the current directory,
        where each element has the structure::

            {
                "path": "/archive/photos/IMG_0001.jpg",
                "sha1": "a1b2c3d4e5f6...",
                "md5":  "f6e5d4c3b2a1...",
                "date": "2024-06-15T14:32:10+02:00",
                "size": 4823041
            }

    Examples:
        >>> args = parser.parse_args(['/path/to/photos'])
        >>> exit_code = run(args)
        File information written to photos.json (42 files)
    """
    validate_directory(args.directory)

    file_info_list = scan_files(args.directory, time_zone=args.time_zone)

    if args.merge:
        file_info_list.extend(load_metadata_json(args.merge))

    for key in DUPLICATE_CHECK_KEYS:
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
    n = len(file_info_list)
    print(f"File information written to {output_json} ({n} file{'s' if n != 1 else ''})")

    return os.EX_OK
