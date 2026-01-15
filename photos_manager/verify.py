#!/usr/bin/env python3
"""verify - Verify archive integrity based on JSON metadata.

This script verifies the integrity of photo archives by checking:
- File existence and accessibility
- File sizes match metadata
- File modification timestamps (mtime) match metadata
- Directory timestamps match newest file
- JSON file timestamps match newest entry
- SHA-1 and MD5 checksums (with --all flag, time-consuming)
- Version file integrity (.version.json)

The script scans a directory for JSON metadata files (excluding *version.json)
and optionally a .version.json file for comprehensive verification.

Usage:
    ./verify.py /path/to/archive
    ./verify.py /path/to/archive --all
    ./verify.py /path/to/archive --check-timestamps
    ./verify.py /path/to/archive --all --check-timestamps
    python -m photos_manager.verify /path/to/archive
"""

import argparse
import hashlib
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
        raise SystemExit(f"Error: JSON file '{file_path}' does not exist") from exception
    except json.JSONDecodeError as exception:
        raise SystemExit(f"Error: JSON file '{file_path}' contains invalid format") from exception


def load_version_json(file_path: str) -> dict[str, Any]:
    """Load version JSON data from a file.

    Reads a version JSON file created by mkversion and parses it.

    Args:
        file_path: Path to the version JSON file to load.

    Returns:
        Dictionary containing version information with keys: version,
        total_bytes, file_count, last_modified, last_verified, files.

    Raises:
        SystemExit: If the file cannot be read or contains invalid JSON.

    Examples:
        >>> data = load_version_json(".version.json")
        >>> data['version']
        'photos-2.456-234'
    """
    try:
        path = Path(file_path)
        with path.open(encoding="utf-8") as json_file:
            return cast("dict[str, Any]", json.load(json_file))
    except FileNotFoundError as exception:
        raise SystemExit(f"Error: Version file '{file_path}' does not exist") from exception
    except json.JSONDecodeError as exception:
        raise SystemExit(
            f"Error: Version file '{file_path}' contains invalid format"
        ) from exception


def find_json_files(directory: str) -> list[str]:
    """Find all JSON metadata files in a directory.

    Recursively walks through the directory tree starting from the specified
    directory and collects all files with .json extension, excluding files
    ending with 'version.json'.

    Args:
        directory: Path to the root directory to search for JSON files.

    Returns:
        List of absolute paths to JSON metadata files, sorted by name.

    Raises:
        SystemExit: If no JSON files are found in the directory tree.

    Examples:
        >>> files = find_json_files("/path/to/archive")
        >>> files[0]
        '/path/to/archive/data/file1.json'
    """
    json_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            # Skip version.json files (they have different structure)
            if file.endswith(".json") and not file.endswith("version.json"):
                path = Path(root) / file
                json_files.append(str(path))

    if not json_files:
        raise SystemExit("Error: No JSON metadata files found in the directory")

    return sorted(json_files)


def find_version_file(directory: str) -> str | None:
    """Find version JSON file in directory.

    Searches for .version.json file in the specified directory (non-recursive).

    Args:
        directory: Path to the directory to search.

    Returns:
        Path to version file if found, None otherwise.

    Examples:
        >>> version_file = find_version_file("/path/to/archive")
        >>> version_file
        '/path/to/archive/.version.json'
    """
    version_path = Path(directory) / ".version.json"
    if version_path.exists():
        return str(version_path)
    return None


def calculate_checksums(file_path: str) -> tuple[str, str]:
    """Calculate SHA-1 and MD5 checksums for a given file.

    Args:
        file_path: Path to the file to calculate checksums for.

    Returns:
        Tuple containing SHA-1 and MD5 checksums as hex strings.

    Raises:
        OSError: If file cannot be read.

    Examples:
        >>> sha1, md5 = calculate_checksums("/path/to/file.jpg")
        >>> len(sha1)
        40
        >>> len(md5)
        32
    """
    sha1_hash = hashlib.sha1(usedforsecurity=False)
    md5_hash = hashlib.md5(usedforsecurity=False)

    path = Path(file_path)
    with path.open("rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha1_hash.update(byte_block)
            md5_hash.update(byte_block)

    return sha1_hash.hexdigest(), md5_hash.hexdigest()


def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA-1 hash of entire file for version verification.

    Args:
        file_path: Path to the file to hash.

    Returns:
        SHA-1 hash as hex string.

    Raises:
        OSError: If file cannot be read.

    Examples:
        >>> hash_val = calculate_file_hash("archive.json")
        >>> len(hash_val)
        40
    """
    sha1_hash = hashlib.sha1(usedforsecurity=False)
    path = Path(file_path)
    with path.open("rb") as f:
        sha1_hash.update(f.read())
    return sha1_hash.hexdigest()


def verify_file_entry(
    entry: dict[str, str | int], verify_checksums: bool = False
) -> tuple[bool, list[str]]:
    """Verify a single file entry from JSON metadata.

    Checks file existence, size, and optionally checksums against metadata.

    Args:
        entry: Dictionary containing file metadata with keys: path, sha1, md5,
            date, size.
        verify_checksums: If True, calculate and verify SHA-1 and MD5 checksums
            (time-consuming). Defaults to False.

    Returns:
        Tuple containing:
            - bool: True if all checks pass, False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> entry = {'path': '/photo.jpg', 'size': 1234, 'sha1': '...', 'md5': '...', 'date': '...'}
        >>> success, errors = verify_file_entry(entry, verify_checksums=False)
        >>> success
        True
    """
    errors = []
    file_path = str(entry.get("path", ""))
    expected_size = entry.get("size")

    if not file_path:
        errors.append("Missing 'path' field in entry")
        return False, errors

    path = Path(file_path)

    # Check file existence
    if not path.exists():
        errors.append(f"File not found: {file_path}")
        return False, errors

    if not path.is_file():
        errors.append(f"Path is not a file: {file_path}")
        return False, errors

    # Check file size
    try:
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            errors.append(
                f"Size mismatch for {file_path}: expected {expected_size}, got {actual_size}"
            )
    except OSError as e:
        errors.append(f"Cannot stat file {file_path}: {e}")
        return False, errors

    # Optionally verify checksums
    if verify_checksums:
        try:
            actual_sha1, actual_md5 = calculate_checksums(file_path)
            expected_sha1 = str(entry.get("sha1", ""))
            expected_md5 = str(entry.get("md5", ""))

            if actual_sha1 != expected_sha1:
                errors.append(
                    f"SHA-1 mismatch for {file_path}: expected {expected_sha1}, got {actual_sha1}"
                )

            if actual_md5 != expected_md5:
                errors.append(
                    f"MD5 mismatch for {file_path}: expected {expected_md5}, got {actual_md5}"
                )
        except OSError as e:
            errors.append(f"Cannot read file for checksum verification {file_path}: {e}")
            return False, errors

    return len(errors) == 0, errors


def verify_timestamps(
    entry: dict[str, str | int], tolerance_seconds: int = 1
) -> tuple[bool, list[str]]:
    """Verify file modification timestamp matches metadata.

    Args:
        entry: Dictionary containing file metadata with 'path' and 'date' fields.
        tolerance_seconds: Allowed difference in seconds between expected and
            actual timestamps. Defaults to 1 second.

    Returns:
        Tuple containing:
            - bool: True if timestamp matches (within tolerance), False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> entry = {'path': '/photo.jpg', 'date': '2024-01-01T12:00:00+0100'}
        >>> success, errors = verify_timestamps(entry)
        >>> success
        True
    """
    errors = []
    file_path = str(entry.get("path", ""))
    expected_date = str(entry.get("date", ""))

    if not file_path or not expected_date:
        errors.append(f"Missing path or date field in entry: {entry}")
        return False, errors

    path = Path(file_path)
    if not path.exists():
        errors.append(f"File not found: {file_path}")
        return False, errors

    try:
        # Get actual modification time
        actual_mtime = int(path.stat().st_mtime)

        # Parse expected timestamp
        expected_mtime = int(datetime.fromisoformat(expected_date).timestamp())

        # Compare with tolerance
        diff = abs(actual_mtime - expected_mtime)
        if diff > tolerance_seconds:
            errors.append(
                f"Timestamp mismatch for {file_path}: "
                f"expected {expected_date} ({expected_mtime}), "
                f"got {datetime.fromtimestamp(actual_mtime)} ({actual_mtime}), "
                f"diff: {diff}s"
            )
    except ValueError as e:
        errors.append(f"Invalid date format in metadata for {file_path}: {e}")
        return False, errors
    except OSError as e:
        errors.append(f"Cannot stat file {file_path}: {e}")
        return False, errors

    return len(errors) == 0, errors


def verify_directory_timestamps(data: list[dict[str, str | int]]) -> tuple[int, list[str]]:
    """Verify directory timestamps match newest file in each directory.

    Args:
        data: List of file metadata entries from JSON.

    Returns:
        Tuple containing:
            - int: Number of directories checked
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> data = [{'path': '/photos/2024/img1.jpg', 'date': '2024-12-31T23:59:59+0100'}]
        >>> count, errors = verify_directory_timestamps(data)
        >>> count >= 0
        True
    """
    errors = []

    # Group files by directory
    dir_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in data:
        file_path = str(entry.get("path", ""))
        if not file_path:
            continue

        dir_path = str(Path(file_path).parent)
        if dir_path not in dir_files:
            dir_files[dir_path] = []
        dir_files[dir_path].append(entry)

    # Check each directory
    for dir_path, files in dir_files.items():
        path = Path(dir_path)
        if not path.exists() or not path.is_dir():
            errors.append(f"Directory not found or not accessible: {dir_path}")
            continue

        try:
            # Find newest file in directory
            newest_file = max(files, key=lambda x: datetime.fromisoformat(str(x["date"])))
            newest_file_path = Path(str(newest_file["path"]))

            if not newest_file_path.exists():
                continue

            # Get timestamps
            dir_mtime = int(path.stat().st_mtime)
            file_mtime = int(newest_file_path.stat().st_mtime)

            if dir_mtime != file_mtime:
                errors.append(
                    f"Directory timestamp mismatch for {dir_path}: "
                    f"expected {file_mtime} (from {newest_file_path.name}), "
                    f"got {dir_mtime}, diff: {abs(dir_mtime - file_mtime)}s"
                )
        except (ValueError, OSError) as e:
            errors.append(f"Error checking directory {dir_path}: {e}")

    return len(dir_files), errors


def verify_json_file_timestamp(
    json_file: str, data: list[dict[str, str | int]]
) -> tuple[bool, list[str]]:
    """Verify JSON file timestamp matches newest entry.

    Args:
        json_file: Path to the JSON metadata file.
        data: List of file metadata entries from the JSON file.

    Returns:
        Tuple containing:
            - bool: True if timestamp matches, False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> data = [{'path': '/photo.jpg', 'date': '2024-01-01T12:00:00+0100'}]
        >>> success, errors = verify_json_file_timestamp("archive.json", data)
    """
    errors = []

    if not data:
        errors.append(f"No data to verify JSON timestamp for {json_file}")
        return False, errors

    json_path = Path(json_file)
    if not json_path.exists():
        errors.append(f"JSON file not found: {json_file}")
        return False, errors

    try:
        # Find newest entry
        newest_entry = max(data, key=lambda x: datetime.fromisoformat(str(x["date"])))
        newest_file_path = Path(str(newest_entry["path"]))

        if not newest_file_path.exists():
            errors.append(f"Newest file not found: {newest_file_path}")
            return False, errors

        # Get timestamps
        json_mtime = int(json_path.stat().st_mtime)
        file_mtime = int(newest_file_path.stat().st_mtime)

        if json_mtime != file_mtime:
            errors.append(
                f"JSON file timestamp mismatch for {json_file}: "
                f"expected {file_mtime} (from {newest_file_path.name}), "
                f"got {json_mtime}, diff: {abs(json_mtime - file_mtime)}s"
            )
            return False, errors

    except (ValueError, KeyError, OSError) as e:
        errors.append(f"Error verifying JSON timestamp for {json_file}: {e}")
        return False, errors

    return True, errors


def verify_version_file(
    version_file: str, json_files: list[str], all_data: list[dict[str, str | int]]
) -> tuple[bool, list[str]]:
    """Verify version file integrity and consistency.

    Args:
        version_file: Path to the version JSON file.
        json_files: List of JSON metadata files that should be in version file.
        all_data: Combined data from all JSON files for total verification.

    Returns:
        Tuple containing:
            - bool: True if all checks pass, False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> success, errors = verify_version_file(".version.json", ["a.json"], data)
    """
    errors = []

    try:
        version_data = load_version_json(version_file)
    except SystemExit as e:
        return False, [str(e)]

    # Verify required fields
    required_fields = ["version", "total_bytes", "file_count", "files"]
    for field in required_fields:
        if field not in version_data:
            errors.append(f"Version file missing required field: {field}")

    if errors:
        return False, errors

    # Verify file hashes
    version_files = version_data.get("files", {})
    for json_file in json_files:
        json_basename = Path(json_file).name

        if json_basename not in version_files:
            errors.append(f"JSON file {json_basename} not listed in version file")
            continue

        expected_hash = version_files[json_basename]
        try:
            actual_hash = calculate_file_hash(json_file)
            if actual_hash != expected_hash:
                errors.append(
                    f"Hash mismatch for {json_basename}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )
        except OSError as e:
            errors.append(f"Cannot read {json_file} for hash verification: {e}")

    # Verify totals
    expected_total_bytes = version_data.get("total_bytes", 0)
    expected_file_count = version_data.get("file_count", 0)

    actual_total_bytes = sum(int(entry.get("size", 0)) for entry in all_data)
    actual_file_count = len(all_data)

    if actual_total_bytes != expected_total_bytes:
        errors.append(
            f"Total bytes mismatch: expected {expected_total_bytes}, got {actual_total_bytes}"
        )

    if actual_file_count != expected_file_count:
        errors.append(
            f"File count mismatch: expected {expected_file_count}, got {actual_file_count}"
        )

    return len(errors) == 0, errors


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for verify command.

    Adds all command-line arguments for the verify tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with verify arguments.
    """
    parser.add_argument("directory", type=str, help="Path to the archive directory")
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Verify SHA-1 and MD5 checksums (time-consuming)",
    )
    parser.add_argument(
        "-t",
        "--check-timestamps",
        action="store_true",
        help="Verify file and directory timestamps match metadata",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=1,
        help="Timestamp tolerance in seconds (default: 1)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute verify command with parsed arguments.

    Performs comprehensive verification of photo archives including file
    existence, sizes, timestamps, and optionally checksums.

    The script scans the specified directory for JSON metadata files and
    optionally a .version.json file, then performs verification:
    1. Verifies all files exist and are accessible
    2. Verifies file sizes match metadata
    3. Optionally verifies file timestamps (with check_timestamps flag)
    4. Optionally verifies SHA-1 and MD5 checksums (with all flag, time-consuming)
    5. Optionally verifies directory timestamps (with check_timestamps flag)
    6. Optionally verifies JSON file timestamps (with check_timestamps flag)
    7. If .version.json found, verifies version integrity

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to archive directory containing JSON files
            - all: Whether to verify SHA-1 and MD5 checksums (time-consuming)
            - check_timestamps: Whether to verify file and directory timestamps
            - tolerance: Timestamp tolerance in seconds

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): All verifications passed
            - 1: One or more verifications failed

    Examples:
        >>> args = parser.parse_args(['/path/to/archive'])
        >>> exit_code = run(args)
        Scanning directory: /path/to/archive
        Found 2 JSON metadata file(s)
        ...
    """
    # Validate directory
    directory_path = Path(args.directory)
    if not directory_path.is_dir() or not os.access(args.directory, os.R_OK):
        raise SystemExit(
            f"Error: The directory '{args.directory}' does not exist or is not readable"
        )

    # Find JSON files
    print(f"Scanning directory: {args.directory}")
    try:
        json_files = find_json_files(args.directory)
    except SystemExit as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Found {len(json_files)} JSON metadata file(s)")

    # Find version file
    version_file = find_version_file(args.directory)
    if version_file:
        print(f"Found version file: {Path(version_file).name}")

    if args.all:
        print("WARNING: Full checksum verification enabled (this may take a while)")
    if args.check_timestamps:
        print("Timestamp verification enabled")

    total_files = 0
    total_errors = 0
    all_data: list[dict[str, str | int]] = []

    # Verify each JSON file
    for json_file in json_files:
        print(f"\nVerifying {Path(json_file).name}...")

        try:
            data = load_json(json_file)
            all_data.extend(data)
            file_count = len(data)
            total_files += file_count
            errors_in_file = 0

            print(f"  Found {file_count} file entries")

            # Verify each file entry
            for i, entry in enumerate(data, 1):
                success, errors = verify_file_entry(entry, verify_checksums=args.all)
                if not success:
                    errors_in_file += len(errors)
                    total_errors += len(errors)
                    for error in errors:
                        print(f"  Error: {error}", file=sys.stderr)

                # Progress indicator for large archives
                if args.all and i % 100 == 0:
                    print(f"  Progress: {i}/{file_count} files verified...")

            # Verify timestamps if requested
            if args.check_timestamps:
                print("  Verifying file timestamps...")
                for entry in data:
                    success, errors = verify_timestamps(entry, args.tolerance)
                    if not success:
                        errors_in_file += len(errors)
                        total_errors += len(errors)
                        for error in errors:
                            print(f"  Error: {error}", file=sys.stderr)

                # Verify directory timestamps
                print("  Verifying directory timestamps...")
                dir_count, errors = verify_directory_timestamps(data)
                if errors:
                    errors_in_file += len(errors)
                    total_errors += len(errors)
                    for error in errors:
                        print(f"  Error: {error}", file=sys.stderr)
                else:
                    print(f"  Verified {dir_count} directories")

                # Verify JSON file timestamp
                print("  Verifying JSON file timestamp...")
                success, errors = verify_json_file_timestamp(json_file, data)
                if not success:
                    errors_in_file += len(errors)
                    total_errors += len(errors)
                    for error in errors:
                        print(f"  Error: {error}", file=sys.stderr)
                else:
                    print("  JSON file timestamp OK")

            if errors_in_file == 0:
                print(f"  PASS: All {file_count} files verified successfully")
            else:
                print(
                    f"  FAIL: Found {errors_in_file} error(s) in {Path(json_file).name}",
                    file=sys.stderr,
                )

        except SystemExit as e:
            print(f"  Error: {e}", file=sys.stderr)
            total_errors += 1

    # Verify version file if found
    if version_file:
        print(f"\nVerifying version file {Path(version_file).name}...")
        success, errors = verify_version_file(version_file, json_files, all_data)
        if not success:
            total_errors += len(errors)
            for error in errors:
                print(f"  Error: {error}", file=sys.stderr)
        else:
            print("  Version file verified successfully")

    # Summary
    print(f"\n{'=' * 60}")
    print("Verification complete:")
    print(f"  Total files checked: {total_files}")
    print(f"  Total errors found: {total_errors}")

    if total_errors == 0:
        print("  Result: PASS - All verifications passed")
        return os.EX_OK

    print(f"  Result: FAIL - Verification failed with {total_errors} error(s)", file=sys.stderr)
    return 1


def main() -> int:
    """Main entry point for standalone execution.

    Creates argument parser, configures it with setup_parser(),
    parses command-line arguments, and executes run().

    This function exists for backward compatibility and standalone
    execution. The unified CLI uses setup_parser() and run() directly.

    Returns:
        int: Exit code from run()
            - os.EX_OK (0): All verifications passed
            - 1: One or more verifications failed
    """
    parser = argparse.ArgumentParser(description="Verify archive integrity based on JSON metadata.")
    setup_parser(parser)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
