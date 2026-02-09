"""Common utilities shared across photos_manager modules.

This module provides shared functionality to eliminate code duplication
across index, verify, setmtime, mkversion, and dedup modules.
"""

import hashlib
import json
import sys
from pathlib import Path

# Constants
CHUNK_SIZE = 65536  # 64KB chunks for file operations


def load_json(file_path: str) -> list[dict[str, str | int]]:
    """Load and parse JSON metadata file.

    Args:
        file_path: Path to the JSON file to load

    Returns:
        List of file metadata dictionaries

    Raises:
        SystemExit: If file doesn't exist or JSON is invalid
    """
    path = Path(file_path)

    if not path.exists():
        raise SystemExit(f"Error: File '{file_path}' does not exist")

    if not path.is_file():
        raise SystemExit(f"Error: '{file_path}' is not a file")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Error: Invalid JSON in '{file_path}': {e}") from e
    except OSError as e:
        raise SystemExit(f"Error: Cannot read '{file_path}': {e}") from e

    if not isinstance(data, list):
        raise SystemExit(f"Error: '{file_path}' does not contain a JSON array")

    return data


def _hash_file(file_path: str) -> tuple[str, str]:
    """Read a file in chunks and compute SHA1 and MD5 digests.

    Args:
        file_path: Path to the file to hash

    Returns:
        Tuple of (sha1_hex, md5_hex)

    Raises:
        OSError: If file cannot be read
    """
    sha1_hash = hashlib.sha1(usedforsecurity=False)
    md5_hash = hashlib.md5(usedforsecurity=False)

    with Path(file_path).open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            sha1_hash.update(chunk)
            md5_hash.update(chunk)

    return sha1_hash.hexdigest(), md5_hash.hexdigest()


def calculate_checksums(file_path: str) -> tuple[str | None, str | None]:
    """Calculate SHA1 and MD5 checksums for a file (lenient).

    Returns (None, None) on error with warning. Use for batch processing
    where you want to continue on errors (index, dedup).

    Args:
        file_path: Path to the file to hash

    Returns:
        Tuple of (sha1_hex, md5_hex), or (None, None) if error occurs
    """
    try:
        return _hash_file(file_path)
    except OSError as e:
        print(f"Warning: Cannot read '{file_path}': {e}", file=sys.stderr)
        return None, None


def calculate_checksums_strict(file_path: str) -> tuple[str, str]:
    """Calculate SHA1 and MD5 checksums for a file (strict).

    Raises OSError on error. Use for validation where failures must
    be reported (verify).

    Args:
        file_path: Path to the file to hash

    Returns:
        Tuple of (sha1_hex, md5_hex)

    Raises:
        OSError: If file cannot be read
    """
    return _hash_file(file_path)


def _validate_directory(directory: str) -> Path:
    """Validate that the given path is an existing directory.

    Args:
        directory: Path to validate

    Returns:
        Validated Path object

    Raises:
        SystemExit: If path doesn't exist or isn't a directory
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        raise SystemExit(f"Error: Directory '{directory}' does not exist")

    if not dir_path.is_dir():
        raise SystemExit(f"Error: '{directory}' is not a directory")

    return dir_path


def _find_metadata_json_files(directory: str) -> list[Path]:
    """Find JSON metadata files in directory, excluding *version.json.

    Args:
        directory: Root directory to search

    Returns:
        List of Path objects for matching JSON files

    Raises:
        SystemExit: If directory is invalid or no JSON files found
    """
    dir_path = _validate_directory(directory)

    json_files = [
        json_file
        for json_file in dir_path.rglob("*.json")
        if not json_file.name.endswith("version.json")
    ]

    if not json_files:
        raise SystemExit(f"Error: No JSON files found in '{directory}'")

    return json_files


def find_json_files(directory: str) -> list[str]:
    """Find JSON metadata files in directory tree (excludes *version.json).

    Returns list of paths sorted by filename.

    Args:
        directory: Root directory to search

    Returns:
        Sorted list of JSON file paths

    Raises:
        SystemExit: If directory doesn't exist or no JSON files found
    """
    return sorted(str(f) for f in _find_metadata_json_files(directory))


def find_json_files_with_mtime(directory: str) -> list[tuple[float, str]]:
    """Find JSON files with modification times (excludes *version.json).

    Returns list of (mtime, path) tuples sorted by mtime descending.

    Args:
        directory: Root directory to search

    Returns:
        List of (mtime, path) tuples, sorted newest first

    Raises:
        SystemExit: If directory doesn't exist or no JSON files found
    """
    json_files = [(f.stat().st_mtime, str(f)) for f in _find_metadata_json_files(directory)]
    return sorted(json_files, key=lambda x: x[0], reverse=True)
