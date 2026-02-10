"""Tests for prepare module."""

import argparse
import grp  # noqa: F401
import os
import pwd
import stat
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from photos_manager.prepare import (
    DIR_PERMISSIONS,
    FILE_PERMISSIONS,
    check_dir_permissions,
    check_exif_libraries_available,
    check_file_permissions,
    check_ownership,
    extract_date_from_video,
    extract_exif_date_from_image,
    fix_dir_permissions,
    fix_file_permissions,
    fix_ownership,
    get_file_type,
    get_items_depth_first,
    get_unique_normalized_path,
    has_spaces,
    has_uppercase,
    is_hidden,
    needs_normalization,
    parse_exif_date,
    process_directory,
    rename_to_normalized,
    run,
    scan_directory,
    set_file_mtime_from_exif,
)

# Try to import EXIF libraries for integration tests
try:
    import piexif
    from PIL import Image

    EXIF_LIBS_INSTALLED = True
except ImportError:
    EXIF_LIBS_INSTALLED = False


class TestIsHidden:
    """Tests for is_hidden function."""

    def test_hidden_file_returns_true(self, tmp_path: Path) -> None:
        """Test that files starting with dot are hidden."""
        hidden = tmp_path / ".hidden"
        hidden.touch()
        assert is_hidden(hidden) is True

    def test_visible_file_returns_false(self, tmp_path: Path) -> None:
        """Test that files not starting with dot are not hidden."""
        visible = tmp_path / "visible.txt"
        visible.touch()
        assert is_hidden(visible) is False

    def test_hidden_directory_returns_true(self, tmp_path: Path) -> None:
        """Test that directories starting with dot are hidden."""
        hidden_dir = tmp_path / ".hidden_dir"
        hidden_dir.mkdir()
        assert is_hidden(hidden_dir) is True


class TestScanDirectory:
    """Tests for scan_directory function."""

    def test_scans_files_and_directories(self, tmp_path: Path) -> None:
        """Test that scan returns all files and directories."""
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.txt").touch()

        items = list(scan_directory(tmp_path))

        assert len(items) == 3
        paths = [str(p) for p in items]
        assert str(tmp_path / "file.txt") in paths
        assert str(tmp_path / "subdir") in paths
        assert str(tmp_path / "subdir" / "nested.txt") in paths

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        """Test that hidden files are skipped."""
        (tmp_path / ".hidden").touch()
        (tmp_path / "visible.txt").touch()

        items = list(scan_directory(tmp_path))

        assert len(items) == 1
        assert items[0].name == "visible.txt"

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        """Test that hidden directories and their contents are skipped."""
        (tmp_path / ".hidden_dir").mkdir()
        (tmp_path / ".hidden_dir" / "file.txt").touch()
        (tmp_path / "visible_dir").mkdir()

        items = list(scan_directory(tmp_path))

        assert len(items) == 1
        assert items[0].name == "visible_dir"

    def test_yields_symlinks(self, tmp_path: Path) -> None:
        """Test that symlinks are yielded but not followed."""
        target = tmp_path / "target.txt"
        target.touch()
        link = tmp_path / "link.txt"
        link.symlink_to(target)

        items = list(scan_directory(tmp_path))

        assert len(items) == 2
        link_item = next(i for i in items if i.name == "link.txt")
        assert link_item.is_symlink()


class TestGetItemsDepthFirst:
    """Tests for get_items_depth_first function."""

    def test_returns_deepest_first(self, tmp_path: Path) -> None:
        """Test that deepest items come first."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        (tmp_path / "a" / "b" / "c.txt").touch()

        items = get_items_depth_first(tmp_path)

        # Deepest item (c.txt) should be first
        assert items[0].name == "c.txt"
        # Root-level directory should be last
        assert items[-1].name == "a"


class TestCheckFilePermissions:
    """Tests for check_file_permissions function."""

    def test_correct_permissions_return_true(self, tmp_path: Path) -> None:
        """Test that files with 644 permissions return True."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(FILE_PERMISSIONS)

        is_ok, current = check_file_permissions(test_file)

        assert is_ok is True
        assert current == FILE_PERMISSIONS

    def test_incorrect_permissions_return_false(self, tmp_path: Path) -> None:
        """Test that files with wrong permissions return False."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        is_ok, current = check_file_permissions(test_file)

        assert is_ok is False
        assert current == 0o777


class TestCheckDirPermissions:
    """Tests for check_dir_permissions function."""

    def test_correct_permissions_return_true(self, tmp_path: Path) -> None:
        """Test that directories with 755 permissions return True."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()
        test_dir.chmod(DIR_PERMISSIONS)

        is_ok, current = check_dir_permissions(test_dir)

        assert is_ok is True
        assert current == DIR_PERMISSIONS

    def test_incorrect_permissions_return_false(self, tmp_path: Path) -> None:
        """Test that directories with wrong permissions return False."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()
        test_dir.chmod(0o700)

        is_ok, current = check_dir_permissions(test_dir)

        assert is_ok is False
        assert current == 0o700


class TestCheckOwnership:
    """Tests for check_ownership function."""

    def test_correct_ownership_returns_true(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that files with correct ownership return True."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        is_ok, user, group = check_ownership(test_file, current_user, current_group)

        assert is_ok is True
        assert user == current_user
        assert group == current_group

    def test_wrong_user_returns_false(self, tmp_path: Path) -> None:
        """Test that files with wrong user return False."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        is_ok, _user, _group = check_ownership(test_file, "nonexistent_user", "nonexistent_group")

        assert is_ok is False


class TestHasUppercase:
    """Tests for has_uppercase function."""

    def test_lowercase_returns_false(self) -> None:
        """Test that lowercase string returns False."""
        assert has_uppercase("lowercase.txt") is False

    def test_uppercase_returns_true(self) -> None:
        """Test that string with uppercase returns True."""
        assert has_uppercase("UpperCase.txt") is True

    def test_mixed_case_returns_true(self) -> None:
        """Test that mixed case string returns True."""
        assert has_uppercase("IMG_001.JPG") is True

    def test_numbers_only_returns_false(self) -> None:
        """Test that numbers don't count as uppercase."""
        assert has_uppercase("12345.txt") is False


class TestHasSpaces:
    """Tests for has_spaces function."""

    def test_with_spaces_returns_true(self) -> None:
        """Test that string with spaces returns True."""
        assert has_spaces("my file.jpg") is True

    def test_without_spaces_returns_false(self) -> None:
        """Test that string without spaces returns False."""
        assert has_spaces("my_file.jpg") is False

    def test_multiple_spaces_returns_true(self) -> None:
        """Test that string with multiple spaces returns True."""
        assert has_spaces("my  file  name.jpg") is True


class TestNeedsNormalization:
    """Tests for needs_normalization function."""

    def test_uppercase_returns_true(self) -> None:
        """Test that uppercase triggers normalization."""
        assert needs_normalization("FILE.JPG") is True

    def test_spaces_returns_true(self) -> None:
        """Test that spaces trigger normalization."""
        assert needs_normalization("my file.jpg") is True

    def test_both_returns_true(self) -> None:
        """Test that both uppercase and spaces trigger normalization."""
        assert needs_normalization("My File.JPG") is True

    def test_normalized_returns_false(self) -> None:
        """Test that normalized name returns False."""
        assert needs_normalization("my_file.jpg") is False


class TestGetUniqueNormalizedPath:
    """Tests for get_unique_normalized_path function."""

    def test_returns_lowercase_path(self, tmp_path: Path) -> None:
        """Test that uppercase name is converted to lowercase."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        result = get_unique_normalized_path(test_file)

        assert result.name == "test.txt"

    def test_converts_spaces_to_underscores(self, tmp_path: Path) -> None:
        """Test that spaces are converted to underscores."""
        test_file = tmp_path / "my file.txt"
        test_file.touch()

        result = get_unique_normalized_path(test_file)

        assert result.name == "my_file.txt"

    def test_handles_both_uppercase_and_spaces(self, tmp_path: Path) -> None:
        """Test that both uppercase and spaces are normalized."""
        test_file = tmp_path / "My File.TXT"
        test_file.touch()

        result = get_unique_normalized_path(test_file)

        assert result.name == "my_file.txt"

    def test_adds_suffix_on_conflict(self, tmp_path: Path) -> None:
        """Test that numeric suffix is added when conflict exists."""
        # Create existing lowercase file
        existing = tmp_path / "test.txt"
        existing.touch()

        # Create uppercase file
        uppercase = tmp_path / "TEST.TXT"
        uppercase.touch()

        result = get_unique_normalized_path(uppercase)

        assert result.name == "test_1.txt"

    def test_increments_suffix_on_multiple_conflicts(self, tmp_path: Path) -> None:
        """Test that suffix increments for multiple conflicts."""
        # Create existing files
        (tmp_path / "test.txt").touch()
        (tmp_path / "test_1.txt").touch()

        # Create uppercase file
        uppercase = tmp_path / "TEST.TXT"
        uppercase.touch()

        result = get_unique_normalized_path(uppercase)

        assert result.name == "test_2.txt"


class TestFixFilePermissions:
    """Tests for fix_file_permissions function."""

    def test_fixes_permissions(self, tmp_path: Path) -> None:
        """Test that permissions are fixed to 644."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        result = fix_file_permissions(test_file, dry_run=False)

        assert result is True
        assert stat.S_IMODE(test_file.stat().st_mode) == FILE_PERMISSIONS

    def test_dry_run_does_not_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dry run does not modify permissions."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        result = fix_file_permissions(test_file, dry_run=True)

        assert result is True
        assert stat.S_IMODE(test_file.stat().st_mode) == 0o777
        captured = capsys.readouterr()
        assert "[FIX]" in captured.out


class TestFixDirPermissions:
    """Tests for fix_dir_permissions function."""

    def test_fixes_permissions(self, tmp_path: Path) -> None:
        """Test that directory permissions are fixed to 755."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()
        test_dir.chmod(0o700)

        result = fix_dir_permissions(test_dir, dry_run=False)

        assert result is True
        assert stat.S_IMODE(test_dir.stat().st_mode) == DIR_PERMISSIONS

    def test_dry_run_does_not_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dry run does not modify permissions."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()
        test_dir.chmod(0o700)

        result = fix_dir_permissions(test_dir, dry_run=True)

        assert result is True
        assert stat.S_IMODE(test_dir.stat().st_mode) == 0o700
        captured = capsys.readouterr()
        assert "[FIX]" in captured.out


class TestRenameToNormalized:
    """Tests for rename_to_normalized function."""

    def test_renames_uppercase_file(self, tmp_path: Path) -> None:
        """Test that uppercase file is renamed to lowercase."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        success, new_path = rename_to_normalized(test_file, dry_run=False)

        assert success is True
        assert new_path.name == "test.txt"
        assert new_path.exists()
        assert not test_file.exists()

    def test_converts_spaces_to_underscores(self, tmp_path: Path) -> None:
        """Test that spaces are converted to underscores."""
        test_file = tmp_path / "my file.txt"
        test_file.touch()

        success, new_path = rename_to_normalized(test_file, dry_run=False)

        assert success is True
        assert new_path.name == "my_file.txt"
        assert new_path.exists()
        assert not test_file.exists()

    def test_handles_both_spaces_and_uppercase(self, tmp_path: Path) -> None:
        """Test that both uppercase and spaces are normalized."""
        test_file = tmp_path / "My File.TXT"
        test_file.touch()

        success, new_path = rename_to_normalized(test_file, dry_run=False)

        assert success is True
        assert new_path.name == "my_file.txt"
        assert new_path.exists()
        assert not test_file.exists()

    def test_already_normalized_unchanged(self, tmp_path: Path) -> None:
        """Test that normalized file is not changed."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        success, new_path = rename_to_normalized(test_file, dry_run=False)

        assert success is True
        assert new_path == test_file

    def test_dry_run_does_not_rename(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dry run does not rename file."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        success, _new_path = rename_to_normalized(test_file, dry_run=True)

        assert success is True
        assert test_file.exists()  # Original still exists
        captured = capsys.readouterr()
        assert "[FIX]" in captured.out

    def test_adds_suffix_on_conflict(self, tmp_path: Path) -> None:
        """Test that suffix is added when normalized name exists."""
        existing = tmp_path / "test.txt"
        existing.touch()

        uppercase = tmp_path / "TEST.TXT"
        uppercase.touch()

        success, new_path = rename_to_normalized(uppercase, dry_run=False)

        assert success is True
        assert new_path.name == "test_1.txt"
        assert existing.exists()
        assert new_path.exists()


class TestProcessDirectory:
    """Tests for process_directory function."""

    def test_returns_success_on_no_errors(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that processing returns True when no errors occur."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(FILE_PERMISSIONS)

        current_user, current_group = current_user_and_group

        result = process_directory(tmp_path, current_user, current_group, dry_run=True)

        assert result is True

    def test_fixes_file_permissions(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that file permissions are fixed."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        current_user, current_group = current_user_and_group

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert stat.S_IMODE(test_file.stat().st_mode) == FILE_PERMISSIONS

    def test_fixes_directory_permissions(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that directory permissions are fixed."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        subdir.chmod(0o700)

        current_user, current_group = current_user_and_group

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert stat.S_IMODE(subdir.stat().st_mode) == DIR_PERMISSIONS

    def test_renames_uppercase_files(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that uppercase files are renamed."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user, current_group = current_user_and_group

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert (tmp_path / "test.txt").exists()
        assert not test_file.exists()

    def test_converts_spaces_to_underscores(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that spaces in filenames are converted to underscores."""
        test_file = tmp_path / "my file.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert (tmp_path / "my_file.txt").exists()
        assert not test_file.exists()


class TestErrorHandling:
    """Tests for error handling in prepare module."""

    def test_scan_directory_permission_error(self, tmp_path: Path) -> None:
        """Test that PermissionError raises SystemExit."""
        with (
            patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")),
            pytest.raises(SystemExit, match="Cannot access directory"),
        ):
            list(scan_directory(tmp_path))

    def test_check_ownership_unknown_uid(self, tmp_path: Path) -> None:
        """Test check_ownership handles unknown uid gracefully."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        with patch("photos_manager.prepare.pwd.getpwuid", side_effect=KeyError("uid")):
            is_ok, user, _group = check_ownership(test_file, "someuser", "somegroup")

        # Should return numeric uid as string
        assert is_ok is False
        assert user.isdigit()

    def test_check_ownership_unknown_gid(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test check_ownership handles unknown gid gracefully."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user, _ = current_user_and_group

        with patch("photos_manager.prepare.grp.getgrgid", side_effect=KeyError("gid")):
            is_ok, _user, group = check_ownership(test_file, current_user, "somegroup")

        # Should return numeric gid as string
        assert is_ok is False
        assert group.isdigit()

    def test_fix_file_permissions_oserror(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test fix_file_permissions handles OSError."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
            result = fix_file_permissions(test_file, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_dir_permissions_oserror(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test fix_dir_permissions handles OSError."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()

        with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
            result = fix_dir_permissions(test_dir, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_ownership_nonexistent_user(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test fix_ownership with nonexistent user."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        result = fix_ownership(test_file, "nonexistent_user_12345", "staff", dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "not found" in captured.err

    def test_fix_ownership_nonexistent_group(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test fix_ownership with nonexistent group."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user, _ = current_user_and_group

        result = fix_ownership(test_file, current_user, "nonexistent_group_12345", dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "not found" in captured.err

    def test_fix_ownership_chown_oserror(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test fix_ownership handles chown OSError."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        with patch(
            "photos_manager.prepare.os.chown", side_effect=OSError("Operation not permitted")
        ):
            result = fix_ownership(test_file, current_user, current_group, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_ownership_unknown_current_uid(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test fix_ownership handles unknown current uid in dry-run."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        # Mock getpwuid to fail for the second call (getting current owner)
        call_count = [0]
        original_getpwuid = pwd.getpwuid

        def mock_getpwuid(uid: int) -> pwd.struct_passwd:
            call_count[0] += 1
            if call_count[0] > 1:  # First call is for target user lookup
                raise KeyError("uid")
            return original_getpwuid(uid)

        with (
            patch("photos_manager.prepare.pwd.getpwuid", side_effect=mock_getpwuid),
            patch("photos_manager.prepare.pwd.getpwnam") as mock_getpwnam,
        ):
            mock_getpwnam.return_value = pwd.getpwnam(current_user)
            result = fix_ownership(test_file, current_user, current_group, dry_run=True)

        assert result is True
        captured = capsys.readouterr()
        assert "[FIX]" in captured.out

    def test_rename_to_normalized_oserror(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test rename_to_normalized handles OSError."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        with patch.object(Path, "rename", side_effect=OSError("Cannot rename")):
            success, new_path = rename_to_normalized(test_file, dry_run=False)

        assert success is False
        assert new_path == test_file
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_get_unique_normalized_path_resolve_oserror(self, tmp_path: Path) -> None:
        """Test get_unique_normalized_path handles resolve OSError."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        # Create lowercase version to trigger the resolve check
        lowercase = tmp_path / "test.txt"
        lowercase.touch()

        with patch.object(Path, "resolve", side_effect=OSError("Cannot resolve")):
            result = get_unique_normalized_path(test_file)

        # Should fall through and add suffix
        assert result.name == "test_1.txt"

    def test_process_directory_returns_false_on_errors(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test process_directory returns False when errors occur."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user, current_group = current_user_and_group

        with patch.object(Path, "rename", side_effect=OSError("Cannot rename")):
            result = process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert result is False


class TestExifLibraryCheck:
    """Tests for EXIF library availability checks."""

    def test_check_raises_error_when_not_available(self) -> None:
        """Test that check raises SystemExit when EXIF libraries not available."""
        with (
            patch("photos_manager.prepare.EXIF_AVAILABLE", False),
            pytest.raises(SystemExit, match="EXIF libraries not installed"),
        ):
            check_exif_libraries_available()

    def test_check_succeeds_when_available(self) -> None:
        """Test that check succeeds when EXIF libraries are available."""
        with patch("photos_manager.prepare.EXIF_AVAILABLE", True):
            check_exif_libraries_available()  # Should not raise


class TestFileTypeDetection:
    """Tests for get_file_type function."""

    def test_detects_jpeg_as_image(self) -> None:
        """Test that JPEG files are detected as image."""
        assert get_file_type(Path("photo.jpg")) == "image"
        assert get_file_type(Path("photo.jpeg")) == "image"
        assert get_file_type(Path("PHOTO.JPG")) == "image"

    def test_detects_png_as_image(self) -> None:
        """Test that PNG files are detected as image."""
        assert get_file_type(Path("photo.png")) == "image"

    def test_detects_tiff_as_image(self) -> None:
        """Test that TIFF files are detected as image."""
        assert get_file_type(Path("photo.tiff")) == "image"
        assert get_file_type(Path("photo.tif")) == "image"

    def test_detects_raw_as_image(self) -> None:
        """Test that RAW files are detected as image."""
        assert get_file_type(Path("photo.cr2")) == "image"
        assert get_file_type(Path("photo.nef")) == "image"
        assert get_file_type(Path("photo.arw")) == "image"
        assert get_file_type(Path("photo.dng")) == "image"

    def test_detects_heic_as_heif(self) -> None:
        """Test that HEIC/HEIF files are detected as heif."""
        assert get_file_type(Path("photo.heic")) == "heif"
        assert get_file_type(Path("photo.heif")) == "heif"
        assert get_file_type(Path("PHOTO.HEIC")) == "heif"

    def test_detects_mp4_as_video(self) -> None:
        """Test that MP4 files are detected as video."""
        assert get_file_type(Path("video.mp4")) == "video"
        assert get_file_type(Path("video.m4v")) == "video"

    def test_detects_mov_as_video(self) -> None:
        """Test that MOV files are detected as video."""
        assert get_file_type(Path("video.mov")) == "video"
        assert get_file_type(Path("VIDEO.MOV")) == "video"

    def test_detects_avi_as_video(self) -> None:
        """Test that AVI files are detected as video."""
        assert get_file_type(Path("video.avi")) == "video"
        assert get_file_type(Path("video.3gp")) == "video"

    def test_returns_none_for_unsupported(self) -> None:
        """Test that unsupported file types return None."""
        assert get_file_type(Path("document.txt")) is None
        assert get_file_type(Path("archive.zip")) is None
        assert get_file_type(Path("data.json")) is None

    def test_case_insensitive_extension(self) -> None:
        """Test that file type detection is case insensitive."""
        assert get_file_type(Path("PHOTO.JPG")) == "image"
        assert get_file_type(Path("Photo.Jpeg")) == "image"
        assert get_file_type(Path("VIDEO.MP4")) == "video"


class TestExifDateParsing:
    """Tests for parse_exif_date function."""

    def test_parses_standard_format(self) -> None:
        """Test parsing standard EXIF date format."""
        result = parse_exif_date("2025:01:24 15:30:45")
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    def test_parses_with_subseconds(self) -> None:
        """Test parsing EXIF date with subseconds."""
        result = parse_exif_date("2025:01:24 15:30:45.123")
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    def test_handles_invalid_format(self) -> None:
        """Test that invalid format returns None."""
        assert parse_exif_date("invalid") is None
        assert parse_exif_date("2025-01-24 15:30:45") is None  # Wrong separator

    def test_handles_empty_string(self) -> None:
        """Test that empty string returns None."""
        assert parse_exif_date("") is None

    def test_handles_null_bytes(self) -> None:
        """Test that null bytes are handled."""
        result = parse_exif_date("2025:01:24 15:30:45\x00")
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    def test_handles_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        result = parse_exif_date("  2025:01:24 15:30:45  ")
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    def test_handles_only_null_bytes(self) -> None:
        """Test that string with only null bytes returns None."""
        assert parse_exif_date("\x00\x00") is None


class TestExifDateExtraction:
    """Tests for extract_exif_date_from_image function."""

    def test_returns_none_when_exif_not_available(self) -> None:
        """Test that function returns None when EXIF libraries not available."""
        with patch("photos_manager.prepare.EXIF_AVAILABLE", False):
            result = extract_exif_date_from_image(Path("photo.jpg"))
            assert result is None

    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_extracts_datetime_original_with_piexif(self, tmp_path: Path) -> None:
        """Test extracting DateTimeOriginal using piexif."""
        test_file = tmp_path / "test.jpg"
        img = Image.new("RGB", (100, 100), color="red")

        exif_dict = {
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2025:01:24 15:30:45",
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(test_file, exif=exif_bytes)

        result = extract_exif_date_from_image(test_file)
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_extracts_datetime_digitized_with_piexif(self, tmp_path: Path) -> None:
        """Test extracting DateTimeDigitized using piexif."""
        test_file = tmp_path / "test.jpg"
        img = Image.new("RGB", (100, 100), color="red")

        exif_dict = {
            "Exif": {
                piexif.ExifIFD.DateTimeDigitized: b"2025:01:24 16:00:00",
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(test_file, exif=exif_bytes)

        result = extract_exif_date_from_image(test_file)
        assert result == datetime(2025, 1, 24, 16, 0, 0)

    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_prefers_datetime_original_over_digitized(self, tmp_path: Path) -> None:
        """Test that DateTimeOriginal takes priority over DateTimeDigitized."""
        test_file = tmp_path / "test.jpg"
        img = Image.new("RGB", (100, 100), color="red")

        exif_dict = {
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2025:01:24 15:30:45",
                piexif.ExifIFD.DateTimeDigitized: b"2025:01:24 16:00:00",
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(test_file, exif=exif_bytes)

        result = extract_exif_date_from_image(test_file)
        assert result == datetime(2025, 1, 24, 15, 30, 45)

    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_extracts_datetime_from_0th_ifd(self, tmp_path: Path) -> None:
        """Test extracting DateTime from 0th IFD."""
        test_file = tmp_path / "test.jpg"
        img = Image.new("RGB", (100, 100), color="red")

        exif_dict = {
            "0th": {
                piexif.ImageIFD.DateTime: b"2025:01:24 17:00:00",
            }
        }
        exif_bytes = piexif.dump(exif_dict)
        img.save(test_file, exif=exif_bytes)

        result = extract_exif_date_from_image(test_file)
        assert result == datetime(2025, 1, 24, 17, 0, 0)

    def test_returns_none_for_no_exif(self, tmp_path: Path) -> None:
        """Test that files without EXIF return None."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("no exif here")

        result = extract_exif_date_from_image(test_file)
        assert result is None

    def test_handles_corrupted_exif(self, tmp_path: Path) -> None:
        """Test that corrupted EXIF data is handled gracefully."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Invalid JPEG

        result = extract_exif_date_from_image(test_file)
        assert result is None

    def test_fallback_to_pillow(self, tmp_path: Path) -> None:
        """Test fallback to Pillow when piexif fails."""
        test_file = tmp_path / "test.jpg"
        test_file.touch()

        # Mock piexif.load to fail
        if EXIF_LIBS_INSTALLED:
            with patch("piexif.load", side_effect=Exception("piexif failed")):
                # Should not crash, returns None if Pillow also can't read EXIF
                result = extract_exif_date_from_image(test_file)
                assert result is None
        else:
            # If EXIF libs not installed, just verify it returns None
            result = extract_exif_date_from_image(test_file)
            assert result is None


class TestExtractDateFromVideo:
    """Tests for extract_date_from_video function."""

    def test_returns_none_stub_implementation(self, tmp_path: Path) -> None:
        """Test that stub implementation returns None."""
        test_file = tmp_path / "video.mp4"
        test_file.touch()

        result = extract_date_from_video(test_file)
        assert result is None


class TestSetMtimeFromExif:
    """Tests for set_file_mtime_from_exif function."""

    def test_skips_unsupported_file_types(self, tmp_path: Path) -> None:
        """Test that unsupported file types are skipped."""
        test_file = tmp_path / "document.txt"
        test_file.touch()

        result = set_file_mtime_from_exif(test_file, dry_run=False)
        assert result is False

    def test_skips_files_without_exif(self, tmp_path: Path) -> None:
        """Test that files without EXIF data are skipped."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=None):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is False

    def test_sets_mtime_from_exif(self, tmp_path: Path) -> None:
        """Test that mtime is set from EXIF date."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is True

            # Verify mtime was updated
            new_mtime = test_file.stat().st_mtime
            assert abs(new_mtime - exif_date.timestamp()) < 1.0

    def test_dry_run_shows_changes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dry run shows what would be changed."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        original_mtime = test_file.stat().st_mtime

        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = set_file_mtime_from_exif(test_file, dry_run=True)
            assert result is True

            # Verify mtime was NOT changed
            assert test_file.stat().st_mtime == original_mtime

            # Verify output
            captured = capsys.readouterr()
            assert "[FIX]" in captured.out
            assert "2025-01-24 15:30:45" in captured.out

    def test_handles_oserror(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that OSError is handled gracefully."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        with (
            patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date),
            patch("os.utime", side_effect=OSError("Permission denied")),
        ):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is False

            captured = capsys.readouterr()
            assert "Warning:" in captured.err

    def test_skips_if_mtime_already_correct(self, tmp_path: Path) -> None:
        """Test that files with correct mtime are skipped."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        # Set mtime to match EXIF date
        os.utime(test_file, (exif_date.timestamp(), exif_date.timestamp()))

        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is False

    def test_processes_image_files(self, tmp_path: Path) -> None:
        """Test that image files are processed."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is True

    def test_processes_heif_files(self, tmp_path: Path) -> None:
        """Test that HEIF files are processed."""
        test_file = tmp_path / "photo.heic"
        test_file.touch()

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is True

    def test_processes_video_files(self, tmp_path: Path) -> None:
        """Test that video files are processed (returns None in stub)."""
        test_file = tmp_path / "video.mp4"
        test_file.touch()

        with patch("photos_manager.prepare.extract_date_from_video", return_value=None):
            result = set_file_mtime_from_exif(test_file, dry_run=False)
            assert result is False


class TestProcessDirectoryWithExif:
    """Tests for process_directory with EXIF support."""

    def test_processes_exif_when_flag_set(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test that EXIF processing occurs when use_exif=True."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        current_user, current_group = current_user_and_group

        with patch(
            "photos_manager.prepare._process_exif_timestamps", return_value=False
        ) as mock_exif:
            process_directory(tmp_path, current_user, current_group, dry_run=True, use_exif=True)

            # Verify EXIF processing was called
            assert mock_exif.called

    def test_skips_exif_when_flag_not_set(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that EXIF processing is skipped when use_exif=False."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        current_user, current_group = current_user_and_group

        with patch("photos_manager.prepare._process_exif_timestamps") as mock_exif:
            process_directory(tmp_path, current_user, current_group, dry_run=True, use_exif=False)

            # Verify EXIF processing was NOT called
            assert not mock_exif.called

    def test_exif_phase_runs_after_rename(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that EXIF phase runs after filename normalization."""
        test_file = tmp_path / "PHOTO.JPG"
        test_file.touch()

        current_user, current_group = current_user_and_group

        call_order = []

        def track_rename(*_args: Any, **_kwargs: Any) -> tuple[bool, dict[Path, Path]]:
            call_order.append("rename")
            return False, {}

        def track_exif(*_args: Any, **_kwargs: Any) -> bool:
            call_order.append("exif")
            return False

        with (
            patch("photos_manager.prepare._process_filenames", side_effect=track_rename),
            patch("photos_manager.prepare._process_exif_timestamps", side_effect=track_exif),
            patch("photos_manager.prepare._process_file_permissions", return_value=False),
            patch("photos_manager.prepare._process_dir_permissions", return_value=False),
            patch("photos_manager.prepare._process_ownership", return_value=False),
        ):
            process_directory(tmp_path, current_user, current_group, dry_run=True, use_exif=True)

            # Verify order: rename first, then EXIF
            assert call_order == ["rename", "exif"]

    def test_exif_errors_affect_return_value(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that EXIF errors cause process_directory to return False."""
        test_file = tmp_path / "photo.jpg"
        test_file.touch()

        current_user, current_group = current_user_and_group

        with patch("photos_manager.prepare._process_exif_timestamps", return_value=True):
            result = process_directory(
                tmp_path, current_user, current_group, dry_run=True, use_exif=True
            )

            assert result is False


class TestRunWithExifFlag:
    """Tests for run() with --use-exif flag."""

    def test_checks_libraries_when_flag_set(self) -> None:
        """Test that EXIF libraries are checked when --use-exif is set."""
        args = MagicMock()
        args.use_exif = True
        args.directories = []

        with (
            patch("photos_manager.prepare.EXIF_AVAILABLE", False),
            pytest.raises(SystemExit, match="EXIF libraries not installed"),
        ):
            run(args)

    def test_does_not_check_libraries_when_flag_not_set(self, tmp_path: Path) -> None:
        """Test that EXIF libraries are not checked when --use-exif is not set."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        args = MagicMock()
        args.use_exif = False
        args.dry_run = True
        args.user = "storage"
        args.group = "storage"
        args.directories = [str(test_dir)]

        with patch("photos_manager.prepare.check_exif_libraries_available") as mock_check:
            run(args)

            # Verify check was NOT called
            assert not mock_check.called

    def test_passes_use_exif_to_process_directory(self, tmp_path: Path) -> None:
        """Test that use_exif flag is passed to process_directory."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        args = MagicMock()
        args.use_exif = True
        args.dry_run = True
        args.user = "storage"
        args.group = "storage"
        args.directories = [str(test_dir)]

        with (
            patch("photos_manager.prepare.EXIF_AVAILABLE", True),
            patch("photos_manager.prepare.process_directory") as mock_process,
        ):
            mock_process.return_value = True
            run(args)

            # Verify process_directory was called with use_exif=True
            assert mock_process.called
            call_args = mock_process.call_args
            assert call_args[0][4] is True  # 5th positional argument is use_exif


class TestRunIntegration:
    """Integration tests for run() function."""

    def test_run_processes_single_directory(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() successfully processes a directory."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Create file with wrong permissions
        test_file = test_dir / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=False,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        assert stat.S_IMODE(test_file.stat().st_mode) == FILE_PERMISSIONS

    def test_run_with_nonexistent_directory(self) -> None:
        """Test that run() raises SystemExit for nonexistent directory."""

        args = argparse.Namespace(
            directories=["/nonexistent/path/that/does/not/exist"],
            dry_run=False,
            user="storage",
            group="storage",
            use_exif=False,
        )

        with pytest.raises(SystemExit, match="does not exist"):
            run(args)

    def test_run_with_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Test that run() raises SystemExit when path is a file."""

        test_file = tmp_path / "file.txt"
        test_file.touch()

        args = argparse.Namespace(
            directories=[str(test_file)],
            dry_run=False,
            user="storage",
            group="storage",
            use_exif=False,
        )

        with pytest.raises(SystemExit, match="is not a directory"):
            run(args)

    def test_run_with_multiple_directories(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() processes multiple directories."""

        # Create two directories with issues
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        file1 = dir1 / "TEST.TXT"
        file1.touch()

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        file2 = dir2 / "FILE.TXT"
        file2.touch()

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(dir1), str(dir2)],
            dry_run=False,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        # Verify both directories were processed
        assert (dir1 / "test.txt").exists()
        assert (dir2 / "file.txt").exists()

    def test_run_with_dry_run_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        current_user_and_group: tuple[str, str],
    ) -> None:
        """Test that run() with --dry-run shows message and doesn't modify files."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Create file with wrong permissions
        test_file = test_dir / "TEST.TXT"
        test_file.write_text("content")
        test_file.chmod(0o777)

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=True,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

        # Verify DRY-RUN message in output
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out

        # Verify no actual changes were made
        assert test_file.exists()  # Original uppercase file still exists
        assert stat.S_IMODE(test_file.stat().st_mode) == 0o777  # Permissions unchanged

    def test_run_returns_error_code_on_failure(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() returns 1 when processing fails."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        test_file = test_dir / "test.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=False,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        # Mock process_directory to return False (indicating failure)
        with patch("photos_manager.prepare.process_directory", return_value=False):
            exit_code = run(args)

        assert exit_code == 1

    def test_run_processes_permissions_and_names(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() fixes both permissions and filenames."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Create file with wrong permissions AND uppercase name
        test_file = test_dir / "MY FILE.TXT"
        test_file.touch()
        test_file.chmod(0o777)

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=False,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

        # Verify filename was normalized
        normalized_file = test_dir / "my_file.txt"
        assert normalized_file.exists()
        assert not test_file.exists()

        # Verify permissions were fixed
        assert stat.S_IMODE(normalized_file.stat().st_mode) == FILE_PERMISSIONS

    def test_run_resolves_directory_paths(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() resolves directory paths correctly."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        test_file = test_dir / "test.txt"
        test_file.touch()

        current_user, current_group = current_user_and_group

        # Use relative path (if possible)
        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=True,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        # Should not raise an error
        exit_code = run(args)
        assert exit_code == os.EX_OK

    def test_run_with_exif_processing_enabled(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() passes use_exif flag to process_directory."""

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        test_file = test_dir / "photo.jpg"
        test_file.touch()

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(test_dir)],
            dry_run=True,
            user=current_user,
            group=current_group,
            use_exif=True,
        )

        with (
            patch("photos_manager.prepare.EXIF_AVAILABLE", True),
            patch("photos_manager.prepare.process_directory") as mock_process,
        ):
            mock_process.return_value = True
            exit_code = run(args)

            assert exit_code == os.EX_OK
            # process_directory is called positionally: (path, user, group, dry_run, use_exif)
            mock_process.assert_called_once()
            assert mock_process.call_args.args[4] is True

    def test_run_handles_mixed_success_and_failure(
        self, tmp_path: Path, current_user_and_group: tuple[str, str]
    ) -> None:
        """Test that run() returns error if any directory fails."""

        dir1 = tmp_path / "dir1"
        dir1.mkdir()

        dir2 = tmp_path / "dir2"
        dir2.mkdir()

        current_user, current_group = current_user_and_group

        args = argparse.Namespace(
            directories=[str(dir1), str(dir2)],
            dry_run=False,
            user=current_user,
            group=current_group,
            use_exif=False,
        )

        # Mock to return success for first dir, failure for second
        call_count = [0]

        def mock_process(*_args: Any, **_kwargs: Any) -> bool:
            call_count[0] += 1
            return call_count[0] == 1  # True for first call, False for second

        with patch("photos_manager.prepare.process_directory", side_effect=mock_process):
            exit_code = run(args)

        # Should return error code since one directory failed
        assert exit_code == 1


class TestProcessExifTimestamps:
    """Tests for _process_exif_timestamps function."""

    def test_processes_supported_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that supported files are processed."""
        jpg_file = tmp_path / "photo.jpg"
        jpg_file.touch()
        png_file = tmp_path / "photo.png"
        png_file.touch()
        txt_file = tmp_path / "document.txt"
        txt_file.touch()

        from photos_manager.prepare import _process_exif_timestamps

        all_items = [jpg_file, png_file, txt_file]

        exif_date = datetime(2025, 1, 24, 15, 30, 45)
        with patch("photos_manager.prepare.extract_exif_date_from_image", return_value=exif_date):
            result = _process_exif_timestamps(all_items, dry_run=True)

            assert result is False  # No errors

            captured = capsys.readouterr()
            # Should process jpg and png, skip txt
            assert "photo.jpg" in captured.out
            assert "photo.png" in captured.out

    def test_prints_ok_when_all_correct(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that OK message is printed when all files have correct timestamps."""
        jpg_file = tmp_path / "photo.jpg"
        jpg_file.touch()

        from photos_manager.prepare import _process_exif_timestamps

        all_items = [jpg_file]

        # Mock to return False (no update needed)
        with patch("photos_manager.prepare.set_file_mtime_from_exif", return_value=False):
            result = _process_exif_timestamps(all_items, dry_run=True)

            assert result is False

            captured = capsys.readouterr()
            assert "[OK]" in captured.out
            assert "correct EXIF timestamps" in captured.out

    def test_prints_ok_when_no_media_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that OK message is printed when no media files found."""
        txt_file = tmp_path / "document.txt"
        txt_file.touch()

        from photos_manager.prepare import _process_exif_timestamps

        all_items = [txt_file]

        result = _process_exif_timestamps(all_items, dry_run=True)

        assert result is False

        captured = capsys.readouterr()
        assert "[OK]" in captured.out
        assert "No supported media files" in captured.out

    def test_handles_exceptions(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that exceptions are handled and reported as errors."""
        jpg_file = tmp_path / "photo.jpg"
        jpg_file.touch()

        from photos_manager.prepare import _process_exif_timestamps

        all_items = [jpg_file]

        with patch(
            "photos_manager.prepare.set_file_mtime_from_exif",
            side_effect=Exception("Test error"),
        ):
            result = _process_exif_timestamps(all_items, dry_run=True)

            assert result is True  # Errors occurred

            captured = capsys.readouterr()
            assert "Error:" in captured.err
