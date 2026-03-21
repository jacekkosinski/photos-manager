"""prepare - Prepare directories for archiving by fixing permissions and filenames.

This script checks and fixes:
- File permissions (should be 644)
- Directory permissions (should be 755)
- File/directory ownership (should be storage:storage by default)
- Filenames (should be lowercase with no spaces - spaces are converted to underscores)

Hidden files (starting with .) are skipped. Symbolic links are checked but not followed.

Usage:
    photos prepare /path/to/directory              # preview changes
    photos prepare /path/to/directory --fix        # apply changes
    photos prepare /path/to/directory --fix --owner storage --group storage
"""

import argparse
import grp
import os
import pwd
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

from photos_manager.common import resolve_group_name, resolve_owner_name, validate_directory

# Expected permissions
FILE_PERMISSIONS = 0o644
DIR_PERMISSIONS = 0o755


def is_hidden(path: Path) -> bool:
    """Check if a file or directory is hidden.

    A path is considered hidden if its name starts with a dot.

    Args:
        path: Path to check.

    Returns:
        True if the path is hidden, False otherwise.

    Examples:
        >>> is_hidden(Path(".git"))
        True
        >>> is_hidden(Path("photos"))
        False
    """
    return path.name.startswith(".")


def iter_directory(directory: Path) -> Iterator[Path]:
    """Recursively scan directory, skipping hidden files.

    Yields all files and directories under the given path, excluding
    hidden entries (those starting with a dot). Symbolic links are
    yielded but not followed.

    Args:
        directory: Root directory to scan.

    Yields:
        Path objects for each non-hidden file and directory.

    Raises:
        SystemExit: If the directory does not exist or is not accessible.

    Examples:
        >>> list(iter_directory(Path("/tmp/photos")))
        [PosixPath('/tmp/photos/img.jpg'), PosixPath('/tmp/photos/subdir')]
    """
    try:
        for item in sorted(directory.iterdir()):
            if is_hidden(item):
                continue
            if item.is_symlink():
                yield item  # Yield symlink but don't follow
            elif item.is_dir():
                yield item
                yield from iter_directory(item)
            else:
                yield item
    except PermissionError as e:
        raise SystemExit(f"Error: Cannot access directory '{directory}': {e}") from e


def get_items_depth_first(directory: Path) -> list[Path]:
    """Get all items sorted by depth (deepest first).

    This ordering is essential for renaming operations to ensure
    child items are renamed before their parent directories.

    Args:
        directory: Root directory to scan.

    Returns:
        List of paths sorted from deepest to shallowest.

    Examples:
        >>> get_items_depth_first(Path("/tmp/a"))
        [PosixPath('/tmp/a/b/c.txt'), PosixPath('/tmp/a/b'), PosixPath('/tmp/a/d.txt')]
    """
    items = list(iter_directory(directory))
    # Sort by depth (number of parts), deepest first
    return sorted(items, key=lambda p: len(p.parts), reverse=True)


def check_file_permissions(path: Path) -> tuple[bool, int]:
    """Check if a file has the expected permissions (644).

    Args:
        path: Path to the file to check.

    Returns:
        Tuple of (is_correct, current_permissions).

    Examples:
        >>> check_file_permissions(Path("/tmp/file.txt"))
        (True, 420)  # 420 = 0o644
    """
    current = stat.S_IMODE(path.stat().st_mode)
    return current == FILE_PERMISSIONS, current


def check_dir_permissions(path: Path) -> tuple[bool, int]:
    """Check if a directory has the expected permissions (755).

    Args:
        path: Path to the directory to check.

    Returns:
        Tuple of (is_correct, current_permissions).

    Examples:
        >>> check_dir_permissions(Path("/tmp/photos"))
        (True, 493)  # 493 = 0o755
    """
    current = stat.S_IMODE(path.stat().st_mode)
    return current == DIR_PERMISSIONS, current


def _owner_group_names(st: os.stat_result) -> tuple[str, str]:
    """Return (username, groupname) from a stat result, falling back to uid/gid strings."""
    return resolve_owner_name(st.st_uid) or str(st.st_uid), resolve_group_name(st.st_gid) or str(
        st.st_gid
    )


def check_ownership(path: Path, user: str, group: str) -> tuple[bool, str, str]:
    """Check if a path has the expected owner and group.

    Args:
        path: Path to check.
        user: Expected username.
        group: Expected group name.

    Returns:
        Tuple of (is_correct, current_user, current_group).

    Examples:
        >>> check_ownership(Path("/tmp/file.txt"), "storage", "storage")
        (False, 'root', 'wheel')
    """
    st = path.stat()
    current_user, current_group = _owner_group_names(st)
    is_correct = current_user == user and current_group == group
    return is_correct, current_user, current_group


def has_uppercase(name: str) -> bool:
    """Check if a string contains uppercase letters.

    Args:
        name: String to check.

    Returns:
        True if the string contains at least one uppercase letter.

    Examples:
        >>> has_uppercase("IMG_001.JPG")
        True
        >>> has_uppercase("photo.jpg")
        False
    """
    return any(c.isupper() for c in name)


def has_spaces(name: str) -> bool:
    """Check if a string contains spaces.

    Args:
        name: String to check.

    Returns:
        True if the string contains at least one space.

    Examples:
        >>> has_spaces("my file.jpg")
        True
        >>> has_spaces("my_file.jpg")
        False
    """
    return " " in name


def needs_normalization(name: str) -> bool:
    """Check if filename needs normalization (uppercase or spaces).

    Args:
        name: Filename to check.

    Returns:
        True if the name contains uppercase letters or spaces.

    Examples:
        >>> needs_normalization("My File.JPG")
        True
        >>> needs_normalization("my_file.jpg")
        False
    """
    return has_uppercase(name) or has_spaces(name)


def _rel(path: Path, root: Path | None) -> str:
    """Return path relative to root for display, falling back to str(path)."""
    if root is None:
        return str(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def get_unique_normalized_path(path: Path) -> Path:
    """Get a unique normalized path (lowercase, no spaces), adding suffix if needed.

    Converts uppercase letters to lowercase and spaces to underscores.
    If the normalized version of the path already exists (and is not
    the same file on case-insensitive filesystems), a numeric suffix
    is added to make it unique.

    Args:
        path: Original path with potentially uppercase letters or spaces.

    Returns:
        A unique path with lowercase letters and underscores instead of spaces.

    Examples:
        >>> get_unique_normalized_path(Path("/tmp/IMG_001.JPG"))
        PosixPath('/tmp/img_001.jpg')
        >>> get_unique_normalized_path(Path("/tmp/My File.txt"))
        PosixPath('/tmp/my_file.txt')
    """
    base_name = path.stem.lower().replace(" ", "_")
    suffix = path.suffix.lower()
    new_path = path.parent / f"{base_name}{suffix}"

    # If it resolves to the same file (case-insensitive fs), return as-is
    if new_path.exists():
        try:
            if new_path.resolve() == path.resolve():
                return new_path
        except OSError:
            pass

    # Add numeric suffix if there's a conflict
    counter = 1
    while new_path.exists():
        new_path = path.parent / f"{base_name}_{counter}{suffix}"
        counter += 1

    return new_path


def fix_file_permissions(path: Path, dry_run: bool, root: Path | None = None) -> bool:
    """Fix file permissions to 644.

    Args:
        path: Path to the file.
        dry_run: If True, only print what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        if dry_run:
            print(f"  {_rel(path, root)}: {oct(stat.S_IMODE(path.stat().st_mode))} → 0o644")
        else:
            path.chmod(FILE_PERMISSIONS)
            print(f"  {_rel(path, root)}: permissions set to 0o644")
        return True
    except OSError as e:
        print(f"  Error: {_rel(path, root)}: cannot change permissions: {e}", file=sys.stderr)
        return False


def fix_dir_permissions(path: Path, dry_run: bool, root: Path | None = None) -> bool:
    """Fix directory permissions to 755.

    Args:
        path: Path to the directory.
        dry_run: If True, only print what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        if dry_run:
            print(f"  {_rel(path, root)}: {oct(stat.S_IMODE(path.stat().st_mode))} → 0o755")
        else:
            path.chmod(DIR_PERMISSIONS)
            print(f"  {_rel(path, root)}: permissions set to 0o755")
        return True
    except OSError as e:
        print(f"  Error: {_rel(path, root)}: cannot change permissions: {e}", file=sys.stderr)
        return False


def fix_ownership(
    path: Path, user: str, group: str, dry_run: bool, root: Path | None = None
) -> bool:
    """Fix file/directory ownership.

    Args:
        path: Path to fix.
        user: Target username.
        group: Target group name.
        dry_run: If True, only print what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError as e:
        print(f"  Error: {_rel(path, root)}: user or group not found: {e}", file=sys.stderr)
        return False

    st = path.stat()
    current_user, current_group = _owner_group_names(st)

    try:
        if dry_run:
            print(f"  {_rel(path, root)}: {current_user}:{current_group} → {user}:{group}")
        else:
            os.chown(path, uid, gid)
            print(f"  {_rel(path, root)}: ownership set to {user}:{group}")
        return True
    except OSError as e:
        print(f"  Error: {_rel(path, root)}: cannot change ownership: {e}", file=sys.stderr)
        return False


def rename_to_normalized(path: Path, dry_run: bool, root: Path | None = None) -> tuple[bool, Path]:
    """Rename file/directory to normalized form (lowercase, no spaces).

    Converts uppercase letters to lowercase and spaces to underscores.
    If a conflict exists, a numeric suffix is added to the name.

    Args:
        path: Path to rename.
        dry_run: If True, only print what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        Tuple of (success, new_path). On dry-run, returns the target path.

    Examples:
        >>> rename_to_normalized(Path("/tmp/My File.TXT"), dry_run=False)
        (True, PosixPath('/tmp/my_file.txt'))
    """
    if not needs_normalization(path.name):
        return True, path

    new_path = get_unique_normalized_path(path)

    # Check if already normalized (same path)
    if new_path.name == path.name:
        return True, path

    # Check if suffix was added (conflict case)
    expected_normalized = path.name.lower().replace(" ", "_")
    has_conflict = new_path.name != expected_normalized

    try:
        if dry_run:
            if has_conflict:
                print(
                    f"  {_rel(path, root)} → {new_path.name} (conflict with {expected_normalized})"
                )
            else:
                print(f"  {_rel(path, root)} → {new_path.name}")
            return True, new_path
        else:
            path.rename(new_path)
            if has_conflict:
                print(
                    f"  {_rel(path, root)} → {new_path.name} (conflict with {expected_normalized})"
                )
            else:
                print(f"  {_rel(path, root)} → {new_path.name}")
            return True, new_path
    except OSError as e:
        print(f"  Error: {_rel(path, root)}: cannot rename: {e}", file=sys.stderr)
        return False, path


def _get_current_path(item: Path, path_map: dict[Path, Path]) -> Path:
    """Get the current path for an item, accounting for parent renames.

    Args:
        item: Original item path.
        path_map: Mapping of old paths to new paths from renames.

    Returns:
        The current path after accounting for any parent directory renames.
    """
    for old, new in path_map.items():
        if item != old and item.is_relative_to(old):
            return new / item.relative_to(old)
    return item


def _update_paths_for_dry_run(all_items: list[Path], path_map: dict[Path, Path]) -> list[Path]:
    """Update paths based on rename map for dry-run mode.

    Args:
        all_items: List of original paths.
        path_map: Mapping of old paths to new paths.

    Returns:
        List of updated paths.
    """
    updated_items = []
    for item in all_items:
        current = path_map.get(item, item)
        if current == item:
            current = _get_current_path(item, path_map)
        updated_items.append(current)
    return updated_items


def _process_filenames(
    all_items: list[Path], dry_run: bool, root: Path | None = None
) -> tuple[bool, dict[Path, Path]]:
    """Process filename fixes (normalize: lowercase, no spaces).

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        Tuple of (has_errors, path_map).
    """
    print("\nFilenames (lowercase, no spaces):")
    has_errors = False
    has_fixes = False
    path_map: dict[Path, Path] = {}

    for item in all_items:
        current_path = _get_current_path(item, path_map)
        if not current_path.exists():
            continue

        if needs_normalization(current_path.name):
            has_fixes = True
            success, new_path = rename_to_normalized(current_path, dry_run, root=root)
            if success and new_path != current_path:
                path_map[current_path] = new_path
            elif not success:
                has_errors = True

    if not has_fixes:
        print("  All names are normalized")

    return has_errors, path_map


def _process_file_permissions(
    all_items: list[Path], dry_run: bool, root: Path | None = None
) -> tuple[bool, int]:
    """Process file permission fixes.

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        Tuple of (has_errors, change_count).
    """
    print("\nFile permissions (644):")
    has_errors = False
    count = 0

    for item in all_items:
        if item.is_symlink() or not item.is_file():
            continue
        is_ok, _current_perms = check_file_permissions(item)
        if not is_ok:
            count += 1
            if not fix_file_permissions(item, dry_run, root=root):
                has_errors = True

    if not count:
        print("  All files have correct permissions")

    return has_errors, count


def _process_dir_permissions(
    all_items: list[Path], dry_run: bool, root: Path | None = None
) -> tuple[bool, int]:
    """Process directory permission fixes.

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        Tuple of (has_errors, change_count).
    """
    print("\nDirectory permissions (755):")
    has_errors = False
    count = 0

    for item in all_items:
        if item.is_symlink() or not item.is_dir():
            continue
        is_ok, _current_perms = check_dir_permissions(item)
        if not is_ok:
            count += 1
            if not fix_dir_permissions(item, dry_run, root=root):
                has_errors = True

    if not count:
        print("  All directories have correct permissions")

    return has_errors, count


def _process_ownership(
    all_items: list[Path], user: str, group: str, dry_run: bool, root: Path | None = None
) -> tuple[bool, int]:
    """Process ownership fixes.

    Args:
        all_items: List of paths to process.
        user: Expected owner username.
        group: Expected group name.
        dry_run: If True, only show what would be done.
        root: Root directory for relative display of paths in output.

    Returns:
        Tuple of (has_errors, change_count).
    """
    print(f"\nOwnership ({user}:{group}):")
    has_errors = False
    count = 0

    for item in all_items:
        if not item.exists():
            continue
        is_ok, _curr_user, _curr_group = check_ownership(item, user, group)
        if not is_ok:
            count += 1
            if not fix_ownership(item, user, group, dry_run, root=root):
                has_errors = True

    if not count:
        print("  All items have correct ownership")

    return has_errors, count


def process_directory(
    directory: Path,
    user: str,
    group: str,
    dry_run: bool,
) -> tuple[bool, int, int]:
    """Process a single directory and fix all issues.

    Args:
        directory: Directory to process.
        user: Expected owner username.
        group: Expected group name.
        dry_run: If True, only show what would be done.

    Returns:
        Tuple of (success, change_count, item_count). success is False if any
        errors occurred. item_count is the total number of files and directories
        scanned.
    """
    root = directory.parent

    # Get all items, deepest first (for renaming)
    items = get_items_depth_first(directory)
    all_items = [*items, directory]
    item_count = len(all_items)

    # Phase 1: Rename to lowercase
    name_errors, path_map = _process_filenames(all_items, dry_run, root=root)
    total_changes = len(path_map)

    # Re-scan or update paths after renames
    if not dry_run and path_map:
        new_directory = path_map.get(directory, directory)
        items = get_items_depth_first(new_directory)
        all_items = [*items, new_directory]
    elif path_map:
        all_items = _update_paths_for_dry_run(all_items, path_map)

    # Phase 2-4: Fix permissions and ownership
    file_perm_errors, file_perm_count = _process_file_permissions(all_items, dry_run, root=root)
    dir_perm_errors, dir_perm_count = _process_dir_permissions(all_items, dry_run, root=root)
    ownership_errors, ownership_count = _process_ownership(
        all_items, user, group, dry_run, root=root
    )
    total_changes += file_perm_count + dir_perm_count + ownership_count

    has_errors = name_errors or file_perm_errors or dir_perm_errors or ownership_errors
    return not has_errors, total_changes, item_count


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for prepare command.

    Adds all command-line arguments for the prepare tool to the provided parser.

    Args:
        parser: ArgumentParser instance to configure with prepare arguments.
    """
    parser.add_argument(
        "directories",
        nargs="+",
        help="One or more directories to prepare for archiving",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply changes to the filesystem (default: preview only)",
    )
    parser.add_argument(
        "-u",
        "--owner",
        default="storage",
        help="Expected owner username (default: storage)",
    )
    parser.add_argument(
        "-g",
        "--group",
        default="storage",
        help="Expected group name (default: storage)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute the prepare command with parsed arguments.

    Validates input directories and processes each one to fix permissions,
    ownership, and filenames.

    Args:
        args: Parsed command-line arguments containing:
            - directories: List of directory paths to process
            - dry_run: If True, only show what would be done
            - owner: Expected owner username
            - group: Expected group name

    Returns:
        Exit code: 0 on success, 1 if any errors occurred.
    """
    # Validate all directories first
    for directory in args.directories:
        validate_directory(directory)

    # Process each directory
    all_success = True
    total_changes = 0
    total_files = 0
    for directory in args.directories:
        path = Path(directory).resolve()
        success, changes, item_count = process_directory(path, args.owner, args.group, not args.fix)
        total_changes += changes
        total_files += item_count
        if not success:
            all_success = False

    verb = "applied" if args.fix else "detected"
    print(f"\n{total_changes} change(s) {verb} in {total_files} file(s).")
    if total_changes:
        if not args.fix:
            print("Dry-run: use --fix to apply changes.")
        else:
            print("Run 'photos index' to generate JSON metadata.")

    return os.EX_OK if all_success else 1
