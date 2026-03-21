"""Common utilities shared across photos_manager modules.

This module provides shared functionality to eliminate code duplication
across all photos_manager modules.
"""

import concurrent.futures
import grp
import hashlib
import json
import os
import pwd
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

# Constants
CHUNK_SIZE = 65536  # 64KB chunks for file operations

# Timestamp display formats
TS_FMT = "%Y-%m-%d %H:%M:%S"
TIME_FMT = "%H:%M:%S"


def format_datetime_change(old_dt: datetime, new_dt: datetime) -> str:
    """Format a datetime pair as ``old → new (delta: +Xs)``.

    Uses the full date+time format when the calendar dates differ; uses
    time-only otherwise.

    Args:
        old_dt: Original datetime.
        new_dt: Target datetime.

    Returns:
        Formatted string, e.g. ``"10:00:00 → 11:00:00 (delta: +3600s)"``.

    Examples:
        >>> from datetime import datetime
        >>> old = datetime(2023, 5, 14, 10, 0, 0)
        >>> new = datetime(2023, 5, 14, 11, 0, 0)
        >>> format_datetime_change(old, new)
        '10:00:00 → 11:00:00 (delta: +3600s)'
    """
    if old_dt.date() != new_dt.date():
        old_str = old_dt.strftime(TS_FMT)
        new_str = new_dt.strftime(TS_FMT)
    else:
        old_str = old_dt.strftime(TIME_FMT)
        new_str = new_dt.strftime(TIME_FMT)
    delta_s = int((new_dt - old_dt).total_seconds())
    delta_str = f"+{delta_s}s" if delta_s >= 0 else f"{delta_s}s"
    return f"{old_str} → {new_str} (delta: {delta_str})"


def format_timestamp_change(
    name: str,
    tag: str,
    old_dt: datetime,
    new_dt: datetime,
    *,
    name_width: int = 0,
    tag_width: int = 6,
    extra: str = "",
) -> str:
    """Format one output line describing a timestamp change.

    Produces an aligned line with full date when the calendar date differs,
    time-only otherwise:
    ``name  [TAG]  HH:MM:SS → HH:MM:SS (delta: +Xs[extra])``

    Args:
        name: Display name (file path, directory with trailing ``/``, etc.).
        tag: Type tag, e.g. ``[FILE]``, ``[DIR]``, ``[EXIF+GPS]``.
        old_dt: Original datetime.
        new_dt: Target datetime.
        name_width: Left-justify name column to this width (0 = no padding).
        tag_width: Left-justify tag column to this width.
        extra: Additional text appended inside the trailing parentheses
            after the delta, e.g. ``", src: path"``.

    Returns:
        Formatted change line string.

    Examples:
        >>> from datetime import datetime
        >>> old = datetime(2023, 5, 14, 10, 0, 0)
        >>> new = datetime(2023, 5, 14, 11, 0, 0)
        >>> "delta: +3600s" in format_timestamp_change("f.jpg", "[FILE]", old, new)
        True
    """
    if old_dt.date() != new_dt.date():
        old_str = old_dt.strftime(TS_FMT)
        new_str = new_dt.strftime(TS_FMT)
    else:
        old_str = old_dt.strftime(TIME_FMT)
        new_str = new_dt.strftime(TIME_FMT)
    delta_s = int((new_dt - old_dt).total_seconds())
    delta_str = f"+{delta_s}s" if delta_s >= 0 else f"{delta_s}s"
    name_col = f"{name:<{name_width}}" if name_width else name
    return f"{name_col}  {tag:<{tag_width}}  {old_str} → {new_str} (delta: {delta_str}{extra})"


_METADATA_KEY_ORDER = ["path", "sha1", "md5", "date", "size"]
_METADATA_KEYS = set(_METADATA_KEY_ORDER)


def load_metadata_json(file_path: str) -> list[dict[str, str | int]]:
    """Load and validate a JSON metadata file.

    Reads a file produced by ``photos index`` and verifies that every entry
    is a dict with the required keys: path, sha1, md5, date, size.

    Args:
        file_path: Path to the JSON metadata file to load.

    Returns:
        List of file metadata dictionaries, each with keys path, sha1, md5,
        date, size.

    Raises:
        SystemExit: If the file doesn't exist, contains invalid JSON, is not
            an array, any entry is not a dict, or any entry is missing required
            keys.
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

    for entry in data:
        if not isinstance(entry, dict):
            raise SystemExit(f"Error: '{file_path}' must contain an array of objects")
        missing = _METADATA_KEYS - entry.keys()
        if missing:
            keys_str = ", ".join(sorted(missing))
            raise SystemExit(f"Error: Entry in '{file_path}' is missing required keys: {keys_str}")

    return data


def write_metadata_json(file_path: str, data: list[dict[str, str | int]]) -> None:
    """Write metadata entries to a JSON file.

    Normalises key order to (path, sha1, md5, date, size), formats with
    indent=4 and ensure_ascii=False, appends a trailing newline, and sets
    file permissions to 0o644.

    Args:
        file_path: Destination path for the JSON file.
        data: List of file metadata dictionaries.

    Raises:
        SystemExit: If the file cannot be written.
    """
    ordered = [{key: item[key] for key in _METADATA_KEY_ORDER if key in item} for item in data]
    try:
        output_path = Path(file_path)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(ordered, f, ensure_ascii=False, indent=4)
            f.write("\n")
        output_path.chmod(0o644)
    except OSError as e:
        raise SystemExit(f"Error: Could not write to '{file_path}': {e}") from e


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
    where you want to continue on errors (index, find).

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


def format_count(n: int) -> str:
    """Format integer with space as thousands separator.

    Args:
        n: Integer to format.

    Returns:
        String with spaces as thousands separators, e.g. ``280 924``.

    Examples:
        >>> format_count(280924)
        '280 924'
        >>> format_count(100)
        '100'
    """
    return f"{n:,}".replace(",", " ")


def human_size(size_bytes: int) -> str:
    """Format bytes as a human-readable size string.

    Args:
        size_bytes: Size in bytes to format.

    Returns:
        Human-readable size string, e.g. ``1.5 GB``, ``234.0 MB``, ``512 B``.

    Examples:
        >>> human_size(0)
        '0 B'
        >>> human_size(1500000)
        '1.4 MB'
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} kB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    if size_bytes < 1024**4:
        return f"{size_bytes / 1024**3:.1f} GB"
    return f"{size_bytes / 1024**4:.1f} TB"


def validate_directory(directory: str, check_readable: bool = False) -> Path:
    """Validate that the given path is an existing directory.

    Args:
        directory: Path to validate.
        check_readable: If True, also verify the directory is readable.

    Returns:
        Validated Path object.

    Raises:
        SystemExit: If path doesn't exist, isn't a directory, or isn't readable.
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        raise SystemExit(f"Error: Directory '{directory}' does not exist")

    if not dir_path.is_dir():
        raise SystemExit(f"Error: '{directory}' is not a directory")

    if check_readable and not os.access(directory, os.R_OK):
        raise SystemExit(f"Error: Directory '{directory}' is not readable")

    return dir_path


def load_version_json(file_path: str) -> dict[str, Any]:
    """Load version JSON file, raising SystemExit on any error.

    Args:
        file_path: Path to the .version.json file.

    Returns:
        Parsed dict with version metadata.

    Raises:
        SystemExit: If the file does not exist or contains invalid JSON.

    Examples:
        >>> data = load_version_json(".version.json")
        >>> "version" in data
        True
    """
    try:
        with Path(file_path).open(encoding="utf-8") as f:
            return cast("dict[str, Any]", json.load(f))
    except FileNotFoundError as exc:
        raise SystemExit(f"Error: Version file '{file_path}' does not exist") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Error: Version file '{file_path}' contains invalid format") from exc


def load_version_json_lenient(file_path: str) -> dict[str, Any] | None:
    """Load version JSON file, returning None on any error.

    Args:
        file_path: Path to the .version.json file.

    Returns:
        Parsed dict with version metadata, or None if file cannot be loaded
        or does not contain a JSON object.

    Examples:
        >>> load_version_json_lenient("/nonexistent/.version.json") is None
        True
    """
    try:
        with Path(file_path).open(encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def find_version_file(directory: str) -> str | None:
    """Find version JSON file in directory.

    Searches for .version.json file in the specified directory (non-recursive).

    Args:
        directory: Path to the directory to search.

    Returns:
        Path to version file if found, None otherwise.

    Examples:
        >>> find_version_file("/path/to/archive")
        '/path/to/archive/.version.json'
    """
    base_path = Path(directory).resolve()
    version_path = base_path / ".version.json"
    if version_path.exists():
        return str(version_path)
    return None


def resolve_owner_name(uid: int) -> str | None:
    """Resolve a UID to a username.

    Args:
        uid: User ID to resolve.

    Returns:
        Username string, or None if the UID has no associated user.
    """
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def resolve_group_name(gid: int) -> str | None:
    """Resolve a GID to a group name.

    Args:
        gid: Group ID to resolve.

    Returns:
        Group name string, or None if the GID has no associated group.
    """
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return None


def _find_metadata_json_files(directory: str) -> list[Path]:
    """Find JSON metadata files in directory, excluding *version.json.

    Args:
        directory: Root directory to search

    Returns:
        List of Path objects for matching JSON files

    Raises:
        SystemExit: If directory is invalid or no JSON files found
    """
    dir_path = validate_directory(directory)

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


def scan_files(
    directory: str,
    *,
    time_zone: str | None = None,
    resolve_paths: bool = False,
) -> list[dict[str, str | int]]:
    """Scan directory recursively and collect file metadata with checksums.

    Implements a three-phase pipeline: stat collection (sequential), checksum
    computation (parallel, hashlib releases the GIL), and result assembly.

    Args:
        directory: Path to the directory to scan. Must already be validated.
        time_zone: IANA timezone name for timestamps (e.g. ``'Europe/Warsaw'``).
            If None, uses the local system timezone via ``.astimezone()``.
        resolve_paths: If True, resolve symlinks and relative components in
            file paths via ``Path.resolve()``. If False, use the path as-is.

    Returns:
        List of file metadata dicts with keys: path, sha1, md5, date, size.
        Files that cannot be stat'd or hashed are silently skipped with a
        warning printed to stderr.

    Examples:
        >>> files = scan_files("/path/to/photos")
        >>> files[0]["sha1"]  # doctest: +SKIP
        'a1b2c3...'
    """
    tz: ZoneInfo | None = ZoneInfo(time_zone) if time_zone else None
    dir_path = Path(directory)

    # Phase 1: collect paths and stat info (sequential)
    file_entries: list[tuple[str, float, int]] = []
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            stat_result = file_path.stat()
            resolved = str(file_path.resolve()) if resolve_paths else str(file_path)
            file_entries.append((resolved, stat_result.st_mtime, stat_result.st_size))
        except OSError as e:
            print(f"Warning: Could not process {file_path}: {e}", file=sys.stderr)

    # Phase 2: compute checksums in parallel (hashlib releases the GIL)
    workers = os.cpu_count() or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        checksums = list(executor.map(calculate_checksums, [p for p, _, _ in file_entries]))

    # Phase 3: assemble results (order preserved by executor.map)
    files: list[dict[str, str | int]] = []
    for (path, mtime, size), (sha1, md5) in zip(file_entries, checksums, strict=True):
        if sha1 is None or md5 is None:
            continue
        if tz is not None:
            date = datetime.fromtimestamp(mtime, tz).isoformat()
        else:
            date = datetime.fromtimestamp(mtime).astimezone().isoformat()
        files.append({"path": path, "sha1": sha1, "md5": md5, "date": date, "size": size})

    return files
