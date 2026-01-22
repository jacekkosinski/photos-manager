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
    normalize_paths,
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


def compute_sync_plan(
    source_data: list[dict[str, str | int]],
    dest_data: list[dict[str, str | int]],
) -> tuple[list[SyncOperation], list[str]]:
    """Generate minimal sync operations to synchronize archives.

    Compares source and destination archives by file content (sha1, md5, size)
    and generates operations to synchronize. Timestamps must match exactly.

    Args:
        source_data: File metadata from source archive
        dest_data: File metadata from destination archive

    Returns:
        Tuple containing:
            - List of SyncOperation objects
            - List of warning messages

    Examples:
        >>> source = [{'path': '/src/a.jpg', 'sha1': 'abc', 'md5': 'def',
        ...            'size': 100, 'date': '2024-01-01T12:00:00+0100'}]
        >>> dest = []
        >>> ops, warnings = compute_sync_plan(source, dest)
        >>> ops[0].op_type
        'copy'
    """
    operations: list[SyncOperation] = []
    warnings: list[str] = []

    # Build indices for fast lookup
    dest_index = build_file_index(dest_data)

    # Build path mappings
    dest_by_path = {str(entry["path"]): entry for entry in dest_data}

    # Track which dest files we've handled
    handled_dest_files: set[str] = set()

    # Phase 1: Process source files
    for source_entry in source_data:
        source_path = str(source_entry["path"])
        sha1 = str(source_entry.get("sha1", ""))
        md5 = str(source_entry.get("md5", ""))
        size = int(source_entry.get("size", 0))
        source_date = str(source_entry.get("date", ""))

        identity: FileIdentity = (sha1, md5, size)

        # Check if file exists in destination by identity
        if identity in dest_index:
            dest_entry = dest_index[identity]
            dest_path = str(dest_entry["path"])
            dest_date = str(dest_entry.get("date", ""))

            handled_dest_files.add(dest_path)

            if source_path == dest_path:
                # Same path, same content - check timestamp
                source_mtime = int(datetime.fromisoformat(source_date).timestamp())
                dest_mtime = int(datetime.fromisoformat(dest_date).timestamp())

                if source_mtime != dest_mtime:
                    operations.append(
                        SyncOperation(
                            op_type="touch",
                            source_path=None,
                            dest_path=dest_path,
                            expected_mtime=source_mtime,
                            reason=f"timestamp mismatch: expected {source_mtime}, got {dest_mtime}",
                        )
                    )
            else:
                # Same content, different path - move operation
                operations.append(
                    SyncOperation(
                        op_type="move",
                        source_path=dest_path,  # Move FROM dest location
                        dest_path=source_path,  # Move TO source location
                        expected_mtime=None,
                        reason=f"file moved/renamed from {dest_path}",
                    )
                )

                handled_dest_files.add(dest_path)

                # Check if timestamp needs updating after move
                source_mtime = int(datetime.fromisoformat(source_date).timestamp())
                dest_mtime = int(datetime.fromisoformat(dest_date).timestamp())

                if source_mtime != dest_mtime:
                    operations.append(
                        SyncOperation(
                            op_type="touch",
                            source_path=None,
                            dest_path=source_path,
                            expected_mtime=source_mtime,
                            reason="timestamp correction after move",
                        )
                    )
        else:
            # File not found by identity
            # Check if same path exists with different content (file modified)
            if source_path in dest_by_path:
                # File content changed at same path
                warnings.append(f"File modified: {source_path} (will be replaced)")
                handled_dest_files.add(source_path)

                source_mtime = int(datetime.fromisoformat(source_date).timestamp())

                operations.append(
                    SyncOperation(
                        op_type="copy",
                        source_path=source_path,
                        dest_path=source_path,
                        expected_mtime=source_mtime,
                        reason="file content changed",
                    )
                )
            else:
                # New file - needs to be copied
                source_mtime = int(datetime.fromisoformat(source_date).timestamp())

                operations.append(
                    SyncOperation(
                        op_type="copy",
                        source_path=source_path,
                        dest_path=source_path,  # Keep same path structure
                        expected_mtime=source_mtime,
                        reason="new file in source",
                    )
                )

    # Phase 2: Find files to delete (in dest but not in source)
    for dest_entry in dest_data:
        dest_path = str(dest_entry["path"])

        if dest_path in handled_dest_files:
            continue

        # Pure deletion (file not in source at all)
        operations.append(
            SyncOperation(
                op_type="delete",
                source_path=None,
                dest_path=dest_path,
                expected_mtime=None,
                reason="file not in source",
            )
        )

    return operations, warnings


def optimize_operations(operations: list[SyncOperation]) -> list[SyncOperation]:
    """Optimize operations to minimize work.

    Performs:
    - Detects required directories and adds mkdir operations
    - Sorts operations by dependency order

    Args:
        operations: List of sync operations

    Returns:
        Optimized and sorted list of operations

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/new/a.jpg', 123, 'test')]
        >>> optimized = optimize_operations(ops)
        >>> optimized[0].op_type
        'mkdir'
    """
    optimized: list[SyncOperation] = []

    # Extract directories that need to exist
    required_dirs: set[str] = set()
    for op in operations:
        if op.op_type in ("copy", "move", "touch"):
            parent = str(Path(op.dest_path).parent)
            if parent != "/" and parent != ".":
                required_dirs.add(parent)

    # Add mkdir operations
    for dir_path in sorted(required_dirs):
        optimized.append(
            SyncOperation(
                op_type="mkdir",
                source_path=None,
                dest_path=dir_path,
                expected_mtime=None,
                reason="ensure directory exists",
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
) -> list[SyncOperation]:
    """Generate directory and JSON timestamp updates.

    Identifies directories and JSON files affected by sync operations and
    generates operations to update their timestamps to match source.

    Args:
        operations: List of sync operations that will be performed
        source_data: Source archive metadata

    Returns:
        List of additional SyncOperation objects for metadata updates

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/a.jpg', 123, 'test')]
        >>> source = [{'path': '/dest/a.jpg', 'date': '2024-01-01T12:00:00+0100'}]
        >>> metadata_ops = compute_metadata_updates(ops, source)
        >>> len(metadata_ops) >= 0
        True
    """
    metadata_ops: list[SyncOperation] = []

    # Group source files by directory
    dir_files: dict[str, list[dict[str, str | int]]] = {}
    for entry in source_data:
        file_path = str(entry.get("path", ""))
        if not file_path:
            continue

        dir_path = str(Path(file_path).parent)
        if dir_path not in dir_files:
            dir_files[dir_path] = []
        dir_files[dir_path].append(entry)

    # Find affected directories (directories with file changes)
    affected_dirs: set[str] = set()
    for op in operations:
        if op.op_type in ("copy", "move", "delete", "touch"):
            affected_dirs.add(str(Path(op.dest_path).parent))

    # Generate directory timestamp updates
    for dir_path in sorted(affected_dirs):
        if dir_path in dir_files:
            # Find newest file in directory
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


def load_archive(
    directory: str,
) -> tuple[
    list[dict[str, str | int]],  # all_data
    list[str],  # json_files
    str | None,  # version_file
    list[str],  # errors
]:
    """Load archive data including JSON files and version file.

    Args:
        directory: Path to archive directory

    Returns:
        Tuple containing:
            - Combined data from all JSON files
            - List of JSON file paths
            - Version file path (or None)
            - List of error messages

    Examples:
        >>> data, json_files, version, errors = load_archive("/archive")
        >>> len(errors) == 0
        True
    """
    errors: list[str] = []
    all_data: list[dict[str, str | int]] = []

    # Find version file
    version_file = find_version_file(directory)

    # Find JSON files
    try:
        json_files = find_json_files(directory)
    except SystemExit as e:
        errors.append(f"Failed to find JSON files: {e}")
        return [], [], version_file, errors

    # Load and normalize data from each JSON file
    for json_file in json_files:
        try:
            data = load_json(json_file)
            data = normalize_paths(data, directory)
            all_data.extend(data)
        except SystemExit as e:
            errors.append(f"Failed to load {json_file}: {e}")

    return all_data, json_files, version_file, errors


def validate_archive_directories(
    source_dir: str,
    dest_dir: str,
) -> tuple[bool, list[str]]:
    """Validate that both archives are accessible and have required files.

    Args:
        source_dir: Source archive directory
        dest_dir: Destination archive directory

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
    elif not os.access(dest_dir, os.W_OK):
        errors.append(f"Destination directory is not writable: {dest_dir}")

    return len(errors) == 0, errors


def generate_sync_script(
    operations: list[SyncOperation],
    output_path: str,
) -> None:
    """Write operations as executable shell script.

    Args:
        operations: List of sync operations
        output_path: Path to output script file

    Raises:
        SystemExit: If script cannot be written

    Examples:
        >>> ops = [SyncOperation('copy', '/src/a.jpg', '/dest/a.jpg', 123, 'test')]
        >>> generate_sync_script(ops, "sync.sh")
    """
    try:
        with Path(output_path).open("w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n")
            f.write("# Auto-generated sync script\n")
            f.write("# Generated by photos-manager sync tool\n\n")
            f.write("set -e  # Exit on error\n\n")

            for op in operations:
                f.write(f"# {op.reason}\n")
                commands = op.to_command()
                for cmd in commands:
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
        "-n",
        "--dry-run",
        action="store_true",
        default=True,
        help="Show operations without executing (DEFAULT)",
    )
    parser.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Actually execute sync operations",
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

    # Validate archives
    valid, errors = validate_archive_directories(args.source, args.dest)
    if not valid:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    # Load source archive
    source_data, source_json_files, source_version, source_errors = load_archive(args.source)
    if source_errors:
        for error in source_errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    if source_version:
        print(f"  Found version file: {Path(source_version).name}")
    print(f"  Found {len(source_json_files)} JSON metadata file(s)")
    print(f"  Total files in source: {len(source_data):,}")

    print(f"\nScanning destination archive: {args.dest}")

    # Load destination archive
    dest_data, dest_json_files, dest_version, dest_errors = load_archive(args.dest)
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
    operations, warnings = compute_sync_plan(source_data, dest_data)

    # Add metadata updates
    metadata_ops = compute_metadata_updates(operations, source_data)
    operations.extend(metadata_ops)

    # Optimize operations
    operations = optimize_operations(operations)

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
