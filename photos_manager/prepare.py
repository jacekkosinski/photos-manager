"""prepare - Prepare directories for archiving by fixing permissions and filenames.

This script checks and fixes:
- File permissions (should be 644)
- Directory permissions (should be 755)
- File/directory ownership (should be storage:storage by default)
- Filenames (should be lowercase with no spaces - spaces are converted to underscores)

Hidden files (starting with .) are skipped. Symbolic links are checked but not followed.

Usage:
    photos prepare /path/to/directory
    photos prepare /path/to/dir1 /path/to/dir2 --dry-run
    photos prepare /path/to/directory --user storage --group storage
"""

import argparse
import grp
import os
import pwd
import stat
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

# Conditional imports for EXIF support
try:
    import piexif
    from PIL import Image

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        HEIF_AVAILABLE = True
    except ImportError:
        HEIF_AVAILABLE = False
    EXIF_AVAILABLE = True
except ImportError:
    EXIF_AVAILABLE = False
    HEIF_AVAILABLE = False

# Expected permissions
FILE_PERMISSIONS = 0o644
DIR_PERMISSIONS = 0o755

# EXIF date field priority (first available wins)
EXIF_DATE_FIELDS = ["DateTimeOriginal", "CreateDate", "DateTimeDigitized", "ModifyDate"]

# Supported file extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".cr2", ".nef", ".arw", ".dng"}
HEIF_EXTENSIONS = {".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".m4v", ".3gp"}


def check_exif_libraries_available() -> None:
    """Check if EXIF libraries are installed.

    Raises:
        SystemExit: If EXIF libraries are not available with installation instructions.

    Examples:
        >>> check_exif_libraries_available()  # doctest: +SKIP
    """
    if not EXIF_AVAILABLE:
        raise SystemExit(
            "Error: EXIF libraries not installed.\n"
            "Install with: pip install photos-manager-cli[exif]"
        )


def get_file_type(path: Path) -> str | None:
    """Determine file type based on extension.

    Args:
        path: Path to the file.

    Returns:
        'image', 'heif', 'video', or None if unsupported.

    Examples:
        >>> get_file_type(Path("photo.jpg"))
        'image'
        >>> get_file_type(Path("photo.HEIC"))
        'heif'
        >>> get_file_type(Path("video.mp4"))
        'video'
        >>> get_file_type(Path("document.txt"))
    """
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in HEIF_EXTENSIONS:
        return "heif"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def parse_exif_date(date_str: str) -> datetime | None:
    """Parse EXIF date string to datetime object.

    EXIF dates are in format "YYYY:MM:DD HH:MM:SS" optionally with subseconds.

    Args:
        date_str: EXIF date string.

    Returns:
        datetime object or None if parsing fails.

    Examples:
        >>> parse_exif_date("2025:01:24 15:30:45")
        datetime.datetime(2025, 1, 24, 15, 30, 45)
        >>> parse_exif_date("invalid")
    """
    if not date_str:
        return None

    # Remove null bytes and strip whitespace
    date_str = date_str.replace("\x00", "").strip()

    if not date_str:
        return None

    try:
        # Try standard format first
        return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        pass

    # Try with subseconds
    try:
        # Some cameras add subseconds like "2025:01:24 15:30:45.123"
        if "." in date_str:
            base_date = date_str.split(".")[0]
            return datetime.strptime(base_date, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        pass

    return None


def extract_exif_date_from_image(path: Path) -> datetime | None:
    """Extract EXIF date from image file.

    Tries piexif first (for JPEG/TIFF), then falls back to Pillow (for PNG/HEIF).
    Searches for date fields in priority order.

    Args:
        path: Path to the image file.

    Returns:
        datetime object from EXIF data or None if not found.

    Examples:
        >>> extract_exif_date_from_image(Path("photo.jpg"))  # doctest: +SKIP
        datetime.datetime(2025, 1, 24, 15, 30, 45)
    """
    if not EXIF_AVAILABLE:
        return None

    # Try piexif first (JPEG/TIFF)
    try:
        exif_dict = piexif.load(str(path))
        # Check Exif IFD for standard date fields
        if "Exif" in exif_dict:
            for field_name in EXIF_DATE_FIELDS:
                # Map field names to piexif tags
                if field_name == "DateTimeOriginal":
                    tag = piexif.ExifIFD.DateTimeOriginal
                elif field_name == "CreateDate":
                    # CreateDate is sometimes in EXIF, sometimes not standard
                    continue
                elif field_name == "DateTimeDigitized":
                    tag = piexif.ExifIFD.DateTimeDigitized
                elif field_name == "ModifyDate":
                    # ModifyDate typically in 0th IFD as DateTime
                    continue
                else:
                    continue

                if tag in exif_dict["Exif"]:
                    date_bytes = exif_dict["Exif"][tag]
                    if isinstance(date_bytes, bytes):
                        date_str = date_bytes.decode("utf-8", errors="ignore")
                        parsed = parse_exif_date(date_str)
                        if parsed:
                            return parsed

        # Check 0th IFD for DateTime (ModifyDate)
        if "0th" in exif_dict and piexif.ImageIFD.DateTime in exif_dict["0th"]:
            date_bytes = exif_dict["0th"][piexif.ImageIFD.DateTime]
            if isinstance(date_bytes, bytes):
                date_str = date_bytes.decode("utf-8", errors="ignore")
                parsed = parse_exif_date(date_str)
                if parsed:
                    return parsed

    except (piexif.InvalidImageDataError, ValueError, KeyError):
        pass

    # Fall back to Pillow (PNG, HEIF)
    try:
        with Image.open(path) as img:
            exif_data = img.getexif()
            if exif_data:
                # Try to get DateTimeOriginal (tag 36867)
                for tag_id in [36867, 36868, 306]:  # DateTimeOriginal, DateTimeDigitized, DateTime
                    if tag_id in exif_data:
                        date_str = exif_data[tag_id]
                        if isinstance(date_str, str):
                            parsed = parse_exif_date(date_str)
                            if parsed:
                                return parsed
    except (OSError, ValueError, KeyError):
        pass

    return None


def extract_date_from_video(path: Path) -> datetime | None:  # noqa: ARG001
    """Extract creation date from video file metadata.

    This is a stub implementation. Video metadata extraction requires
    additional libraries like hachoir or ffmpeg.

    Args:
        path: Path to the video file (currently unused in stub).

    Returns:
        datetime object from video metadata or None (currently always None).

    Examples:
        >>> extract_date_from_video(Path("video.mp4"))  # doctest: +SKIP
    """
    # TODO: Add hachoir support if needed
    # from hachoir.parser import createParser
    # from hachoir.metadata import extractMetadata
    return None


def set_file_mtime_from_exif(path: Path, dry_run: bool) -> bool:
    """Set file modification time from EXIF metadata.

    Extracts EXIF date from the file and updates the file's mtime if different.
    Uses 1 second tolerance for comparison.

    Args:
        path: Path to the file.
        dry_run: If True, only print what would be done.

    Returns:
        True if mtime was updated (or would be in dry-run), False otherwise.

    Examples:
        >>> set_file_mtime_from_exif(Path("photo.jpg"), dry_run=True)  # doctest: +SKIP
        True
    """
    file_type = get_file_type(path)
    if not file_type:
        return False

    # Extract date based on file type
    exif_date = None
    if file_type in ("image", "heif"):
        exif_date = extract_exif_date_from_image(path)
    elif file_type == "video":
        exif_date = extract_date_from_video(path)

    if not exif_date:
        return False

    # Get current mtime
    try:
        current_mtime = path.stat().st_mtime
        exif_timestamp = exif_date.timestamp()

        # Compare with 1 second tolerance
        if abs(current_mtime - exif_timestamp) < 1.0:
            return False

        # Update mtime
        if dry_run:
            print(f"  [FIX] {path}: mtime -> {exif_date.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            os.utime(path, (exif_timestamp, exif_timestamp))
            print(f"  [FIXED] {path}: mtime set to {exif_date.strftime('%Y-%m-%d %H:%M:%S')}")
        return True

    except OSError as e:
        print(f"  Warning: {path}: cannot update mtime: {e}", file=sys.stderr)
        return False


def _process_exif_timestamps(all_items: list[Path], dry_run: bool) -> bool:
    """Process EXIF timestamp updates for all files.

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.

    Returns:
        True if any errors occurred.
    """
    print("\nEXIF timestamps:")
    has_errors = False
    has_fixes = False
    processed_count = 0

    for item in all_items:
        if not item.exists() or item.is_symlink() or not item.is_file():
            continue

        # Only process files with supported extensions
        if get_file_type(item):
            processed_count += 1
            try:
                if set_file_mtime_from_exif(item, dry_run):
                    has_fixes = True
            except Exception as e:
                print(f"  Error: {item}: {e}", file=sys.stderr)
                has_errors = True

    if not has_fixes and processed_count > 0:
        print("  [OK] All files already have correct EXIF timestamps")
    elif processed_count == 0:
        print("  [OK] No supported media files found")

    return has_errors


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


def scan_directory(directory: Path) -> Iterator[Path]:
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
        >>> list(scan_directory(Path("/tmp/photos")))
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
                yield from scan_directory(item)
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
    items = list(scan_directory(directory))
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
    try:
        current_user = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        current_user = str(st.st_uid)
    try:
        current_group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        current_group = str(st.st_gid)

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


def fix_file_permissions(path: Path, dry_run: bool) -> bool:
    """Fix file permissions to 644.

    Args:
        path: Path to the file.
        dry_run: If True, only print what would be done.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        if dry_run:
            print(f"  [FIX] {path}: {oct(stat.S_IMODE(path.stat().st_mode))} -> 0o644")
        else:
            path.chmod(FILE_PERMISSIONS)
            print(f"  [FIXED] {path}: permissions set to 0o644")
        return True
    except OSError as e:
        print(f"  Error: {path}: cannot change permissions: {e}", file=sys.stderr)
        return False


def fix_dir_permissions(path: Path, dry_run: bool) -> bool:
    """Fix directory permissions to 755.

    Args:
        path: Path to the directory.
        dry_run: If True, only print what would be done.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        if dry_run:
            print(f"  [FIX] {path}: {oct(stat.S_IMODE(path.stat().st_mode))} -> 0o755")
        else:
            path.chmod(DIR_PERMISSIONS)
            print(f"  [FIXED] {path}: permissions set to 0o755")
        return True
    except OSError as e:
        print(f"  Error: {path}: cannot change permissions: {e}", file=sys.stderr)
        return False


def fix_ownership(path: Path, user: str, group: str, dry_run: bool) -> bool:
    """Fix file/directory ownership.

    Args:
        path: Path to fix.
        user: Target username.
        group: Target group name.
        dry_run: If True, only print what would be done.

    Returns:
        True if successful or dry-run, False on error.
    """
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError as e:
        print(f"  Error: {path}: user or group not found: {e}", file=sys.stderr)
        return False

    st = path.stat()
    try:
        current_user = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        current_user = str(st.st_uid)
    try:
        current_group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        current_group = str(st.st_gid)

    try:
        if dry_run:
            print(f"  [FIX] {path}: {current_user}:{current_group} -> {user}:{group}")
        else:
            os.chown(path, uid, gid)
            print(f"  [FIXED] {path}: ownership set to {user}:{group}")
        return True
    except OSError as e:
        print(f"  Error: {path}: cannot change ownership: {e}", file=sys.stderr)
        return False


def rename_to_normalized(path: Path, dry_run: bool) -> tuple[bool, Path]:
    """Rename file/directory to normalized form (lowercase, no spaces).

    Converts uppercase letters to lowercase and spaces to underscores.
    If a conflict exists, a numeric suffix is added to the name.

    Args:
        path: Path to rename.
        dry_run: If True, only print what would be done.

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
                print(f"  [FIX] {path} -> {new_path.name} (conflict with {expected_normalized})")
            else:
                print(f"  [FIX] {path} -> {new_path.name}")
            return True, new_path
        else:
            path.rename(new_path)
            if has_conflict:
                print(f"  [FIXED] {path} -> {new_path.name} (conflict with {expected_normalized})")
            else:
                print(f"  [FIXED] {path} -> {new_path.name}")
            return True, new_path
    except OSError as e:
        print(f"  Error: {path}: cannot rename: {e}", file=sys.stderr)
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
        if item != old and str(item).startswith(str(old) + "/"):
            return Path(str(item).replace(str(old), str(new), 1))
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


def _process_filenames(all_items: list[Path], dry_run: bool) -> tuple[bool, dict[Path, Path]]:
    """Process filename fixes (normalize: lowercase, no spaces).

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.

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
            success, new_path = rename_to_normalized(current_path, dry_run)
            if success and new_path != current_path:
                path_map[current_path] = new_path
            elif not success:
                has_errors = True

    if not has_fixes:
        print("  [OK] All names are normalized")

    return has_errors, path_map


def _process_file_permissions(all_items: list[Path], dry_run: bool) -> bool:
    """Process file permission fixes.

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.

    Returns:
        True if any errors occurred.
    """
    print("\nFile permissions (644):")
    has_errors = False
    has_fixes = False

    for item in all_items:
        if not item.exists() or item.is_symlink() or not item.is_file():
            continue
        is_ok, _current_perms = check_file_permissions(item)
        if not is_ok:
            has_fixes = True
            if not fix_file_permissions(item, dry_run):
                has_errors = True

    if not has_fixes:
        print("  [OK] All files have correct permissions")

    return has_errors


def _process_dir_permissions(all_items: list[Path], dry_run: bool) -> bool:
    """Process directory permission fixes.

    Args:
        all_items: List of paths to process.
        dry_run: If True, only show what would be done.

    Returns:
        True if any errors occurred.
    """
    print("\nDirectory permissions (755):")
    has_errors = False
    has_fixes = False

    for item in all_items:
        if not item.exists() or item.is_symlink() or not item.is_dir():
            continue
        is_ok, _current_perms = check_dir_permissions(item)
        if not is_ok:
            has_fixes = True
            if not fix_dir_permissions(item, dry_run):
                has_errors = True

    if not has_fixes:
        print("  [OK] All directories have correct permissions")

    return has_errors


def _process_ownership(all_items: list[Path], user: str, group: str, dry_run: bool) -> bool:
    """Process ownership fixes.

    Args:
        all_items: List of paths to process.
        user: Expected owner username.
        group: Expected group name.
        dry_run: If True, only show what would be done.

    Returns:
        True if any errors occurred.
    """
    print(f"\nOwnership ({user}:{group}):")
    has_errors = False
    has_fixes = False

    for item in all_items:
        if not item.exists():
            continue
        is_ok, _curr_user, _curr_group = check_ownership(item, user, group)
        if not is_ok:
            has_fixes = True
            if not fix_ownership(item, user, group, dry_run):
                has_errors = True

    if not has_fixes:
        print("  [OK] All items have correct ownership")

    return has_errors


def process_directory(
    directory: Path,
    user: str,
    group: str,
    dry_run: bool,
    use_exif: bool = False,
) -> bool:
    """Process a single directory and fix all issues.

    Args:
        directory: Directory to process.
        user: Expected owner username.
        group: Expected group name.
        dry_run: If True, only show what would be done.
        use_exif: If True, set file mtimes from EXIF metadata.

    Returns:
        True if processing completed without errors, False otherwise.
    """
    print(f"\nProcessing: {directory}")
    print("-" * 60)

    # Get all items, deepest first (for renaming)
    items = get_items_depth_first(directory)
    all_items = [*items, directory]

    # Phase 1: Rename to lowercase
    name_errors, path_map = _process_filenames(all_items, dry_run)

    # Re-scan or update paths after renames
    if not dry_run and path_map:
        items = get_items_depth_first(directory)
        all_items = [*items, directory]
    elif path_map:
        all_items = _update_paths_for_dry_run(all_items, path_map)

    # Phase 2: EXIF timestamps
    exif_errors = False
    if use_exif:
        exif_errors = _process_exif_timestamps(all_items, dry_run)

    # Phase 3-5: Fix permissions and ownership
    file_perm_errors = _process_file_permissions(all_items, dry_run)
    dir_perm_errors = _process_dir_permissions(all_items, dry_run)
    ownership_errors = _process_ownership(all_items, user, group, dry_run)

    has_errors = (
        name_errors or exif_errors or file_perm_errors or dir_perm_errors or ownership_errors
    )
    return not has_errors


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
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--user",
        default="storage",
        help="Expected owner username (default: storage)",
    )
    parser.add_argument(
        "--group",
        default="storage",
        help="Expected group name (default: storage)",
    )
    parser.add_argument(
        "--use-exif",
        action="store_true",
        help="Set file modification times from EXIF metadata (requires EXIF libraries)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute the prepare command with parsed arguments.

    Validates input directories and processes each one to fix permissions,
    ownership, and filenames.

    Args:
        args: Parsed command-line arguments containing:
            - directories: List of directory paths to process
            - dry_run: If True, only show what would be done
            - user: Expected owner username
            - group: Expected group name
            - use_exif: If True, set file mtimes from EXIF metadata

    Returns:
        Exit code: 0 on success, 1 if any errors occurred.
    """
    # Check EXIF libraries if --use-exif flag is used
    if args.use_exif:
        check_exif_libraries_available()

    # Validate all directories first
    for directory in args.directories:
        path = Path(directory)
        if not path.exists():
            raise SystemExit(f"Error: Directory '{directory}' does not exist")
        if not path.is_dir():
            raise SystemExit(f"Error: '{directory}' is not a directory")

    # Process each directory
    all_success = True
    for directory in args.directories:
        path = Path(directory).resolve()
        success = process_directory(path, args.user, args.group, args.dry_run, args.use_exif)
        if not success:
            all_success = False

    if args.dry_run:
        print("\nMode: DRY-RUN (use without -n to apply fixes)")

    return os.EX_OK if all_success else 1
