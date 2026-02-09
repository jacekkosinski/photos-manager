"""verify - Verify archive integrity based on JSON metadata.

This script verifies the integrity of photo archives by checking:
- File existence and accessibility
- File sizes match metadata
- File modification timestamps (mtime) match metadata
- Directory timestamps match newest file
- JSON file timestamps match newest entry
- Archive directory timestamp matches newest JSON file (with --check-timestamps)
- SHA1 and MD5 checksums (with --all flag, time-consuming)
- Version file integrity (.version.json)
- Extra files in filesystem not present in metadata (with --check-extra-files)
- Extra JSON files not listed in .version.json (with --check-extra-files)

The script scans a directory for JSON metadata files (excluding *version.json)
and optionally a .version.json file for comprehensive verification.

Usage:
    photos verify /path/to/archive
    photos verify /path/to/archive --all
    photos verify /path/to/archive --check-timestamps
    photos verify /path/to/archive --all --check-timestamps
    photos verify /path/to/archive --check-extra-files
"""

import argparse
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from photos_manager.common import (
    calculate_checksums_strict as calculate_checksums,
)
from photos_manager.common import (
    find_json_files,
    load_json,
)


def load_version_json(file_path: str) -> dict[str, Any]:
    """Load version JSON data from a file.

    Reads a version JSON file created by manifest and parses it.

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
    base_path = Path(directory).resolve()
    version_path = base_path / ".version.json"
    if version_path.exists():
        return str(version_path)
    return None


def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA1 hash of entire file for version verification.

    Args:
        file_path: Path to the file to hash.

    Returns:
        SHA1 hash as hex string.

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


def normalize_paths(
    data: list[dict[str, str | int]], base_directory: str
) -> list[dict[str, str | int]]:
    """Normalize relative paths in metadata to absolute paths.

    Converts relative file paths in JSON metadata to absolute paths based on
    the archive directory. This ensures that verification works correctly
    regardless of the current working directory.

    Args:
        data: List of file metadata dictionaries.
        base_directory: Base directory of the archive (used to resolve relative paths).

    Returns:
        list: Modified data with absolute paths.

    Examples:
        >>> data = [{'path': 'photos/img.jpg', 'size': 100}]
        >>> normalized = normalize_paths(data, '/archive')
        >>> normalized[0]['path']
        '/archive/photos/img.jpg'
    """
    base_path = Path(base_directory).resolve()

    for entry in data:
        if "path" in entry:
            file_path = Path(str(entry["path"]))
            # If path is relative, make it absolute relative to base_directory
            if not file_path.is_absolute():
                entry["path"] = str(base_path / file_path)

    return data


def verify_file_entry(
    entry: dict[str, str | int], verify_checksums: bool = False
) -> tuple[bool, list[str]]:
    """Verify a single file entry from JSON metadata.

    Checks file existence, size, and optionally checksums against metadata.

    Args:
        entry: Dictionary containing file metadata with keys: path, sha1, md5,
            date, size.
        verify_checksums: If True, calculate and verify SHA1 and MD5 checksums
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

    if not path.exists():
        errors.append(f"File not found: {file_path}")
        return False, errors

    if not path.is_file():
        errors.append(f"Path is not a file: {file_path}")
        return False, errors

    try:
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            errors.append(
                f"Size mismatch for {file_path}: expected {expected_size}, got {actual_size}"
            )
    except OSError as e:
        errors.append(f"Cannot stat file {file_path}: {e}")
        return False, errors

    if verify_checksums:
        try:
            actual_sha1, actual_md5 = calculate_checksums(file_path)
            expected_sha1 = str(entry.get("sha1", ""))
            expected_md5 = str(entry.get("md5", ""))

            if actual_sha1 != expected_sha1:
                errors.append(
                    f"SHA1 mismatch for {file_path}: expected {expected_sha1}, got {actual_sha1}"
                )

            if actual_md5 != expected_md5:
                errors.append(
                    f"MD5 mismatch for {file_path}: expected {expected_md5}, got {actual_md5}"
                )
        except OSError as e:
            errors.append(f"Cannot read file for checksum verification {file_path}: {e}")
            return False, errors

    return not errors, errors


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
        actual_mtime = int(path.stat().st_mtime)
        expected_mtime = int(datetime.fromisoformat(expected_date).timestamp())
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

    return not errors, errors


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

    dir_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in data:
        file_path = str(entry.get("path", ""))
        if not file_path:
            continue
        dir_path = str(Path(file_path).parent)
        dir_files.setdefault(dir_path, []).append(entry)

    for dir_path, files in dir_files.items():
        path = Path(dir_path)
        if not path.exists() or not path.is_dir():
            errors.append(f"Directory not found or not accessible: {dir_path}")
            continue

        try:
            newest_file = max(files, key=lambda x: datetime.fromisoformat(str(x["date"])))
            newest_file_path = Path(str(newest_file["path"]))

            if not newest_file_path.exists():
                continue

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
        newest_entry = max(data, key=lambda x: datetime.fromisoformat(str(x["date"])))
        newest_file_path = Path(str(newest_entry["path"]))

        if not newest_file_path.exists():
            errors.append(f"Newest file not found: {newest_file_path}")
            return False, errors

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


def _verify_timestamp_against_newest_json(
    target_path: Path,
    json_files: list[str],
    target_name: str,
    extra_validations: list[tuple[bool, str]] | None = None,
) -> tuple[bool, list[str]]:
    """Verify target path timestamp matches newest JSON file.

    Helper function to verify that a file or directory timestamp matches
    the newest JSON file in the archive.

    Args:
        target_path: Path to the target (file or directory) to verify.
        json_files: List of JSON metadata files to check.
        target_name: Descriptive name for error messages (e.g., "version file").
        extra_validations: Optional list of (condition, error_message) tuples
            for additional validation checks.

    Returns:
        Tuple containing:
            - bool: True if timestamp matches, False otherwise
            - list[str]: List of error messages (empty if no errors)
    """
    errors = []

    if not json_files:
        errors.append(f"No JSON files to compare {target_name} timestamp")
        return False, errors

    if not target_path.exists():
        errors.append(f"{target_name.capitalize()} not found: {target_path}")
        return False, errors

    if extra_validations:
        for condition, error_msg in extra_validations:
            if not condition:
                errors.append(error_msg)
                return False, errors

    try:
        newest_json_file = max(json_files, key=lambda f: Path(f).stat().st_mtime)
        newest_json_path = Path(newest_json_file)

        if not newest_json_path.exists():
            errors.append(f"Newest JSON file not found: {newest_json_file}")
            return False, errors

        target_mtime = int(target_path.stat().st_mtime)
        json_mtime = int(newest_json_path.stat().st_mtime)

        if target_mtime != json_mtime:
            errors.append(
                f"{target_name.capitalize()} timestamp mismatch: "
                f"expected {json_mtime} (from {newest_json_path.name}), "
                f"got {target_mtime}, diff: {abs(target_mtime - json_mtime)}s"
            )
            return False, errors

    except OSError as e:
        errors.append(f"Error verifying {target_name} timestamp: {e}")
        return False, errors

    return True, errors


def verify_version_file_timestamp(
    version_file: str, json_files: list[str]
) -> tuple[bool, list[str]]:
    """Verify version file timestamp matches newest JSON file.

    Checks if the modification timestamp of .version.json matches the
    modification timestamp of the newest JSON metadata file in the archive.

    Args:
        version_file: Path to the version JSON file.
        json_files: List of JSON metadata files to check.

    Returns:
        Tuple containing:
            - bool: True if timestamp matches, False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> success, errors = verify_version_file_timestamp(".version.json", ["a.json"])
        >>> success
        True
    """
    version_path = Path(version_file)
    return _verify_timestamp_against_newest_json(version_path, json_files, "version file")


def verify_archive_directory_timestamp(
    directory: str, json_files: list[str]
) -> tuple[bool, list[str]]:
    """Verify archive directory timestamp matches newest JSON file.

    Checks if the modification timestamp of the archive directory matches the
    modification timestamp of the newest JSON metadata file in the archive.

    Args:
        directory: Path to the archive directory.
        json_files: List of JSON metadata files to check.

    Returns:
        Tuple containing:
            - bool: True if timestamp matches, False otherwise
            - list[str]: List of error messages (empty if no errors)

    Examples:
        >>> success, errors = verify_archive_directory_timestamp("/archive", ["a.json"])
        >>> success
        True
    """
    dir_path = Path(directory).resolve()
    extra_validations = [
        (dir_path.is_dir(), f"Path is not a directory: {directory}"),
    ]
    return _verify_timestamp_against_newest_json(
        dir_path, json_files, "archive directory", extra_validations
    )


def collect_filesystem_files(directory: str) -> tuple[set[str], set[str]]:
    """Collect all files from filesystem in given directory.

    Recursively walks the directory tree and collects all file paths,
    separating JSON files from regular files.

    Args:
        directory: Path to the directory to scan.

    Returns:
        Tuple containing:
            - set[str]: Regular files (non-JSON) found in filesystem
            - set[str]: JSON files found in filesystem

    Examples:
        >>> regular, json_files = collect_filesystem_files("/path/to/archive")
        >>> len(regular) >= 0
        True
    """
    regular_files: set[str] = set()
    json_files: set[str] = set()
    base_path = Path(directory).resolve()

    for root, _, files in os.walk(base_path):
        for file in files:
            file_path = str(Path(root) / file)
            if file.endswith(".json"):
                json_files.add(file_path)
            else:
                regular_files.add(file_path)

    return regular_files, json_files


def collect_expected_files(all_data: list[dict[str, str | int]]) -> set[str]:
    """Collect expected files from JSON metadata.

    Extracts all file paths from JSON metadata entries.

    Args:
        all_data: Combined data from all JSON metadata files.

    Returns:
        Set of absolute file paths that should exist according to metadata.

    Examples:
        >>> data = [{'path': '/archive/photo.jpg', 'size': 1234}]
        >>> files = collect_expected_files(data)
        >>> '/archive/photo.jpg' in files
        True
    """
    return {str(entry["path"]) for entry in all_data if "path" in entry}


def find_extra_files(
    directory: str,
    version_file: str | None,
    json_files: list[str],
    all_data: list[dict[str, str | int]],
) -> tuple[set[str], set[str], set[str]]:
    """Find extra files in filesystem not present in metadata.

    Compares files in the filesystem with files listed in .version.json
    and JSON metadata to identify any extra files that shouldn't be in
    the archive.

    Args:
        directory: Path to the archive directory.
        version_file: Path to .version.json file (if exists).
        json_files: List of JSON metadata files that should exist (from version file).
        all_data: Combined data from all JSON metadata files.

    Returns:
        Tuple containing:
            - set[str]: Extra JSON files not in .version.json
            - set[str]: Extra regular files not in metadata
            - set[str]: Files in metadata but missing from filesystem

    Examples:
        >>> result = find_extra_files("/archive", ".version.json", ["a.json"], data)
        >>> len(result[0]) == 0
        True
    """
    filesystem_regular, filesystem_json = collect_filesystem_files(directory)
    expected_files = collect_expected_files(all_data)

    expected_json = set(json_files)
    if version_file:
        expected_json.add(version_file)

    extra_json_files = filesystem_json - expected_json
    extra_regular_files = filesystem_regular - expected_files
    missing_files = expected_files - filesystem_regular

    return extra_json_files, extra_regular_files, missing_files


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

    return not errors, errors


def find_zero_byte_files(all_data: list[dict[str, str | int]]) -> list[str]:
    """Find files with zero bytes in metadata.

    Args:
        all_data: Combined data from all JSON metadata files.

    Returns:
        List of file paths with zero bytes.

    Examples:
        >>> data = [{'path': '/archive/empty.txt', 'size': 0}]
        >>> zero_files = find_zero_byte_files(data)
        >>> len(zero_files)
        1
    """
    return [str(entry["path"]) for entry in all_data if entry.get("size") == 0 and "path" in entry]


def find_duplicate_checksums(
    all_data: list[dict[str, str | int]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Find duplicate SHA1 and MD5 checksums in metadata.

    Args:
        all_data: Combined data from all JSON metadata files.

    Returns:
        Tuple containing:
            - dict: SHA1 checksums that appear more than once, mapping to list of file paths
            - dict: MD5 checksums that appear more than once, mapping to list of file paths

    Examples:
        >>> data = [
        ...     {'path': '/a.jpg', 'sha1': 'abc123', 'md5': 'def456'},
        ...     {'path': '/b.jpg', 'sha1': 'abc123', 'md5': 'def456'}
        ... ]
        >>> sha1_dups, md5_dups = find_duplicate_checksums(data)
        >>> len(sha1_dups)
        1
    """
    sha1_map: dict[str, list[str]] = {}
    md5_map: dict[str, list[str]] = {}

    for entry in all_data:
        path = str(entry.get("path", ""))
        sha1 = str(entry.get("sha1", ""))
        md5 = str(entry.get("md5", ""))

        if path and sha1:
            sha1_map.setdefault(sha1, []).append(path)
        if path and md5:
            md5_map.setdefault(md5, []).append(path)

    sha1_duplicates = {k: v for k, v in sha1_map.items() if len(v) > 1}
    md5_duplicates = {k: v for k, v in md5_map.items() if len(v) > 1}

    return sha1_duplicates, md5_duplicates


def validate_date_format(date_str: str) -> tuple[bool, str | None]:
    """Validate that date string is in proper ISO 8601 format with colon in timezone.

    Args:
        date_str: Date string to validate.

    Returns:
        Tuple containing:
            - bool: True if date format is valid, False otherwise
            - str | None: Error message if invalid, None if valid

    Examples:
        >>> validate_date_format("2024-01-01T12:00:00+02:00")
        (True, None)
        >>> validate_date_format("2024-01-01T12:00:00+0200")
        (False, "Timezone format should use colon (e.g., '+02:00' not '+0200')")
    """
    # Check if date can be parsed as ISO 8601
    try:
        datetime.fromisoformat(str(date_str))
    except (ValueError, TypeError) as e:
        return False, f"Invalid ISO 8601 format: {e}"

    if "T" not in str(date_str):
        return (
            False,
            "Date format must use 'T' separator between date and time",
        )

    timezone_pattern = r"([+-]\d{2}:\d{2}|Z)$"
    if not re.search(timezone_pattern, str(date_str)):
        if re.search(r"[+-]\d{4}$", str(date_str)):
            return False, "Timezone format should use colon (e.g., '+02:00' not '+0200')"
        return False, "Date must include timezone with colon format (e.g., '+02:00') or 'Z'"

    return True, None


def find_invalid_dates(all_data: list[dict[str, str | int]]) -> dict[str, list[tuple[str, str]]]:
    """Find files with invalid date formats in metadata.

    Args:
        all_data: Combined data from all JSON metadata files.

    Returns:
        Dictionary mapping file paths to list of (date_value, error_message) tuples.

    Examples:
        >>> data = [{'path': '/a.jpg', 'date': '2024-01-01T12:00:00+0200'}]
        >>> invalid = find_invalid_dates(data)
        >>> len(invalid) > 0
        True
    """
    invalid_dates: dict[str, list[tuple[str, str]]] = {}

    for entry in all_data:
        path = str(entry.get("path", ""))
        date_str = entry.get("date")

        if not path or not date_str:
            continue

        is_valid, error_msg = validate_date_format(str(date_str))
        if not is_valid and error_msg:
            invalid_dates.setdefault(path, []).append((str(date_str), error_msg))

    return invalid_dates


def validate_version_file_dates(version_file: str) -> list[tuple[str, str, str]]:
    """Validate date formats in version file.

    Args:
        version_file: Path to .version.json file.

    Returns:
        List of tuples (field_name, date_value, error_message) for invalid dates.

    Examples:
        >>> errors = validate_version_file_dates(".version.json")
        >>> len(errors) == 0
        True
    """
    errors: list[tuple[str, str, str]] = []

    try:
        version_data = load_version_json(version_file)
    except SystemExit:
        return errors

    # Check last_modified field
    if "last_modified" in version_data:
        date_str = str(version_data["last_modified"])
        is_valid, error_msg = validate_date_format(date_str)
        if not is_valid and error_msg:
            errors.append(("last_modified", date_str, error_msg))

    # Check last_verified field
    if "last_verified" in version_data:
        date_str = str(version_data["last_verified"])
        is_valid, error_msg = validate_date_format(date_str)
        if not is_valid and error_msg:
            errors.append(("last_verified", date_str, error_msg))

    return errors


def _get_json_files_list(directory: str, version_file: str | None) -> tuple[list[str], int]:
    """Get list of JSON files to process from version file or directory scan.

    Args:
        directory: Path to the archive directory.
        version_file: Path to .version.json file if exists.

    Returns:
        Tuple containing:
            - list[str]: List of JSON file paths to process
            - int: Number of errors encountered (0 or 1)
    """
    json_files: list[str] = []
    if version_file:
        try:
            version_data = load_version_json(version_file)
            if "files" in version_data:
                version_dir = Path(directory).resolve()
                json_files = [str(version_dir / filename) for filename in version_data["files"]]
            else:
                print("Warning: Version file has no 'files' field", file=sys.stderr)
        except SystemExit as e:
            print(f"Error loading version file: {e}", file=sys.stderr)
            return [], 1
    else:
        # No version file, scan for JSON files
        try:
            json_files = find_json_files(directory)
        except SystemExit as e:
            print(f"Error: {e}", file=sys.stderr)
            return [], 1

    return json_files, 0


def _verify_timestamps_for_json_file(
    json_file: str, data: list[dict[str, str | int]], args: argparse.Namespace
) -> tuple[int, int]:
    """Verify timestamps for a single JSON file and its contents.

    Helper function that verifies file timestamps, directory timestamps,
    and JSON file timestamp for a single JSON file.

    Args:
        json_file: Path to the JSON file.
        data: File metadata entries from the JSON file.
        args: Command-line arguments with tolerance setting.

    Returns:
        Tuple containing (number of directories checked, number of errors found).
    """
    errors_count = 0

    # Verify file timestamps
    print("  Verifying file timestamps...")
    for entry in data:
        success, errors = verify_timestamps(entry, args.tolerance)
        if not success:
            errors_count += len(errors)
            for error in errors:
                print(f"  Error: {error}", file=sys.stderr)

    # Verify directory timestamps
    print("  Verifying directory timestamps...")
    dir_count, errors = verify_directory_timestamps(data)
    if errors:
        errors_count += len(errors)
        for error in errors:
            print(f"  Error: {error}", file=sys.stderr)
    else:
        print(f"  Verified {dir_count} directories")

    # Verify JSON file timestamp
    print("  Verifying JSON file timestamp...")
    success, errors = verify_json_file_timestamp(json_file, data)
    if not success:
        errors_count += len(errors)
        for error in errors:
            print(f"  Error: {error}", file=sys.stderr)
    else:
        print("  JSON file timestamp OK")

    return dir_count, errors_count


def _verify_version_file_and_timestamps(
    version_file: str | None,
    json_files: list[str],
    all_data: list[dict[str, str | int]],
    check_timestamps: bool,
    directory: str,
) -> int:
    """Verify version file timestamp and integrity.

    Args:
        version_file: Path to .version.json file if exists.
        json_files: List of JSON metadata files.
        all_data: Combined data from all JSON files.
        check_timestamps: Whether to check timestamps.
        directory: Path to the archive directory.

    Returns:
        Number of errors found.
    """
    total_errors = 0

    if check_timestamps:
        if not version_file:
            print("\nError: Version file (.version.json) not found", file=sys.stderr)
            print("  Timestamp verification requires .version.json file", file=sys.stderr)
            total_errors += 1
        else:
            print("\nVerifying version file timestamp...")
            success, errors = verify_version_file_timestamp(version_file, json_files)
            if not success:
                total_errors += len(errors)
                for error in errors:
                    print(f"  Error: {error}", file=sys.stderr)
            else:
                print("  Version file timestamp OK")

        print("\nVerifying archive directory timestamp...")
        success, errors = verify_archive_directory_timestamp(directory, json_files)
        if not success:
            total_errors += len(errors)
            for error in errors:
                print(f"  Error: {error}", file=sys.stderr)
        else:
            print("  Archive directory timestamp OK")

    if version_file:
        print(f"\nVerifying version file {Path(version_file).name}...")
        success, errors = verify_version_file(version_file, json_files, all_data)
        if not success:
            total_errors += len(errors)
            for error in errors:
                print(f"  Error: {error}", file=sys.stderr)
        else:
            print("  Version file verified successfully")

    return total_errors


def _verify_extra_files_check(
    directory: str,
    version_file: str | None,
    json_files: list[str],
    all_data: list[dict[str, str | int]],
) -> int:
    """Check for extra files in filesystem not present in metadata.

    Args:
        directory: Path to the archive directory.
        version_file: Path to .version.json file if exists.
        json_files: List of JSON metadata files.
        all_data: Combined data from all JSON files.

    Returns:
        Number of errors found.
    """
    total_errors = 0

    if not version_file:
        print("\nError: Version file (.version.json) not found", file=sys.stderr)
        print("  Extra files check requires .version.json file", file=sys.stderr)
        return 1

    print("\nChecking for extra files in archive...")
    extra_json, extra_regular, missing = find_extra_files(
        directory, version_file, json_files, all_data
    )

    if extra_json:
        print(f"  Found {len(extra_json)} extra JSON file(s) not in .version.json:")
        for file_path in sorted(extra_json):
            print(f"    - {file_path}", file=sys.stderr)
            total_errors += 1

    if extra_regular:
        print(f"  Found {len(extra_regular)} extra file(s) not in metadata:")
        for file_path in sorted(extra_regular):
            print(f"    - {file_path}", file=sys.stderr)
            total_errors += 1

    if missing:
        print(f"  Found {len(missing)} missing file(s) from filesystem:")
        for file_path in sorted(missing):
            print(f"    - {file_path}", file=sys.stderr)
            total_errors += 1

    if not extra_json and not extra_regular and not missing:
        print("  No extra or missing files found - archive is clean")

    return total_errors


def _verify_date_formats(all_data: list[dict[str, str | int]], version_file: str | None) -> int:
    """Verify date formats in metadata and version file.

    Checks that all dates in JSON metadata and .version.json follow ISO 8601
    format with proper timezone separator (colon).

    Args:
        all_data: Combined metadata from all JSON files.
        version_file: Path to .version.json file if present, None otherwise.

    Returns:
        int: Number of errors found (invalid dates).
    """
    total_errors = 0

    print("\nChecking date formats in metadata...")
    invalid_dates = find_invalid_dates(all_data)
    if invalid_dates:
        print(f"  Found {len(invalid_dates)} file(s) with invalid date format:")
        for path, date_errors in sorted(invalid_dates.items()):
            for date_val, error_msg in date_errors:
                print(f"    {path}:", file=sys.stderr)
                print(f"      Date: {date_val}", file=sys.stderr)
                print(f"      Error: {error_msg}", file=sys.stderr)
                total_errors += 1
    else:
        print("  All date formats are valid")

    if version_file:
        print("\nChecking date formats in version file...")
        version_date_errors = validate_version_file_dates(version_file)
        if version_date_errors:
            print(f"  Found {len(version_date_errors)} invalid date(s) in version file:")
            for field_name, date_val, error_msg in version_date_errors:
                print(f"    Field '{field_name}':", file=sys.stderr)
                print(f"      Date: {date_val}", file=sys.stderr)
                print(f"      Error: {error_msg}", file=sys.stderr)
                total_errors += 1
        else:
            print("  All version file date formats are valid")

    return total_errors


def verify_permissions(
    directory: str,
    json_files: list[str],
    version_file: str | None,
    all_data: list[dict[str, str | int]],
    expected_owner: str,
    expected_group: str,
) -> dict[str, list[tuple[str, str]]]:
    """Verify file and directory permissions and ownership.

    Checks that:
    - All files (.version.json, *.json, archive files) have 644 permissions
    - All directories have 755 permissions
    - All files and directories have correct owner and group

    Args:
        directory: Root directory of the archive.
        json_files: List of JSON metadata file paths.
        version_file: Path to .version.json file if present, None otherwise.
        all_data: Combined metadata from all JSON files.
        expected_owner: Expected owner username.
        expected_group: Expected group name.

    Returns:
        dict: Mapping of file/directory paths to list of tuples (issue_type, description).
              Empty dict if all permissions are correct.

    Examples:
        >>> errors = verify_permissions('/archive', ['a.json'], None, data, 'storage', 'storage')
        >>> errors['/archive/file.jpg']
        [('permissions', 'Expected 644, got 755'), ('owner', 'Expected storage, got user')]
    """
    errors: dict[str, list[tuple[str, str]]] = {}
    expected_file_perms = 0o644
    expected_dir_perms = 0o755

    def check_path(path_str: str, is_directory: bool) -> None:
        """Check permissions and ownership for a single path."""
        try:
            path = Path(path_str)
            if not path.exists():
                return

            file_stat = path.stat()
            current_perms = stat.S_IMODE(file_stat.st_mode)
            expected_perms = expected_dir_perms if is_directory else expected_file_perms

            path_errors: list[tuple[str, str]] = []

            if current_perms != expected_perms:
                path_errors.append(
                    (
                        "permissions",
                        f"Expected {oct(expected_perms)}, got {oct(current_perms)}",
                    )
                )

            try:
                current_owner = pwd.getpwuid(file_stat.st_uid).pw_name
                if current_owner != expected_owner:
                    path_errors.append(("owner", f"Expected {expected_owner}, got {current_owner}"))
            except KeyError:
                path_errors.append(("owner", f"Unknown owner UID: {file_stat.st_uid}"))

            try:
                current_group = grp.getgrgid(file_stat.st_gid).gr_name
                if current_group != expected_group:
                    path_errors.append(("group", f"Expected {expected_group}, got {current_group}"))
            except KeyError:
                path_errors.append(("group", f"Unknown group GID: {file_stat.st_gid}"))

            if path_errors:
                errors[str(path)] = path_errors

        except OSError as e:
            errors[str(path_str)] = [("access", f"Cannot access: {e}")]

    if version_file:
        check_path(version_file, is_directory=False)

    for json_file in json_files:
        check_path(json_file, is_directory=False)

    checked_dirs: set[str] = set()
    for entry in all_data:
        file_path = entry.get("path")
        if not file_path:
            continue

        check_path(str(file_path), is_directory=False)

        path = Path(str(file_path))
        for parent in path.parents:
            parent_str = str(parent)
            if parent_str not in checked_dirs and parent_str.startswith(directory):
                check_path(parent_str, is_directory=True)
                checked_dirs.add(parent_str)

    check_path(directory, is_directory=True)

    return errors


def _verify_permissions_check(
    directory: str,
    json_files: list[str],
    version_file: str | None,
    all_data: list[dict[str, str | int]],
    expected_owner: str,
    expected_group: str,
) -> int:
    """Verify permissions and ownership of files and directories.

    Helper function for run() that checks permissions and ownership.

    Args:
        directory: Root directory of the archive.
        json_files: List of JSON metadata file paths.
        version_file: Path to .version.json file if present, None otherwise.
        all_data: Combined metadata from all JSON files.
        expected_owner: Expected owner username.
        expected_group: Expected group name.

    Returns:
        int: Number of errors found (files/dirs with incorrect permissions/ownership).
    """
    total_errors = 0

    print("\nChecking file and directory permissions...")
    permission_errors = verify_permissions(
        directory, json_files, version_file, all_data, expected_owner, expected_group
    )

    if permission_errors:
        print(f"  Found {len(permission_errors)} file(s)/directory(ies) with incorrect settings:")
        for path, issues in sorted(permission_errors.items()):
            print(f"    {path}:", file=sys.stderr)
            for issue_type, description in issues:
                print(f"      {issue_type}: {description}", file=sys.stderr)
                total_errors += 1
    else:
        print("  All permissions and ownership are correct")

    return total_errors


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
        help="Verify SHA1 and MD5 checksums (time-consuming)",
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
    parser.add_argument(
        "-e",
        "--check-extra-files",
        action="store_true",
        help="Check for extra files in filesystem not present in metadata",
    )
    parser.add_argument(
        "-p",
        "--check-permissions",
        action="store_true",
        help="Verify file permissions (644) and directory permissions (755)",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default="storage",
        help="Expected owner username for all files and directories (default: storage)",
    )
    parser.add_argument(
        "--group",
        type=str,
        default="storage",
        help="Expected group name for all files and directories (default: storage)",
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
    4. Optionally verifies SHA1 and MD5 checksums (with all flag, time-consuming)
    5. Optionally verifies directory timestamps (with check_timestamps flag)
    6. Optionally verifies JSON file timestamps (with check_timestamps flag)
    7. Optionally verifies archive directory timestamp matches newest JSON file
       (with check_timestamps flag)
    8. If .version.json found, verifies version integrity
    9. Optionally checks for extra files in filesystem (with check_extra_files flag)
    10. Checks for zero-byte files in metadata
    11. Checks for duplicate SHA1 and MD5 checksums
    12. Validates date formats in metadata (ISO 8601 with colon in timezone)
    13. Validates date formats in .version.json file
    14. Optionally verifies file/directory permissions and ownership (with check_permissions flag)

    Args:
        args: Parsed command-line arguments with fields:
            - directory: Path to archive directory containing JSON files
            - all: Whether to verify SHA1 and MD5 checksums (time-consuming)
            - check_timestamps: Whether to verify file and directory timestamps
            - tolerance: Timestamp tolerance in seconds
            - check_extra_files: Whether to check for extra files not in metadata
            - check_permissions: Whether to verify permissions and ownership
            - owner: Expected owner username (default: 'storage')
            - group: Expected group name (default: 'storage')

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
    directory_path = Path(args.directory)
    if not directory_path.is_dir() or not os.access(args.directory, os.R_OK):
        raise SystemExit(
            f"Error: The directory '{args.directory}' does not exist or is not readable"
        )

    print(f"Scanning directory: {args.directory}")
    version_file = find_version_file(args.directory)
    if version_file:
        print(f"Found version file: {Path(version_file).name}")

    json_files, error_count = _get_json_files_list(args.directory, version_file)
    if error_count:
        return 1

    print(f"Found {len(json_files)} JSON metadata file(s)")

    if args.all:
        print("WARNING: Full checksum verification enabled (this may take a while)")
    if args.check_timestamps:
        print("Timestamp verification enabled")

    total_files = 0
    total_errors = 0
    all_data: list[dict[str, str | int]] = []

    for json_file in json_files:
        print(f"\nVerifying {Path(json_file).name}...")

        try:
            data = load_json(json_file)
            data = normalize_paths(data, args.directory)
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
                _, timestamp_errors = _verify_timestamps_for_json_file(json_file, data, args)
                errors_in_file += timestamp_errors
                total_errors += timestamp_errors

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

    total_errors += _verify_version_file_and_timestamps(
        version_file, json_files, all_data, args.check_timestamps, args.directory
    )

    if args.check_extra_files:
        total_errors += _verify_extra_files_check(
            args.directory, version_file, json_files, all_data
        )

    print("\nChecking for zero-byte files...")
    zero_byte_files = find_zero_byte_files(all_data)
    if zero_byte_files:
        print(f"  Found {len(zero_byte_files)} zero-byte file(s):")
        for file_path in sorted(zero_byte_files):
            print(f"    - {file_path}", file=sys.stderr)
            total_errors += 1
    else:
        print("  No zero-byte files found")

    print("\nChecking for duplicate checksums...")
    sha1_duplicates, md5_duplicates = find_duplicate_checksums(all_data)

    if sha1_duplicates:
        print(f"  Found {len(sha1_duplicates)} duplicate SHA1 checksum(s):")
        for sha1, paths in sorted(sha1_duplicates.items()):
            print(f"    SHA1 {sha1} appears in {len(paths)} file(s):", file=sys.stderr)
            for path in sorted(paths):
                print(f"      - {path}", file=sys.stderr)
            total_errors += len(paths) - 1
    else:
        print("  No duplicate SHA1 checksums found")

    if md5_duplicates:
        print(f"  Found {len(md5_duplicates)} duplicate MD5 checksum(s):")
        for md5, paths in sorted(md5_duplicates.items()):
            print(f"    MD5 {md5} appears in {len(paths)} file(s):", file=sys.stderr)
            for path in sorted(paths):
                print(f"      - {path}", file=sys.stderr)
    else:
        print("  No duplicate MD5 checksums found")

    total_errors += _verify_date_formats(all_data, version_file)

    if args.check_permissions:
        total_errors += _verify_permissions_check(
            args.directory, json_files, version_file, all_data, args.owner, args.group
        )

    print(f"\n{'=' * 60}")
    print("Verification complete:")
    print(f"  Total files checked: {total_files}")
    print(f"  Total errors found: {total_errors}")

    if total_errors == 0:
        print("  Result: PASS - All verifications passed")
        return os.EX_OK

    print(f"  Result: FAIL - Verification failed with {total_errors} error(s)", file=sys.stderr)
    return 1
