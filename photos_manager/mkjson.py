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
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
        return None, None

    return sha1_hash.hexdigest(), md5_hash.hexdigest()


def get_file_info(directory: str, time_zone: str) -> list[dict[str, str | int]]:
    """Collect information about all files in a given directory.

    Args:
        directory: Directory path to scan recursively.
        time_zone: Time zone for modification time formatting.

    Returns:
        List of dictionaries containing file information with keys:
        path, sha1, md5, date, size.
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
        print(f"Error accessing directory {directory}: {e}", file=sys.stderr)

    return file_info_list


def extract_numbers(path: str) -> tuple[int, int, str]:
    """Extract numbers from a given path.

    Args:
        path: Path string to extract numbers from.

    Returns:
        Tuple of (directory number, filename number, filename).
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


def load_json(file_path: str) -> list[dict[str, str | int]] | None:
    """Load JSON data from a file.

    Args:
        file_path: Path to the JSON file.

    Returns:
        List of dictionaries containing file information, or None on error.
    """
    try:
        path = Path(file_path)
        with path.open(encoding="utf-8") as json_file:
            data: Any = json.load(json_file)
            return cast(list[dict[str, str | int]], data)
    except FileNotFoundError:
        print(f"Error: JSON file '{file_path}' does not exist.", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(
            f"Error: JSON file '{file_path}' contains an invalid format.",
            file=sys.stderr,
        )
        return None


def main() -> None:
    """Generate JSON file with file information from a directory.

    This is the main entry point that processes command-line arguments,
    scans the directory, optionally merges with existing JSON, validates
    for duplicates, sorts results, and writes output JSON file.
    """
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="Generate JSON file with file information from a given directory."
    )
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
    args = parser.parse_args()

    # Ensure the directory exists
    if not Path(args.directory).is_dir():
        print(
            f"Error: The specified path '{args.directory}' is not a valid directory.",
            file=sys.stderr,
        )
        return

    # Get file information
    file_info_list = get_file_info(args.directory, args.time_zone)

    # Merge information from previous JSON file
    if args.merge:
        try:
            merge_path = Path(args.merge)
            with merge_path.open(encoding="utf-8") as json_file:
                merge_data = json.load(json_file)
                file_info_list.extend(merge_data)
        except FileNotFoundError:
            print(f"The specified merge file '{args.merge}' does not exist.")
            return
        except json.JSONDecodeError:
            print(
                f"Error: JSON file '{args.merge}' contains an invalid format.",
                file=sys.stderr,
            )
            return

    # Checks for duplicate 'path', 'sha1', and 'md5' in the list
    for key in ["path", "sha1", "md5"]:
        counts = Counter(entry[key] for entry in file_info_list)
        duplicates = [item for item, count in counts.items() if count > 1]

        if duplicates:
            duplicates_str = sorted(str(dup) for dup in duplicates)
            print(
                f"Error: Duplicate {key} found: {', '.join(duplicates_str)}",
                file=sys.stderr,
            )
            return

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
    except OSError as e:
        print(f"Error writing to JSON file {output_json}: {e}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
