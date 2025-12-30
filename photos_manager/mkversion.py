#!/usr/bin/env python3
"""mkversion - Generate version information from a collection of JSON files.

This script processes JSON files in a specified directory, validates their
content, and generates a version file with metadata including:
- Total size
- File count
- Last modification timestamp
- File hashes
- A formatted version string

Usage:
    ./mkversion.py -a /path/to/archive

The version string follows the format "photos-SIZE-COUNT" where:
- SIZE is the total content size in terabytes
- COUNT is the last three digits of the total file count
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Constants
VERSION_PREFIX = "photos"
BYTES_PER_TB = 2**40


def find_json_files(directory: str) -> list[tuple[float, str]]:
    """Find all JSON files in a directory and return with modification times."""
    json_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".json"):
                try:
                    path = Path(root) / file
                    mtime = path.stat().st_mtime
                    json_files.append((mtime, str(path)))
                except (OSError, PermissionError) as exception:
                    print(f"Warning: Could not access {path}: {exception}")

    if not json_files:
        raise SystemExit("Error: No JSON files found in the directory.")

    return sorted(json_files, reverse=True)


def validate_and_process_json(file_paths: list[str]) -> tuple[int, int, dict[str, str]]:
    """Validate JSON files and extract size and count information.

    Returns (total_bytes, files_count, file_hashes).
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

            # Check required fields
            if not all(required_json_fields.issubset(set(item.keys())) for item in data):
                raise SystemExit(f"Error: JSON file {file_path} is missing required fields.")

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


def main() -> int:
    """Main function that processes JSON files and generates a version JSON.

    The function:
    1. Parses command line arguments
    2. Validates the archive path
    3. Finds and processes JSON files
    4. Calculates total size and file counts
    5. Generates version information and timestamps
    6. Outputs the result as formatted JSON

    Returns:
        int: Exit code (os.EX_OK on success)
    """
    parser = argparse.ArgumentParser(description="Generate version JSON")
    parser.add_argument(
        "-a", dest="arch_path", default="/work", help="Archive path (default: /work)"
    )
    args = parser.parse_args()

    # Validate arch_path
    arch_path = Path(args.arch_path)
    if not arch_path.is_dir() or not os.access(args.arch_path, os.R_OK):
        raise SystemExit(
            f"Error: The directory '{args.arch_path}' does not exist or is not readable."
        )

    # Find JSON files
    json_files_with_mtimes = find_json_files(args.arch_path)
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
    print(json.dumps(output, indent=4))

    return os.EX_OK


if __name__ == "__main__":
    sys.exit(main())
