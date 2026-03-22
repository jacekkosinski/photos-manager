"""manifest - Generate manifest information from a collection of JSON files.

This script processes JSON files in a specified directory, validates their
content, and generates a manifest file with metadata including:
- Total size in bytes and terabytes
- Total file count across all JSON files
- Last modification timestamp of the most recently modified JSON file
- SHA1 hashes of each JSON file for integrity verification
- A formatted version string for easy identification

The script recursively scans a directory tree for JSON files, where each JSON
file is expected to contain an array of objects with the following required fields:
    - md5: MD5 hash of the file
    - path: File path
    - sha1: SHA1 hash of the file
    - size: File size in bytes
    - date: File date/timestamp

Note: Files ending with 'version.json' (e.g., .version.json, archive.version.json)
are automatically excluded from processing as they contain version metadata rather
than photo archive data.

Usage:
    photos manifest /path/to/archive
    photos manifest /path/to/archive --output custom.json
    photos manifest /path/to/archive -o version.json

The version string follows the format "PREFIX-SIZE-COUNT" where:
- PREFIX is the archive name (default: "photos", configurable with --prefix)
- SIZE is the total content size in terabytes (3 decimal places)
- COUNT is the last three digits of the total file count (modulo 1000, zero-padded to 3 digits)

Example output:
    {
        "version": "photos-2.456-234",
        "total_bytes": 2701131776000,
        "file_count": 12234,
        "last_modified": "2025-12-30T12:34:56+01:00",
        "last_verified": "2025-12-30T13:45:23+01:00",
        "files": {
            "archive1.json": "a1b2c3d4e5f6...",
            "archive2.json": "f6e5d4c3b2a1..."
        }
    }

Exit codes:
    0 (os.EX_OK): Success
    1 (SystemExit): Error occurred (invalid directory, no JSON files, validation failure)
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

from photos_manager.common import (
    calculate_checksums_strict,
    find_json_files_with_mtime,
    load_metadata_json,
    validate_directory,
    write_manifest_json,
)

# Constants
VERSION_PREFIX = "photos"
BYTES_PER_TB = 2**40


def validate_and_process_json(file_paths: list[str]) -> tuple[int, int, dict[str, str]]:
    """Validate JSON files and extract size and count information.

    Processes each JSON file to:
    1. Calculate SHA1 hash of the entire JSON file (for integrity checking)
    2. Parse and validate JSON structure
    3. Verify all required fields are present in each JSON object
    4. Sum up total bytes from all 'size' fields
    5. Count total number of entries across all files

    Each JSON file must contain an array of objects, where each object has
    the required fields: md5, path, sha1, size, and date.

    Args:
        file_paths: List of absolute or relative file paths to JSON files
            that need to be validated and processed.

    Returns:
        A tuple containing three elements:
            - int: Total bytes - sum of all 'size' fields from all JSON entries
            - int: Total count - total number of objects across all JSON files
            - dict[str, str]: Mapping of JSON filenames (basename only) to their
              SHA1 hash (hex digest)

    Raises:
        SystemExit: If any of the following conditions occur:
            - JSON file does not contain an array (must be a list/array at root level)
            - JSON array contains non-object items (all items must be dictionaries)
            - JSON file is missing required fields (md5, path, sha1, size, date)
            - JSON file contains invalid/malformed JSON syntax
            - JSON file cannot be read (permission denied, file not found, etc.)

    Note:
        SHA1 is used for file integrity verification only (usedforsecurity=False),
        not for cryptographic security purposes. This satisfies security linters
        while maintaining compatibility with existing hash formats.

    Examples:
        >>> paths = ['/archive/file1.json', '/archive/file2.json']
        >>> total, count, hashes = validate_and_process_json(paths)
        >>> total
        1234567890
        >>> count
        5432
        >>> hashes
        {'file1.json': 'a1b2c3...', 'file2.json': 'd4e5f6...'}
    """
    total_bytes = 0
    files_count = 0
    file_hashes = {}

    for file_path in file_paths:
        filename = Path(file_path).name
        try:
            sha1_hex = calculate_checksums_strict(file_path)[0]
            data = load_metadata_json(file_path)

            total_bytes += sum(int(item["size"]) for item in data)
            files_count += len(data)
            file_hashes[filename] = sha1_hex

        except OSError as exception:
            raise SystemExit(f"Error: Could not read {file_path}: {exception}") from exception

    return total_bytes, files_count, file_hashes


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for manifest command.

    Adds all command-line arguments for the manifest tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with manifest arguments.
    """
    parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=".",
        help="Path to the archive directory (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Output file path (default: .version.json inside the archive directory)",
    )
    parser.add_argument(
        "-P",
        "--prefix",
        default=VERSION_PREFIX,
        help=f"Archive name prefix for version string (default: {VERSION_PREFIX})",
    )


def run(args: argparse.Namespace) -> int:
    """Execute manifest command with parsed arguments.

    Processes JSON files and generates a version JSON with aggregate statistics,
    version string, timestamps, and file hashes.

    Workflow:
        1. Validates that the archive path exists and is readable
        2. Recursively finds all JSON files in the archive directory
        3. Validates and processes each JSON file
        4. Calculates aggregate statistics (total size, file count)
        5. Generates version string in format "PREFIX-SIZE-COUNT"
        6. Captures timestamps (last modification, verification time)
        7. Writes version information as formatted JSON to output file or stdout

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to archive directory
            - output: Optional output file path (None for stdout)
            - prefix: Archive name prefix for version string (default: 'photos')

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): Successful execution
            - 1 (SystemExit): Error occurred during processing

    Raises:
        SystemExit: If any of the following errors occur:
            - Archive directory does not exist or is not readable
            - No JSON files found in the archive directory
            - JSON validation fails (missing fields, invalid format)
            - Output file cannot be written

    Output:
        Writes JSON object with structure:
            {
                "version": "{prefix}-{TB:.3f}-{count%1000:03d}",
                "total_bytes": int,
                "file_count": int,
                "last_modified": str,   # ISO 8601 timestamp
                "last_verified": str,   # ISO 8601 timestamp
                "files": {filename: sha1_hash, ...}
            }

    Examples:
        >>> args = parser.parse_args(['/path/to/archive'])
        >>> exit_code = run(args)
        Manifest written to /path/to/archive/.version.json (1234 files)
    """
    directory_path = validate_directory(args.directory, check_readable=True)

    json_files_with_mtimes = find_json_files_with_mtime(args.directory)
    json_files = [path for (_, path) in json_files_with_mtimes]
    total_bytes, file_count, file_hashes = validate_and_process_json(json_files)

    total_tb = total_bytes / BYTES_PER_TB
    last_three_digits = file_count % 1000
    version = f"{args.prefix}-{total_tb:.3f}-{last_three_digits:03d}"

    newest_mtime = datetime.fromtimestamp(json_files_with_mtimes[0][0]).astimezone()
    last_modified = newest_mtime.isoformat(timespec="seconds")
    last_verified = datetime.now().astimezone().isoformat(timespec="seconds")

    output = {
        "version": version,
        "total_bytes": total_bytes,
        "file_count": file_count,
        "last_modified": last_modified,
        "last_verified": last_verified,
        "files": file_hashes,
    }
    output_file = args.output if args.output is not None else str(directory_path / ".version.json")

    write_manifest_json(output_file, output)

    mtime = json_files_with_mtimes[0][0]
    try:
        os.utime(output_file, (mtime, mtime))
    except OSError as exception:
        raise SystemExit(
            f"Error: Could not set mtime on '{output_file}': {exception}"
        ) from exception
    try:
        os.utime(directory_path, (mtime, mtime))
    except OSError as exception:
        raise SystemExit(
            f"Error: Could not set mtime on '{directory_path}': {exception}"
        ) from exception

    print(f"Manifest written to {output_file} ({file_count} files)")

    return os.EX_OK
