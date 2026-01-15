"""Tests for prepare module."""

import grp
import os
import pwd
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from _pytest.capture import CaptureFixture

from photos_manager.prepare import (
    DIR_PERMISSIONS,
    FILE_PERMISSIONS,
    check_dir_permissions,
    check_file_permissions,
    check_ownership,
    fix_dir_permissions,
    fix_file_permissions,
    fix_ownership,
    get_items_depth_first,
    get_unique_normalized_path,
    has_spaces,
    has_uppercase,
    is_hidden,
    main,
    needs_normalization,
    process_directory,
    rename_to_normalized,
    scan_directory,
)


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

    def test_correct_ownership_returns_true(self, tmp_path: Path) -> None:
        """Test that files with correct ownership return True."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

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

    def test_dry_run_does_not_change(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
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

    def test_dry_run_does_not_change(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
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

    def test_dry_run_does_not_rename(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
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

    def test_returns_success_on_no_errors(self, tmp_path: Path) -> None:
        """Test that processing returns True when no errors occur."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(FILE_PERMISSIONS)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        result = process_directory(tmp_path, current_user, current_group, dry_run=True)

        assert result is True

    def test_fixes_file_permissions(self, tmp_path: Path) -> None:
        """Test that file permissions are fixed."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(0o777)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert stat.S_IMODE(test_file.stat().st_mode) == FILE_PERMISSIONS

    def test_fixes_directory_permissions(self, tmp_path: Path) -> None:
        """Test that directory permissions are fixed."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        subdir.chmod(0o700)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert stat.S_IMODE(subdir.stat().st_mode) == DIR_PERMISSIONS

    def test_renames_uppercase_files(self, tmp_path: Path) -> None:
        """Test that uppercase files are renamed."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert (tmp_path / "test.txt").exists()
        assert not test_file.exists()

    def test_converts_spaces_to_underscores(self, tmp_path: Path) -> None:
        """Test that spaces in filenames are converted to underscores."""
        test_file = tmp_path / "my file.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert (tmp_path / "my_file.txt").exists()
        assert not test_file.exists()


class TestMain:
    """Tests for main function."""

    def test_processes_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that main processes a directory."""
        test_file = tmp_path / "test.txt"
        test_file.touch()
        test_file.chmod(FILE_PERMISSIONS)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            ["prepare.py", str(tmp_path), "--user", current_user, "--group", current_group],
        )

        exit_code = main()

        assert exit_code == os.EX_OK

    def test_dry_run_does_not_modify(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that --dry-run does not modify files."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()
        test_file.chmod(0o777)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                "--dry-run",
                str(tmp_path),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        main()

        # File should not be renamed
        assert test_file.exists()
        # Permissions should not be changed
        assert stat.S_IMODE(test_file.stat().st_mode) == 0o777

    def test_raises_on_nonexistent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that SystemExit is raised for nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"

        monkeypatch.setattr("sys.argv", ["prepare.py", str(nonexistent)])

        with pytest.raises(SystemExit, match="does not exist"):
            main()

    def test_raises_on_file_instead_of_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that SystemExit is raised when path is a file."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        monkeypatch.setattr("sys.argv", ["prepare.py", str(test_file)])

        with pytest.raises(SystemExit, match="is not a directory"):
            main()

    def test_processes_multiple_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that multiple directories are processed."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "file1.txt").touch()

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "file2.txt").touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                str(dir1),
                str(dir2),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        exit_code = main()

        assert exit_code == os.EX_OK

    def test_short_dry_run_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that -n flag works as --dry-run."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                "-n",
                str(tmp_path),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        main()

        # File should not be renamed
        assert test_file.exists()

        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out

    def test_default_user_and_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that default user and group are 'storage'."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        monkeypatch.setattr("sys.argv", ["prepare.py", "--dry-run", str(tmp_path)])

        main()

        captured = capsys.readouterr()
        assert "storage:storage" in captured.out

    def test_skips_hidden_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that hidden files are skipped."""
        hidden_file = tmp_path / ".hidden"
        hidden_file.touch()
        hidden_file.chmod(0o777)

        visible_file = tmp_path / "visible.txt"
        visible_file.touch()
        visible_file.chmod(FILE_PERMISSIONS)

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                str(tmp_path),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        main()

        # Hidden file should not be changed
        assert stat.S_IMODE(hidden_file.stat().st_mode) == 0o777

    def test_renames_directories_to_lowercase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that uppercase directories are renamed."""
        upper_dir = tmp_path / "UPPERCASE"
        upper_dir.mkdir()
        (upper_dir / "file.txt").touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                str(tmp_path),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        main()

        assert (tmp_path / "uppercase").exists()
        assert (tmp_path / "uppercase" / "file.txt").exists()
        assert not upper_dir.exists()

    def test_converts_spaces_in_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that spaces in directory names are converted to underscores."""
        space_dir = tmp_path / "my directory"
        space_dir.mkdir()
        (space_dir / "file.txt").touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare.py",
                str(tmp_path),
                "--user",
                current_user,
                "--group",
                current_group,
            ],
        )

        main()

        assert (tmp_path / "my_directory").exists()
        assert (tmp_path / "my_directory" / "file.txt").exists()
        assert not space_dir.exists()


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

    def test_check_ownership_unknown_gid(self, tmp_path: Path) -> None:
        """Test check_ownership handles unknown gid gracefully."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name

        with patch("photos_manager.prepare.grp.getgrgid", side_effect=KeyError("gid")):
            is_ok, _user, group = check_ownership(test_file, current_user, "somegroup")

        # Should return numeric gid as string
        assert is_ok is False
        assert group.isdigit()

    def test_fix_file_permissions_oserror(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test fix_file_permissions handles OSError."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
            result = fix_file_permissions(test_file, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_dir_permissions_oserror(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test fix_dir_permissions handles OSError."""
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()

        with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
            result = fix_dir_permissions(test_dir, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_ownership_nonexistent_user(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
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
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test fix_ownership with nonexistent group."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name

        result = fix_ownership(test_file, current_user, "nonexistent_group_12345", dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "not found" in captured.err

    def test_fix_ownership_chown_oserror(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test fix_ownership handles chown OSError."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        with patch(
            "photos_manager.prepare.os.chown", side_effect=OSError("Operation not permitted")
        ):
            result = fix_ownership(test_file, current_user, current_group, dry_run=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_fix_ownership_unknown_current_uid(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test fix_ownership handles unknown current uid in dry-run."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

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
        self, tmp_path: Path, capsys: CaptureFixture[Any]
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
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test process_directory returns False when errors occur."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        with patch.object(Path, "rename", side_effect=OSError("Cannot rename")):
            result = process_directory(tmp_path, current_user, current_group, dry_run=False)

        assert result is False

    def test_main_returns_error_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main returns 1 when processing fails."""
        test_file = tmp_path / "TEST.TXT"
        test_file.touch()

        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name

        monkeypatch.setattr(
            "sys.argv",
            ["prepare.py", str(tmp_path), "--user", current_user, "--group", current_group],
        )

        with patch.object(Path, "rename", side_effect=OSError("Cannot rename")):
            exit_code = main()

        assert exit_code == 1
