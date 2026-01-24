"""sync - Generate minimal synchronization commands for photo archives.

This script compares source and destination archives (both with .version.json
and JSON metadata) and produces an optimized list of operations to synchronize
them. The tool prioritizes minimal operations (moves over copy+delete) and
ensures timestamp synchronization.

Key features:
- File matching by content (SHA1, MD5, size) to detect moves/renames
- Minimal operations: prioritize moves over copy+delete
- Timestamp handling: exact matching required for files and directories
- Safety first: dry-run by default, extensive validation, clear warnings

Usage:
    photos sync /source/archive /dest/archive
    photos sync /source /dest --execute
    photos sync /source /dest --output sync.sh
    photos sync /source /dest --no-delete --execute
"""

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from photos_manager.verify import (
    find_json_files,
    find_version_file,
    load_json,
)

# Type alias for file identity (sha1, md5, size)
FileIdentity = tuple[str, str, int]


@dataclass
class SyncOperation:
    """Represents a single sync operation.

    Attributes:
        op_type: Type of operation - 'copy', 'move', 'touch', 'delete',
            'mkdir', 'update-json-mtime', 'update-dir-mtime'
        source_path: Source file path (None for delete/mkdir/touch operations)
        dest_path: Destination file/directory path
        expected_mtime: Expected modification timestamp (Unix epoch)
        reason: Human-readable explanation of why this operation is needed
    """

    op_type: str
    source_path: str | None
    dest_path: str
    expected_mtime: int | None
    reason: str

    def to_command(self) -> list[str]:
        """Convert operation to shell command(s).

        Returns:
            List of shell commands to execute this operation

        Examples:
            >>> op = SyncOperation('copy', '/src/a.jpg', '/dest/a.jpg', 1234567890, 'new file')
            >>> op.to_command()
            ['rsync -a --times /src/a.jpg /dest/a.jpg']
        """
        if self.op_type == "mkdir":
            return [f"mkdir -p {self.dest_path}"]

        if self.op_type == "copy":
            return [f"rsync -a --times {self.source_path} {self.dest_path}"]

        if self.op_type == "move":
            return [f"mv {self.source_path} {self.dest_path}"]

        if self.op_type == "delete":
            return [f"rm {self.dest_path}"]

        if self.op_type in ("touch", "update-dir-mtime", "update-json-mtime"):
            if self.expected_mtime is None:
                return []
            # Convert Unix timestamp to touch format: YYYYMMDDhhmm.ss
            dt = datetime.fromtimestamp(self.expected_mtime)
            touch_time = dt.strftime("%Y%m%d%H%M.%S")
            return [f"touch -t {touch_time} {self.dest_path}"]

        return []


def build_file_index(data: list[dict[str, str | int]]) -> dict[FileIdentity, dict[str, str | int]]:
    """Build index mapping file identity to metadata.

    Creates a dictionary mapping (sha1, md5, size) tuples to file metadata
    entries. This enables O(1) lookup to detect identical files regardless
    of their path.

    Args:
        data: List of file metadata dictionaries with keys: path, sha1, md5,
            date, size

    Returns:
        Dictionary mapping FileIdentity (sha1, md5, size) to file metadata

    Examples:
        >>> data = [{'path': '/a.jpg', 'sha1': 'abc', 'md5': 'def', 'size': 100, 'date': '...'}]
        >>> index = build_file_index(data)
        >>> ('abc', 'def', 100) in index
        True
    """
    index: dict[FileIdentity, dict[str, str | int]] = {}

    for entry in data:
        sha1 = str(entry.get("sha1", ""))
        md5 = str(entry.get("md5", ""))
        size = int(entry.get("size", 0))

        if sha1 and md5 and size >= 0:
            identity: FileIdentity = (sha1, md5, size)
            # Store first occurrence (in case of duplicates, which shouldn't happen)
            if identity not in index:
                index[identity] = entry

    return index


def load_version_data(directory: str) -> tuple[dict[str, object] | None, str | None]:
    """Load .version.json file data and path.

    Attempts to load and parse the .version.json file from the specified
    directory. Returns both the parsed data and the file path for later use.

    Args:
        directory: Archive directory path to search for .version.json

    Returns:
        Tuple containing:
            - Parsed version data dictionary, or None if not found/invalid
            - Path to the version file, or None if not found

    Examples:
        >>> data, path = load_version_data("/archive")
        >>> data["version"] if data else None
        'photos-1.234-567'
    """
    version_file = find_version_file(directory)
    if not version_file:
        return None, None

    try:
        with Path(version_file).open(encoding="utf-8") as f:
            return json.load(f), version_file
    except (json.JSONDecodeError, OSError):
        return None, version_file


def compare_version_files(
    source_version: dict[str, object] | None,
    dest_version: dict[str, object] | None,
) -> tuple[set[str], set[str], set[str]]:
    """Compare version files to find changed, new, and deleted JSON files.

    Compares the SHA1 hashes of JSON files recorded in both version files
    to determine which files have changed, which are new, and which have
    been deleted.

    Args:
        source_version: Source .version.json data (with 'files' mapping)
        dest_version: Destination .version.json data (with 'files' mapping)

    Returns:
        Tuple containing three sets of JSON filenames:
            - changed_jsons: Files present in both but with different SHA1
            - new_jsons: Files only in source
            - deleted_jsons: Files only in destination

    Examples:
        >>> source = {"files": {"photos.json": "abc123"}}
        >>> dest = {"files": {"photos.json": "def456"}}
        >>> changed, new, deleted = compare_version_files(source, dest)
        >>> "photos.json" in changed
        True
    """
    source_files: dict[str, str] = {}
    dest_files: dict[str, str] = {}

    if source_version:
        files_data = source_version.get("files")
        if isinstance(files_data, dict):
            source_files = files_data

    if dest_version:
        files_data = dest_version.get("files")
        if isinstance(files_data, dict):
            dest_files = files_data

    changed: set[str] = set()
    new: set[str] = set()
    deleted: set[str] = set()

    for name, sha1 in source_files.items():
        if name not in dest_files:
            new.add(name)
        elif dest_files[name] != sha1:
            changed.add(name)

    for name in dest_files:
        if name not in source_files:
            deleted.add(name)

    return changed, new, deleted


def compute_sync_plan(
    source_data: list[dict[str, str | int]],
    dest_data: list[dict[str, str | int]],
    source_dir: str,
    dest_dir: str,
) -> tuple[list[SyncOperation], list[str]]:
    """Generate minimal sync operations to synchronize archives.

    Compares source and destination archives by file content (sha1, md5, size)
    and generates operations to synchronize. Timestamps must match exactly.

    Args:
        source_data: File metadata from source archive (relative paths)
        dest_data: File metadata from destination archive (relative paths)
        source_dir: Source archive directory path
        dest_dir: Destination archive directory path

    Returns:
        Tuple containing:
            - List of SyncOperation objects (with absolute paths)
            - List of warning messages

    Examples:
        >>> source = [{'path': 'a.jpg', 'sha1': 'abc', 'md5': 'def',
        ...            'size': 100, 'date': '2024-01-01T12:00:00+0100'}]
        >>> dest = []
        >>> ops, warnings = compute_sync_plan(source, dest, '/src', '/dest')
        >>> ops[0].op_type
        'copy'
    """
    operations: list[SyncOperation] = []
    warnings: list[str] = []

    # Convert to Path objects for joining
    source_base = Path(source_dir)
    dest_base = Path(dest_dir)

    # Build index mapping file identity (sha1, md5, size) to metadata
    dest_index = build_file_index(dest_data)

    # Build path mapping for destination files
    dest_by_path = {str(entry["path"]): entry for entry in dest_data}

    # Track which dest files we've matched (using relative paths)
    matched_dest_files: set[str] = set()

    # Phase 1: Process each source file
    for source_entry in source_data:
        rel_path = str(source_entry["path"])
        sha1 = str(source_entry.get("sha1", ""))
        md5 = str(source_entry.get("md5", ""))
        size = int(source_entry.get("size", 0))
        source_date = str(source_entry.get("date", ""))
        source_mtime = int(datetime.fromisoformat(source_date).timestamp())

        identity: FileIdentity = (sha1, md5, size)

        # Check if file with same content exists in destination
        if identity in dest_index:
            dest_entry = dest_index[identity]
            dest_rel_path = str(dest_entry["path"])
            dest_date = str(dest_entry.get("date", ""))
            dest_mtime = int(datetime.fromisoformat(dest_date).timestamp())

            matched_dest_files.add(dest_rel_path)

            if rel_path == dest_rel_path and source_mtime == dest_mtime:
                # Identical file: same content, same path, same timestamp
                # No operation needed
                pass
            elif rel_path == dest_rel_path:
                # Same content and path, different timestamp -> touch
                operations.append(
                    SyncOperation(
                        op_type="touch",
                        source_path=None,
                        dest_path=str(dest_base / rel_path),
                        expected_mtime=source_mtime,
                        reason=f"timestamp mismatch: {dest_date} -> {source_date}",
                    )
                )
            else:
                # Same content, different path -> move within destination
                operations.append(
                    SyncOperation(
                        op_type="move",
                        source_path=str(dest_base / dest_rel_path),
                        dest_path=str(dest_base / rel_path),
                        expected_mtime=None,
                        reason=f"rename: {dest_rel_path} -> {rel_path}",
                    )
                )
                # After move, fix timestamp if needed
                if source_mtime != dest_mtime:
                    operations.append(
                        SyncOperation(
                            op_type="touch",
                            source_path=None,
                            dest_path=str(dest_base / rel_path),
                            expected_mtime=source_mtime,
                            reason="timestamp correction after move",
                        )
                    )
        else:
            # File content not found in destination -> copy
            if rel_path in dest_by_path:
                # Same path exists but different content (file modified)
                warnings.append(f"File modified: {rel_path} (will be replaced)")
                matched_dest_files.add(rel_path)

            operations.append(
                SyncOperation(
                    op_type="copy",
                    source_path=str(source_base / rel_path),
                    dest_path=str(dest_base / rel_path),
                    expected_mtime=source_mtime,
                    reason="new file" if rel_path not in dest_by_path else "content changed",
                )
            )

    # Phase 2: Find files to delete (in dest but not matched to any source file)
    for dest_entry in dest_data:
        dest_rel_path = str(dest_entry["path"])

        if dest_rel_path not in matched_dest_files:
            operations.append(
                SyncOperation(
                    op_type="delete",
                    source_path=None,
                    dest_path=str(dest_base / dest_rel_path),
                    expected_mtime=None,
                    reason="file not in source",
                )
            )

    return operations, warnings


def optimize_operations(
    operations: list[SyncOperation],
    dest_data: list[dict[str, str | int]],
    dest_dir: str,
) -> list[SyncOperation]:
    """Optimize operations to minimize work.

    Performs:
    - Detects required directories and adds mkdir operations only for new directories
    - Sorts operations by dependency order

    Args:
        operations: List of sync operations (with absolute paths)
        dest_data: Destination archive metadata (with relative paths)
        dest_dir: Destination archive directory path

    Returns:
        Optimized and sorted list of operations

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/new/a.jpg', 123, 'test')]
        >>> optimized = optimize_operations(ops, [], [], '/dest')
        >>> optimized[0].op_type
        'mkdir'
    """
    optimized: list[SyncOperation] = []

    dest_base = Path(dest_dir)

    # Build set of existing directories from destination data (as absolute paths)
    existing_dirs: set[str] = set()
    for entry in dest_data:
        rel_path = str(entry.get("path", ""))
        if rel_path:
            full_path = dest_base / rel_path
            parent = str(full_path.parent)
            if parent != "/" and parent != ".":
                existing_dirs.add(parent)

    # Extract directories that need to be created
    required_dirs: set[str] = set()
    for op in operations:
        if op.op_type in ("copy", "move", "touch"):
            parent = str(Path(op.dest_path).parent)
            if parent != "/" and parent != "." and parent not in existing_dirs:
                required_dirs.add(parent)

    # Add mkdir operations for new directories
    for dir_path in sorted(required_dirs):
        optimized.append(
            SyncOperation(
                op_type="mkdir",
                source_path=None,
                dest_path=dir_path,
                expected_mtime=None,
                reason="create directory",
            )
        )

    # Sort operations by type to ensure correct execution order:
    # 1. mkdir - create directories first
    # 2. delete - remove files before adding new ones
    # 3. move - relocate existing files
    # 4. copy - add new files
    # 5. touch - fix file timestamps
    # 6. update-dir-mtime - fix directory timestamps
    # 7. update-json-mtime - fix JSON timestamps
    op_priority = {
        "mkdir": 0,
        "delete": 1,
        "move": 2,
        "copy": 3,
        "touch": 4,
        "update-dir-mtime": 5,
        "update-json-mtime": 6,
    }

    # Add remaining operations and sort
    optimized.extend(operations)
    optimized.sort(key=lambda op: (op_priority.get(op.op_type, 99), op.dest_path))

    return optimized


def compute_metadata_updates(
    operations: list[SyncOperation],
    source_data: list[dict[str, str | int]],
    dest_dir: str,
) -> list[SyncOperation]:
    """Generate directory and JSON timestamp updates.

    Identifies directories and JSON files affected by sync operations and
    generates operations to update their timestamps to match source.

    Args:
        operations: List of sync operations that will be performed (with absolute paths)
        source_data: Source archive metadata (with relative paths)
        dest_dir: Destination archive directory path

    Returns:
        List of additional SyncOperation objects for metadata updates

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/a.jpg', 123, 'test')]
        >>> source = [{'path': 'a.jpg', 'date': '2024-01-01T12:00:00+0100'}]
        >>> metadata_ops = compute_metadata_updates(ops, source, '/dest')
        >>> len(metadata_ops) >= 0
        True
    """
    metadata_ops: list[SyncOperation] = []

    dest_base = Path(dest_dir)

    # Group source files by directory (using absolute paths for consistency with operations)
    dir_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in source_data:
        rel_path = str(entry.get("path", ""))
        if not rel_path:
            continue

        # Convert to absolute path in dest to match operations
        full_path = dest_base / rel_path
        dir_path = str(full_path.parent)
        if dir_path not in dir_files:
            dir_files[dir_path] = []
        dir_files[dir_path].append(entry)

    # Find directories affected by operations (need timestamp update)
    affected_dirs: set[str] = set()
    for op in operations:
        if op.op_type in ("copy", "move", "delete", "touch"):
            affected_dirs.add(str(Path(op.dest_path).parent))

    # Generate directory timestamp updates for all affected directories
    for dir_path in sorted(affected_dirs):
        if dir_path in dir_files:
            # Find newest file in directory to set directory mtime
            files = dir_files[dir_path]
            if files:
                newest_file = max(files, key=lambda x: datetime.fromisoformat(str(x["date"])))
                newest_mtime = int(datetime.fromisoformat(str(newest_file["date"])).timestamp())

                metadata_ops.append(
                    SyncOperation(
                        op_type="update-dir-mtime",
                        source_path=None,
                        dest_path=dir_path,
                        expected_mtime=newest_mtime,
                        reason="sync directory timestamp with newest file",
                    )
                )

    return metadata_ops


def compute_json_operations(
    changed_jsons: set[str],
    new_jsons: set[str],
    deleted_jsons: set[str],
    source_dir: str,
    dest_dir: str,
) -> list[SyncOperation]:
    """Generate operations for JSON metadata files.

    Creates copy operations for changed and new JSON files, and delete
    operations for JSON files that no longer exist in source.

    Args:
        changed_jsons: JSON filenames with different SHA1 in source vs dest
        new_jsons: JSON filenames only present in source
        deleted_jsons: JSON filenames only present in destination
        source_dir: Source archive directory path
        dest_dir: Destination archive directory path

    Returns:
        List of SyncOperation for JSON metadata files

    Examples:
        >>> ops = compute_json_operations({"a.json"}, set(), set(), "/src", "/dest")
        >>> ops[0].op_type
        'copy'
    """
    operations: list[SyncOperation] = []
    source_base = Path(source_dir)
    dest_base = Path(dest_dir)

    # Copy changed and new JSONs
    for json_name in sorted(changed_jsons | new_jsons):
        source_json = source_base / json_name
        dest_json = dest_base / json_name
        mtime = int(source_json.stat().st_mtime) if source_json.exists() else None

        operations.append(
            SyncOperation(
                op_type="copy",
                source_path=str(source_json),
                dest_path=str(dest_json),
                expected_mtime=mtime,
                reason="JSON changed" if json_name in changed_jsons else "new JSON",
            )
        )

    # Delete removed JSONs
    for json_name in sorted(deleted_jsons):
        operations.append(
            SyncOperation(
                op_type="delete",
                source_path=None,
                dest_path=str(dest_base / json_name),
                expected_mtime=None,
                reason="JSON not in source",
            )
        )

    return operations


def compute_version_operation(
    source_version_path: str | None,
    dest_dir: str,
) -> SyncOperation | None:
    """Generate operation for .version.json file.

    Creates a copy operation to sync the .version.json file from source
    to destination archive.

    Args:
        source_version_path: Path to source .version.json file, or None
        dest_dir: Destination archive directory path

    Returns:
        SyncOperation to copy .version.json, or None if no source version

    Examples:
        >>> op = compute_version_operation("/src/.version.json", "/dest")
        >>> op.op_type if op else None
        'copy'
    """
    if not source_version_path:
        return None

    source_path = Path(source_version_path)
    if not source_path.exists():
        return None

    dest_path = Path(dest_dir) / source_path.name
    mtime = int(source_path.stat().st_mtime)

    return SyncOperation(
        op_type="copy",
        source_path=str(source_path),
        dest_path=str(dest_path),
        expected_mtime=mtime,
        reason="sync version file",
    )


def load_archive(
    directory: str,
    json_filter: set[str] | None = None,
) -> tuple[
    list[dict[str, str | int]],  # all_data
    list[str],  # json_files (loaded ones)
    str | None,  # version_file
    list[str],  # errors
]:
    """Load archive data including JSON files and version file.

    Args:
        directory: Path to archive directory
        json_filter: If provided, only load JSON files whose names are in this set.
            This enables optimization when only certain directories need syncing.

    Returns:
        Tuple containing:
            - Combined data from all loaded JSON files
            - List of loaded JSON file paths
            - Version file path (or None)
            - List of error messages

    Examples:
        >>> data, json_files, version, errors = load_archive("/archive")
        >>> len(errors) == 0
        True
        >>> # Load only specific JSON files
        >>> data, json_files, version, errors = load_archive("/archive", {"photos.json"})
    """
    errors: list[str] = []
    all_data: list[dict[str, str | int]] = []
    loaded_json_files: list[str] = []

    # Find version file
    version_file = find_version_file(directory)

    # Find JSON files
    try:
        json_files = find_json_files(directory)
    except SystemExit as e:
        errors.append(f"Failed to find JSON files: {e}")
        return [], [], version_file, errors

    # Load data from each JSON file (keep relative paths for comparison)
    for json_file in json_files:
        # Skip if filter provided and this file not in filter
        if json_filter is not None:
            json_name = Path(json_file).name
            if json_name not in json_filter:
                continue

        try:
            data = load_json(json_file)
            all_data.extend(data)
            loaded_json_files.append(json_file)
        except SystemExit as e:
            errors.append(f"Failed to load {json_file}: {e}")

    return all_data, loaded_json_files, version_file, errors


def validate_archive_directories(
    source_dir: str,
    dest_dir: str,
    check_dest_writable: bool = False,
) -> tuple[bool, list[str]]:
    """Validate that both archives are accessible and have required files.

    Args:
        source_dir: Source archive directory
        dest_dir: Destination archive directory
        check_dest_writable: Whether to check if destination is writable

    Returns:
        Tuple containing:
            - bool: True if validation passed
            - list[str]: Error messages (empty if valid)

    Examples:
        >>> valid, errors = validate_archive_directories("/src", "/dest")
        >>> valid
        True
    """
    errors: list[str] = []

    # Check source directory
    source_path = Path(source_dir)
    if not source_path.exists():
        errors.append(f"Source directory does not exist: {source_dir}")
    elif not source_path.is_dir():
        errors.append(f"Source path is not a directory: {source_dir}")
    elif not os.access(source_dir, os.R_OK):
        errors.append(f"Source directory is not readable: {source_dir}")

    # Check destination directory
    dest_path = Path(dest_dir)
    if not dest_path.exists():
        errors.append(f"Destination directory does not exist: {dest_dir}")
    elif not dest_path.is_dir():
        errors.append(f"Destination path is not a directory: {dest_dir}")
    elif not os.access(dest_dir, os.R_OK):
        errors.append(f"Destination directory is not readable: {dest_dir}")
    elif check_dest_writable and not os.access(dest_dir, os.W_OK):
        errors.append(f"Destination directory is not writable: {dest_dir}")

    return len(errors) == 0, errors


def rewrite_operation_paths(
    operations: list[SyncOperation],
    original_dest: str,
    new_dest: str,
) -> list[SyncOperation]:
    """Rewrite destination paths in operations for output.

    This function replaces the original destination path prefix with a new
    destination path in all operations. Useful for generating scripts that
    will be executed on a remote server with a different path structure.

    Args:
        operations: List of sync operations with original paths
        original_dest: Original destination directory path to replace
        new_dest: New destination directory path for output

    Returns:
        New list of SyncOperation objects with rewritten paths

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/local/dest/a.jpg', 123, 'test')]
        >>> rewritten = rewrite_operation_paths(ops, '/local/dest', '/remote/dest')
        >>> rewritten[0].dest_path
        '/remote/dest/a.jpg'
    """
    rewritten: list[SyncOperation] = []

    for op in operations:
        new_dest_path = op.dest_path.replace(original_dest, new_dest, 1)
        new_source_path = op.source_path

        # Also rewrite source_path for move operations (within dest)
        if op.op_type == "move" and op.source_path:
            new_source_path = op.source_path.replace(original_dest, new_dest, 1)

        rewritten.append(
            SyncOperation(
                op_type=op.op_type,
                source_path=new_source_path,
                dest_path=new_dest_path,
                expected_mtime=op.expected_mtime,
                reason=op.reason,
            )
        )

    return rewritten


def generate_sync_script(
    operations: list[SyncOperation],
    output_path: str,
) -> None:
    """Write operations as executable shell script.

    Groups operations by type with block comments and sorts alphabetically
    within each group. Operations are written without individual comments
    to keep the script concise.

    Args:
        operations: List of sync operations
        output_path: Path to output script file

    Raises:
        SystemExit: If script cannot be written

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/a.jpg', 123, 'test')]
        >>> generate_sync_script(ops, "sync.sh")
    """
    # Group operations by type
    groups: dict[str, list[SyncOperation]] = {}
    for op in operations:
        if op.op_type not in groups:
            groups[op.op_type] = []
        groups[op.op_type].append(op)

    # Sort each group alphabetically by dest_path
    for ops_list in groups.values():
        ops_list.sort(key=lambda op: op.dest_path)

    # Define group order and labels
    group_order = [
        ("mkdir", "Create directories"),
        ("delete", "Delete files"),
        ("move", "Move/rename files"),
        ("copy", "Copy files"),
        ("touch", "Fix file timestamps"),
        ("update-dir-mtime", "Fix directory timestamps"),
        ("update-json-mtime", "Fix JSON timestamps"),
    ]

    try:
        with Path(output_path).open("w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n")
            f.write("set -e\n\n")

            for op_type, label in group_order:
                if op_type not in groups:
                    continue

                ops_list = groups[op_type]
                f.write(f"# {label}\n")
                for op in ops_list:
                    for cmd in op.to_command():
                        f.write(f"{cmd}\n")
                f.write("\n")

        # Make script executable
        script_path = Path(output_path)
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        print(f"Sync script written to: {output_path}")
    except OSError as e:
        raise SystemExit(f"Error: Cannot write sync script to '{output_path}': {e}") from e


def check_for_dangerous_operations(
    operations: list[SyncOperation],
) -> tuple[bool, list[str]]:
    """Check for potentially dangerous operations.

    Warns about:
    - Mass deletions (>30% or >100 files)

    Args:
        operations: List of sync operations

    Returns:
        Tuple containing:
            - bool: True if operations seem dangerous
            - list[str]: Warning messages

    Examples:
        >>> ops = [SyncOperation('delete', None, f'/file{i}', None, 'test') for i in range(150)]
        >>> dangerous, warnings = check_for_dangerous_operations(ops)
        >>> dangerous
        True
    """
    warnings: list[str] = []
    dangerous = False

    # Count deletions
    total_ops = len(operations)
    delete_ops = sum(1 for op in operations if op.op_type == "delete")

    if delete_ops > 100:
        warnings.append(f"Mass deletion detected: {delete_ops} files will be deleted")
        dangerous = True
    elif total_ops > 0 and delete_ops / total_ops > 0.3:
        percentage = 100 * delete_ops / total_ops
        warnings.append(
            f"Large proportion of deletions: {delete_ops}/{total_ops} ({percentage:.1f}%)"
        )
        dangerous = True

    return dangerous, warnings


def execute_sync(
    operations: list[SyncOperation],
    dry_run: bool = True,
) -> tuple[int, int]:
    """Execute sync operations.

    Args:
        operations: List of operations to execute
        dry_run: If True, only print operations without executing

    Returns:
        Tuple containing:
            - int: Number of successful operations
            - int: Number of failed operations

    Examples:
        >>> ops = [SyncOperation('mkdir', None, '/dest/newdir', None, 'test')]
        >>> success, failed = execute_sync(ops, dry_run=True)
        >>> success >= 0
        True
    """
    successful = 0
    failed = 0

    for op in operations:
        commands = op.to_command()

        for cmd in commands:
            if dry_run:
                print(f"[DRY RUN] {cmd}")
                successful += 1
            else:
                try:
                    # Execute command (intentional shell execution for sync operations)
                    result = os.system(cmd)  # noqa: S605  # nosec B605
                    if result == 0:
                        print(f"[OK] {cmd}")
                        successful += 1
                    else:
                        print(f"[FAIL] {cmd}", file=sys.stderr)
                        failed += 1
                except Exception as e:
                    print(f"[ERROR] {cmd}: {e}", file=sys.stderr)
                    failed += 1

    return successful, failed


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for sync command.

    Adds all command-line arguments for the sync tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with sync arguments.
    """
    parser.add_argument(
        "source",
        type=str,
        help="Source archive directory",
    )
    parser.add_argument(
        "dest",
        type=str,
        help="Destination archive directory",
    )
    parser.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Actually execute sync operations (default: dry-run preview only)",
    )
    parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Skip deletion operations",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        metavar="FILE",
        help="Write sync commands to shell script",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed operation information",
    )
    parser.add_argument(
        "-r",
        "--rewrite-dest",
        type=str,
        metavar="PATH",
        help="Rewrite destination path in output commands (for remote execution)",
    )


def _print_operation_summary(op_counts: dict[str, int], total_ops: int) -> None:
    """Print summary of sync operations by type.

    Args:
        op_counts: Dictionary mapping operation types to counts
        total_ops: Total number of operations
    """
    print("\nSync Plan Summary:")
    if "copy" in op_counts:
        print(f"  New files to copy: {op_counts['copy']}")
    if "move" in op_counts:
        print(f"  Files to move/rename: {op_counts['move']}")
    if "touch" in op_counts:
        print(f"  Timestamp corrections: {op_counts['touch']}")
    if "delete" in op_counts:
        print(f"  Files to delete: {op_counts['delete']}")
    if "mkdir" in op_counts:
        print(f"  Directories to create: {op_counts['mkdir']}")
    print(f"  Total operations: {total_ops}")


def _print_verbose_operations(operations: list[SyncOperation], verbose: bool) -> None:
    """Print detailed operation list if verbose mode enabled.

    Args:
        operations: List of sync operations
        verbose: Whether to show detailed information
    """
    if not verbose or not operations:
        return

    print("\nOperations (in execution order):")
    for i, op in enumerate(operations[:20], 1):  # Show first 20
        op_desc = f"[{op.op_type}] {op.dest_path}"
        if op.source_path:
            op_desc += f" (from {op.source_path})"
        print(f"  {i}. {op_desc}")
        if verbose:
            print(f"     Reason: {op.reason}")

    if len(operations) > 20:
        print(f"  ... ({len(operations) - 20} more operations)")


def run(args: argparse.Namespace) -> int:
    """Execute sync command with parsed arguments.

    Performs archive synchronization by:
    1. Validating source and destination archives
    2. Loading archive metadata
    3. Computing sync plan
    4. Optimizing operations
    5. Checking for dangerous operations
    6. Executing or outputting sync commands

    Args:
        args: Parsed command-line arguments with fields:
            - source: Source archive directory
            - dest: Destination archive directory
            - dry_run: Whether to preview changes only
            - execute: Whether to actually execute operations
            - no_delete: Whether to skip deletions
            - output: Optional output script path
            - verbose: Whether to show detailed information

    Returns:
        int: Exit code indicating success or failure
            - os.EX_OK (0): Successful execution
            - 1: Error occurred during processing

    Examples:
        >>> args = parser.parse_args(['/source', '/dest'])
        >>> exit_code = run(args)
        Scanning source archive: /source
        ...
    """
    print(f"Scanning source archive: {args.source}")

    # Validate archives (check write permission only when executing)
    valid, errors = validate_archive_directories(
        args.source, args.dest, check_dest_writable=args.execute
    )
    if not valid:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    # Load and compare version files first (optimization)
    source_version_data, source_version_path = load_version_data(args.source)
    dest_version_data, _dest_version_path = load_version_data(args.dest)

    changed_jsons, new_jsons, deleted_jsons = compare_version_files(
        source_version_data, dest_version_data
    )

    # Determine which JSONs to process
    jsons_to_process: set[str] | None = None
    if source_version_data and dest_version_data:
        # Optimization: only load changed/new JSONs
        jsons_to_process = changed_jsons | new_jsons
        if not jsons_to_process and not deleted_jsons:
            print("Archives are identical (all JSON files have matching SHA1)")
            return os.EX_OK
        print(
            f"  Version comparison: {len(changed_jsons)} changed, "
            f"{len(new_jsons)} new, {len(deleted_jsons)} deleted JSON(s)"
        )
    else:
        # Fallback: no version files, process all
        if source_version_data:
            print("  Source has version file, destination does not")
        elif dest_version_data:
            print("  Destination has version file, source does not")
        else:
            print("  No version files found, comparing all files")

    # Load source archive (filtered if optimization applies)
    source_data, source_json_files, source_version, source_errors = load_archive(
        args.source, json_filter=jsons_to_process
    )
    if source_errors:
        for error in source_errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    if source_version:
        print(f"  Found version file: {Path(source_version).name}")
    print(f"  Found {len(source_json_files)} JSON metadata file(s)")
    print(f"  Total files in source: {len(source_data):,}")

    print(f"\nScanning destination archive: {args.dest}")

    # Load destination archive (filtered if optimization applies)
    dest_data, dest_json_files, dest_version, dest_errors = load_archive(
        args.dest, json_filter=jsons_to_process
    )
    if dest_errors:
        for error in dest_errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    if dest_version:
        print(f"  Found version file: {Path(dest_version).name}")
    print(f"  Found {len(dest_json_files)} JSON metadata file(s)")
    print(f"  Total files in destination: {len(dest_data):,}")

    print("\nAnalyzing differences...")

    # Compute sync plan
    operations, warnings = compute_sync_plan(source_data, dest_data, args.source, args.dest)

    # Add metadata updates
    metadata_ops = compute_metadata_updates(operations, source_data, args.dest)
    operations.extend(metadata_ops)

    # Add JSON file operations (copy changed/new, delete removed)
    json_ops = compute_json_operations(
        changed_jsons, new_jsons, deleted_jsons, args.source, args.dest
    )
    operations.extend(json_ops)

    # Add version file operation
    version_op = compute_version_operation(source_version_path, args.dest)
    if version_op:
        operations.append(version_op)

    # Optimize operations
    operations = optimize_operations(operations, dest_data, args.dest)

    # Filter operations if requested
    if args.no_delete:
        operations = [op for op in operations if op.op_type != "delete"]

    # Count operations by type
    op_counts: dict[str, int] = {}
    for op in operations:
        op_counts[op.op_type] = op_counts.get(op.op_type, 0) + 1

    # Print summary
    _print_operation_summary(op_counts, len(operations))

    # Check for dangerous operations
    dangerous, danger_warnings = check_for_dangerous_operations(operations)
    if danger_warnings:
        print("\nWarnings:")
        for warning in danger_warnings:
            print(f"  - {warning}")

    # Print additional warnings
    if warnings:
        print("\nAdditional warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    # Show detailed operations if verbose
    _print_verbose_operations(operations, args.verbose)

    # Rewrite destination paths if requested (for remote execution)
    if args.rewrite_dest:
        operations = rewrite_operation_paths(operations, args.dest, args.rewrite_dest)

    # Generate script if requested
    if args.output:
        generate_sync_script(operations, args.output)

    # Execute operations or show dry-run message
    if args.execute:
        if dangerous:
            print("\n⚠️  WARNING: Dangerous operations detected!")
            print("Review the operations carefully before proceeding.")

            response = input("Continue with execution? (yes/no): ")
            if response.lower() != "yes":
                print("Operation cancelled.")
                return 1

        print("\nExecuting operations...")
        successful, failed = execute_sync(operations, dry_run=False)

        print("\nExecution complete:")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")

        return 0 if failed == 0 else 1
    else:
        print("\nDRY RUN: No changes made.")
        print("To execute these operations, run with --execute flag.")
        if args.output:
            print(f"To review commands, see: {args.output}")

    return os.EX_OK
