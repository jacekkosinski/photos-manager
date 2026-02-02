"""mkversion - Generate version information from a collection of JSON files.

This script processes JSON files in a specified directory, validates their
content, and generates a version file with metadata including:
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
    photos mkversion /path/to/archive
    photos mkversion /path/to/archive --output custom.json
    photos mkversion /path/to/archive -o version.json

The version string follows the format "photos-SIZE-COUNT" where:
- SIZE is the total content size in terabytes (3 decimal places)
- COUNT is the last three digits of the total file count (modulo 1000)

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
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from photos_manager.common import find_json_files_with_mtime as find_json_files

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
    required_json_fields = {"md5", "path", "sha1", "size", "date"}

    total_bytes = 0
    files_count = 0
    file_hashes = {}

    for file_path in file_paths:
        path = Path(file_path)
        filename = path.name
        try:
            # Calculate SHA1 while reading (for file integrity, not security)
            sha1 = hashlib.sha1(usedforsecurity=False)
            with path.open("rb") as file:
                content = file.read()
                sha1.update(content)

            # Parse and validate JSON
            data = json.loads(content)

            # Validate that data is a list
            if not isinstance(data, list):
                raise SystemExit(
                    f"Error: JSON file {file_path} must contain an array of objects, "
                    f"got {type(data).__name__}"
                )

            # Validate that all items are dictionaries
            if not all(isinstance(item, dict) for item in data):
                raise SystemExit(f"Error: JSON file {file_path} must contain an array of objects")

            # Check required fields
            if not all(required_json_fields.issubset(set(item.keys())) for item in data):
                raise SystemExit(
                    f"Error: JSON file {file_path} is missing required fields "
                    f"(md5, path, sha1, size, date)"
                )

            # Sum sizes and count files
            total_bytes += sum(item["size"] for item in data)
            files_count += len(data)

            # Store hash
            file_hashes[filename] = sha1.hexdigest()

        except json.JSONDecodeError as exception:
            raise SystemExit(f"Error: Invalid JSON in {file_path}") from exception
        except (OSError, PermissionError) as exception:
            raise SystemExit(f"Error: Could not read {file_path}: {exception}") from exception

    return total_bytes, files_count, file_hashes


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for mkversion command.

    Adds all command-line arguments for the mkversion tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with mkversion arguments.
    """
    parser.add_argument("directory", type=str, help="Path to the archive directory")
    parser.add_argument(
        "-o",
        "--output",
        dest="output_file",
        default=None,
        help="Output file path (if not specified, writes to stdout)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute mkversion command with parsed arguments.

    Processes JSON files and generates a version JSON with aggregate statistics,
    version string, timestamps, and file hashes.

    Workflow:
        1. Validates that the archive path exists and is readable
        2. Recursively finds all JSON files in the archive directory
        3. Validates and processes each JSON file
        4. Calculates aggregate statistics (total size, file count)
        5. Generates version string in format "photos-SIZE-COUNT"
        6. Captures timestamps (last modification, verification time)
        7. Writes version information as formatted JSON to output file or stdout

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to archive directory
            - output_file: Optional output file path (None for stdout)

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
                "version": "photos-{TB:.3f}-{count%1000}",
                "total_bytes": int,
                "file_count": int,
                "last_modified": str,   # ISO 8601 timestamp
                "last_verified": str,   # ISO 8601 timestamp
                "files": {filename: sha1_hash, ...}
            }

    Examples:
        >>> args = parser.parse_args(['/path/to/archive'])
        >>> exit_code = run(args)
    """
    # Validate directory
    directory_path = Path(args.directory)
    if not directory_path.is_dir() or not os.access(args.directory, os.R_OK):
        raise SystemExit(
            f"Error: The directory '{args.directory}' does not exist or is not readable"
        )

    # Find JSON files
    json_files_with_mtimes = find_json_files(args.directory)
    json_files = [path for (_, path) in json_files_with_mtimes]

    # Process JSON files
    total_bytes, file_count, file_hashes = validate_and_process_json(json_files)

    # Calculate TB with proper formatting and get last three digits of files count
    total_tb = total_bytes / BYTES_PER_TB
    tb_str = f"{total_tb:.3f}"
    last_three_digits = file_count % 1000

    # Get timestamps
    youngest_mtime = datetime.fromtimestamp(json_files_with_mtimes[0][0]).astimezone()
    last_modified = youngest_mtime.isoformat(timespec="seconds")
    last_verified = datetime.now().astimezone().isoformat(timespec="seconds")

    # Create version string
    version = f"photos-{tb_str}-{last_three_digits}"

    # Generate output JSON
    output = {
        "version": version,
        "total_bytes": total_bytes,
        "file_count": file_count,
        "last_modified": last_modified,
        "last_verified": last_verified,
        "files": file_hashes,
    }
    output_json = json.dumps(output, ensure_ascii=False, indent=4)

    # Write to file or stdout
    if args.output_file is None:
        print(output_json)
    else:
        try:
            output_path = Path(args.output_file)
            output_path.write_text(output_json, encoding="utf-8")
        except (OSError, PermissionError) as exception:
            raise SystemExit(
                f"Error: Could not write to output file '{args.output_file}': {exception}"
            ) from exception

    return os.EX_OK
