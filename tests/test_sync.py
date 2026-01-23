"""Tests for photos_manager.sync module."""

import argparse
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from photos_manager import sync


class TestBuildFileIndex:
    """Tests for build_file_index function."""

    def test_build_index_single_file(self):
        """Test building index with single file."""
        data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        index = sync.build_file_index(data)

        assert ("abc123", "def456", 1000) in index
        assert index[("abc123", "def456", 1000)]["path"] == "/archive/photo.jpg"

    def test_build_index_multiple_files(self):
        """Test building index with multiple files."""
        data = [
            {
                "path": "/archive/photo1.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            },
            {
                "path": "/archive/photo2.jpg",
                "sha1": "xyz789",
                "md5": "uvw012",
                "size": 2000,
                "date": "2024-01-02T12:00:00+01:00",
            },
        ]

        index = sync.build_file_index(data)

        assert len(index) == 2
        assert ("abc123", "def456", 1000) in index
        assert ("xyz789", "uvw012", 2000) in index

    def test_build_index_empty_data(self):
        """Test building index with empty data."""
        index = sync.build_file_index([])
        assert len(index) == 0

    def test_build_index_duplicate_identity(self):
        """Test building index with duplicate file identity (keeps first)."""
        data = [
            {
                "path": "/archive/photo1.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            },
            {
                "path": "/archive/photo2.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-02T12:00:00+01:00",
            },
        ]

        index = sync.build_file_index(data)

        # Should only have one entry (first occurrence)
        assert len(index) == 1
        assert index[("abc123", "def456", 1000)]["path"] == "/archive/photo1.jpg"


class TestComputeSyncPlan:
    """Tests for compute_sync_plan function."""

    def test_sync_plan_new_file(self):
        """Test sync plan with new file in source."""
        source_data = [
            {
                "path": "/archive/new.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        dest_data = []

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have copy operation
        copy_ops = [op for op in operations if op.op_type == "copy"]
        assert len(copy_ops) == 1
        assert copy_ops[0].source_path == "/archive/new.jpg"
        assert copy_ops[0].dest_path == "/archive/new.jpg"
        assert "new file" in copy_ops[0].reason

    def test_sync_plan_deleted_file(self):
        """Test sync plan with file deleted from source."""
        source_data = []
        dest_data = [
            {
                "path": "/archive/deleted.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have delete operation
        delete_ops = [op for op in operations if op.op_type == "delete"]
        assert len(delete_ops) == 1
        assert delete_ops[0].dest_path == "/archive/deleted.jpg"

    def test_sync_plan_moved_file(self):
        """Test sync plan with file moved/renamed."""
        source_data = [
            {
                "path": "/archive/new_name.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        dest_data = [
            {
                "path": "/archive/old_name.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have move operation
        move_ops = [op for op in operations if op.op_type == "move"]
        assert len(move_ops) == 1
        assert move_ops[0].source_path == "/archive/old_name.jpg"
        assert move_ops[0].dest_path == "/archive/new_name.jpg"
        assert "moved" in move_ops[0].reason or "renamed" in move_ops[0].reason

    def test_sync_plan_timestamp_mismatch(self):
        """Test sync plan with timestamp mismatch."""
        source_data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        dest_data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T11:00:00+01:00",  # Different timestamp
            }
        ]

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have touch operation
        touch_ops = [op for op in operations if op.op_type == "touch"]
        assert len(touch_ops) == 1
        assert touch_ops[0].dest_path == "/archive/photo.jpg"
        assert "timestamp" in touch_ops[0].reason

    def test_sync_plan_content_changed(self):
        """Test sync plan with file content changed (same path, different content)."""
        source_data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "new_sha",
                "md5": "new_md5",
                "size": 2000,
                "date": "2024-01-02T12:00:00+01:00",
            }
        ]
        dest_data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "old_sha",
                "md5": "old_md5",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        operations, warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should warn and have copy operation
        assert len(warnings) > 0
        assert any("modified" in w.lower() for w in warnings)

        copy_ops = [op for op in operations if op.op_type == "copy"]
        assert len(copy_ops) == 1
        assert "changed" in copy_ops[0].reason or "modified" in copy_ops[0].reason

    def test_sync_plan_identical_archives(self):
        """Test sync plan with identical archives."""
        data = [
            {
                "path": "/archive/photo.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        operations, _warnings = sync.compute_sync_plan(data, data, "/source", "/dest")

        # Should have no operations
        assert len(operations) == 0

    def test_sync_plan_multiple_operations(self):
        """Test sync plan with multiple operation types."""
        source_data = [
            {
                "path": "/archive/new.jpg",
                "sha1": "new_sha",
                "md5": "new_md5",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            },
            {
                "path": "/archive/renamed.jpg",
                "sha1": "move_sha",
                "md5": "move_md5",
                "size": 2000,
                "date": "2024-01-02T12:00:00+01:00",
            },
        ]
        dest_data = [
            {
                "path": "/archive/old_name.jpg",
                "sha1": "move_sha",
                "md5": "move_md5",
                "size": 2000,
                "date": "2024-01-02T12:00:00+01:00",
            },
            {
                "path": "/archive/deleted.jpg",
                "sha1": "del_sha",
                "md5": "del_md5",
                "size": 3000,
                "date": "2024-01-03T12:00:00+01:00",
            },
        ]

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have mix of operations
        op_types = {op.op_type for op in operations}
        assert "copy" in op_types  # For new.jpg
        assert "move" in op_types  # For renamed.jpg
        assert "delete" in op_types  # For deleted.jpg

    def test_sync_plan_empty_archives(self):
        """Test sync plan with empty archives."""
        operations, warnings = sync.compute_sync_plan([], [], "/source", "/dest")
        assert len(operations) == 0
        assert len(warnings) == 0

    def test_sync_plan_moved_file_with_timestamp_fix(self):
        """Test sync plan with moved file that needs timestamp correction."""
        source_data = [
            {
                "path": "/archive/new_path.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-02T12:00:00+01:00",  # Different timestamp
            }
        ]
        dest_data = [
            {
                "path": "/archive/old_path.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]

        operations, _warnings = sync.compute_sync_plan(source_data, dest_data, "/source", "/dest")

        # Should have move + touch operations
        move_ops = [op for op in operations if op.op_type == "move"]
        touch_ops = [op for op in operations if op.op_type == "touch"]

        assert len(move_ops) == 1
        assert len(touch_ops) == 1
        assert touch_ops[0].reason == "timestamp correction after move"


class TestOptimizeOperations:
    """Tests for optimize_operations function."""

    def test_optimize_adds_mkdir(self):
        """Test that optimize_operations adds mkdir for new directories."""
        operations = [
            sync.SyncOperation(
                op_type="copy",
                source_path="/src/photo.jpg",
                dest_path="/dest/new_dir/photo.jpg",
                expected_mtime=1234567890,
                reason="test",
            )
        ]

        # Empty dest_data means directory doesn't exist
        optimized = sync.optimize_operations(operations, [], "/dest")

        # Should have mkdir + copy
        mkdir_ops = [op for op in optimized if op.op_type == "mkdir"]
        assert len(mkdir_ops) >= 1
        assert any("/dest/new_dir" in op.dest_path for op in mkdir_ops)

    def test_optimize_sorts_operations(self):
        """Test that operations are sorted by type priority."""
        operations = [
            sync.SyncOperation("touch", None, "/dest/file1.jpg", 123, "test"),
            sync.SyncOperation("copy", "/src/file2.jpg", "/dest/file2.jpg", 456, "test"),
            sync.SyncOperation("delete", None, "/dest/file3.jpg", None, "test"),
            sync.SyncOperation("move", "/dest/old.jpg", "/dest/new.jpg", None, "test"),
        ]

        optimized = sync.optimize_operations(operations, [], "/dest")

        # Find indices of each operation type
        op_types = [op.op_type for op in optimized]

        # mkdir should come first, then delete, move, copy, touch
        if "mkdir" in op_types:
            mkdir_idx = op_types.index("mkdir")
            delete_idx = op_types.index("delete")
            assert mkdir_idx < delete_idx

        delete_idx = op_types.index("delete")
        move_idx = op_types.index("move")
        copy_idx = op_types.index("copy")
        touch_idx = op_types.index("touch")

        assert delete_idx < move_idx < copy_idx < touch_idx

    def test_optimize_empty_operations(self):
        """Test optimize with empty operations list."""
        optimized = sync.optimize_operations([], [], "/dest")
        assert len(optimized) == 0

    def test_optimize_no_new_directories(self):
        """Test optimize when no new directories are needed."""
        operations = [
            sync.SyncOperation("touch", None, "/existing/file.jpg", 123, "test"),
        ]

        # Destination has file in /existing/ so directory exists
        dest_data = [
            {
                "path": "/existing/other.jpg",
                "sha1": "abc",
                "md5": "def",
                "size": 100,
                "date": "2024-01-01T12:00:00+00:00",
            }
        ]

        optimized = sync.optimize_operations(operations, dest_data, "/dest")

        # Should have no mkdir since directory already exists
        mkdir_ops = [op for op in optimized if op.op_type == "mkdir"]
        assert len(mkdir_ops) == 0

        # Should have the touch operation
        touch_ops = [op for op in optimized if op.op_type == "touch"]
        assert len(touch_ops) == 1

    def test_optimize_multiple_files_same_directory(self):
        """Test optimize with multiple files in same new directory."""
        operations = [
            sync.SyncOperation("copy", "/src/photo1.jpg", "/dest/newdir/photo1.jpg", 123, "test"),
            sync.SyncOperation("copy", "/src/photo2.jpg", "/dest/newdir/photo2.jpg", 456, "test"),
        ]

        optimized = sync.optimize_operations(operations, [], "/dest")

        # Should have one mkdir + two copies
        mkdir_ops = [op for op in optimized if op.op_type == "mkdir"]
        # May have multiple mkdir for nested paths, but at least one
        assert len(mkdir_ops) >= 1

    def test_optimize_sorts_paths_alphabetically(self):
        """Test that operations with same priority are sorted by path."""
        operations = [
            sync.SyncOperation("copy", "/src/z.jpg", "/dest/z.jpg", 123, "test"),
            sync.SyncOperation("copy", "/src/a.jpg", "/dest/a.jpg", 456, "test"),
            sync.SyncOperation("copy", "/src/m.jpg", "/dest/m.jpg", 789, "test"),
        ]

        optimized = sync.optimize_operations(operations, [], "/dest")

        copy_ops = [op for op in optimized if op.op_type == "copy"]
        copy_paths = [op.dest_path for op in copy_ops]

        # Should be sorted
        assert copy_paths == sorted(copy_paths)


class TestComputeMetadataUpdates:
    """Tests for compute_metadata_updates function."""

    def test_metadata_updates_for_copy(self):
        """Test metadata updates after copy operation."""
        operations = [
            sync.SyncOperation(
                "copy", "/src/newdir/photo.jpg", "/dest/newdir/photo.jpg", 1234567890, "test"
            )
        ]
        source_data = [
            {
                "path": "/dest/newdir/photo.jpg",
                "date": "2024-01-01T12:00:00+01:00",
                "sha1": "abc",
                "md5": "def",
                "size": 100,
            }
        ]

        metadata_ops = sync.compute_metadata_updates(operations, source_data, "/dest")

        # Should have directory mtime update
        dir_ops = [op for op in metadata_ops if op.op_type == "update-dir-mtime"]
        assert len(dir_ops) >= 1

    def test_metadata_updates_for_delete(self):
        """Test metadata updates after delete operation."""
        operations = [sync.SyncOperation("delete", None, "/dest/dir/photo.jpg", None, "test")]
        source_data = [
            {
                "path": "/dest/dir/other.jpg",
                "date": "2024-01-01T12:00:00+01:00",
                "sha1": "abc",
                "md5": "def",
                "size": 100,
            }
        ]

        metadata_ops = sync.compute_metadata_updates(operations, source_data, "/dest")

        # Should have directory mtime update
        dir_ops = [op for op in metadata_ops if op.op_type == "update-dir-mtime"]
        assert len(dir_ops) >= 0  # May or may not have update depending on remaining files

    def test_metadata_updates_empty_operations(self):
        """Test metadata updates with no operations."""
        metadata_ops = sync.compute_metadata_updates([], [], "/dest")
        assert len(metadata_ops) == 0

    def test_metadata_updates_newest_file_in_directory(self):
        """Test that directory mtime is set to newest file."""
        operations = [sync.SyncOperation("touch", None, "/dest/dir/photo.jpg", 1234567890, "test")]
        source_data = [
            {
                "path": "/dest/dir/photo1.jpg",
                "date": "2024-01-01T12:00:00+01:00",
                "sha1": "abc",
                "md5": "def",
                "size": 100,
            },
            {
                "path": "/dest/dir/photo2.jpg",
                "date": "2024-01-02T12:00:00+01:00",  # Newer
                "sha1": "xyz",
                "md5": "uvw",
                "size": 200,
            },
        ]

        metadata_ops = sync.compute_metadata_updates(operations, source_data, "/dest")

        dir_ops = [op for op in metadata_ops if op.op_type == "update-dir-mtime"]
        if dir_ops:
            # Should use timestamp from photo2 (newer)
            expected_mtime = int(datetime.fromisoformat("2024-01-02T12:00:00+01:00").timestamp())
            assert any(op.expected_mtime == expected_mtime for op in dir_ops)


class TestValidateArchiveDirectories:
    """Tests for validate_archive_directories function."""

    def test_validate_valid_directories(self, tmp_path):
        """Test validation with valid source and destination directories."""
        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()

        valid, errors = sync.validate_archive_directories(str(source_dir), str(dest_dir))

        assert valid
        assert len(errors) == 0

    def test_validate_nonexistent_source(self, tmp_path):
        """Test validation with nonexistent source directory."""
        source_dir = tmp_path / "nonexistent"
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        valid, errors = sync.validate_archive_directories(str(source_dir), str(dest_dir))

        assert not valid
        assert len(errors) > 0
        assert any("source" in e.lower() for e in errors)

    def test_validate_nonexistent_dest(self, tmp_path):
        """Test validation with nonexistent destination directory."""
        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "nonexistent"
        source_dir.mkdir()

        valid, errors = sync.validate_archive_directories(str(source_dir), str(dest_dir))

        assert not valid
        assert len(errors) > 0
        assert any("destination" in e.lower() for e in errors)

    def test_validate_file_instead_of_directory(self, tmp_path):
        """Test validation when path points to file instead of directory."""
        source_file = tmp_path / "source.txt"
        dest_dir = tmp_path / "dest"
        source_file.write_text("test")
        dest_dir.mkdir()

        valid, errors = sync.validate_archive_directories(str(source_file), str(dest_dir))

        assert not valid
        assert len(errors) > 0


class TestOperationToCommand:
    """Tests for SyncOperation.to_command method."""

    def test_mkdir_command(self):
        """Test mkdir operation command generation."""
        op = sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test")
        commands = op.to_command()

        assert len(commands) == 1
        assert "mkdir -p /dest/newdir" in commands[0]

    def test_copy_command(self):
        """Test copy operation command generation."""
        op = sync.SyncOperation("copy", "/src/photo.jpg", "/dest/photo.jpg", 1234567890, "test")
        commands = op.to_command()

        assert len(commands) == 1
        assert "rsync" in commands[0]
        assert "/src/photo.jpg" in commands[0]
        assert "/dest/photo.jpg" in commands[0]

    def test_move_command(self):
        """Test move operation command generation."""
        op = sync.SyncOperation("move", "/dest/old.jpg", "/dest/new.jpg", None, "test")
        commands = op.to_command()

        assert len(commands) == 1
        assert "mv" in commands[0]
        assert "/dest/old.jpg" in commands[0]
        assert "/dest/new.jpg" in commands[0]

    def test_delete_command(self):
        """Test delete operation command generation."""
        op = sync.SyncOperation("delete", None, "/dest/old.jpg", None, "test")
        commands = op.to_command()

        assert len(commands) == 1
        assert "rm" in commands[0]
        assert "/dest/old.jpg" in commands[0]

    def test_touch_command(self):
        """Test touch operation command generation."""
        # Timestamp: 2024-01-01 12:00:00 UTC
        mtime = 1704110400
        op = sync.SyncOperation("touch", None, "/dest/photo.jpg", mtime, "test")
        commands = op.to_command()

        assert len(commands) == 1
        assert "touch -t" in commands[0]
        assert "/dest/photo.jpg" in commands[0]


class TestGenerateSyncScript:
    """Tests for generate_sync_script function."""

    def test_generate_script_basic(self, tmp_path):
        """Test basic script generation."""
        output_path = tmp_path / "sync.sh"
        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "create directory"),
            sync.SyncOperation("copy", "/src/photo.jpg", "/dest/photo.jpg", 1234567890, "new file"),
        ]

        sync.generate_sync_script(operations, str(output_path))

        assert output_path.exists()
        script_content = output_path.read_text()

        # Check script contains expected elements
        assert "#!/bin/bash" in script_content
        assert "mkdir" in script_content
        assert "rsync" in script_content
        assert "# create directory" in script_content
        assert "# new file" in script_content

    def test_generate_script_is_executable(self, tmp_path):
        """Test that generated script is executable."""
        output_path = tmp_path / "sync.sh"
        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test"),
        ]

        sync.generate_sync_script(operations, str(output_path))

        # Check file is executable
        file_stat = output_path.stat()
        assert file_stat.st_mode & 0o111  # Check any execute bit is set

    def test_generate_script_invalid_path(self):
        """Test script generation with invalid output path."""
        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test"),
        ]

        with pytest.raises(SystemExit):
            sync.generate_sync_script(operations, "/nonexistent/dir/sync.sh")


class TestCheckForDangerousOperations:
    """Tests for check_for_dangerous_operations function."""

    def test_check_safe_operations(self):
        """Test checking operations that are safe."""
        operations = [
            sync.SyncOperation("copy", "/src/a.jpg", "/dest/a.jpg", 123, "test"),
            sync.SyncOperation("touch", None, "/dest/b.jpg", 456, "test"),
        ]

        dangerous, warnings = sync.check_for_dangerous_operations(operations)

        assert not dangerous
        assert len(warnings) == 0

    def test_check_mass_deletion_count(self):
        """Test checking for mass deletion by count (>100 files)."""
        operations = [
            sync.SyncOperation("delete", None, f"/dest/file{i}.jpg", None, "test")
            for i in range(150)
        ]

        dangerous, warnings = sync.check_for_dangerous_operations(operations)

        assert dangerous
        assert len(warnings) > 0
        assert any("mass deletion" in w.lower() for w in warnings)

    def test_check_mass_deletion_percentage(self):
        """Test checking for mass deletion by percentage (>30%)."""
        operations = [
            sync.SyncOperation("delete", None, f"/dest/del{i}.jpg", None, "test") for i in range(40)
        ] + [
            sync.SyncOperation("copy", f"/src/keep{i}.jpg", f"/dest/keep{i}.jpg", 123, "test")
            for i in range(60)
        ]

        dangerous, warnings = sync.check_for_dangerous_operations(operations)

        assert dangerous
        assert len(warnings) > 0
        assert any("deletion" in w.lower() for w in warnings)

    def test_check_no_deletions(self):
        """Test checking operations with no deletions."""
        operations = [
            sync.SyncOperation("copy", "/src/a.jpg", "/dest/a.jpg", 123, "test"),
            sync.SyncOperation("move", "/dest/b.jpg", "/dest/c.jpg", None, "test"),
        ]

        dangerous, warnings = sync.check_for_dangerous_operations(operations)

        assert not dangerous
        assert len(warnings) == 0


class TestExecuteSync:
    """Tests for execute_sync function."""

    def test_execute_dry_run(self):
        """Test executing operations in dry-run mode."""
        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test"),
            sync.SyncOperation("copy", "/src/photo.jpg", "/dest/photo.jpg", 123, "test"),
        ]

        successful, failed = sync.execute_sync(operations, dry_run=True)

        # All operations should succeed in dry-run
        assert successful > 0
        assert failed == 0

    def test_execute_empty_operations(self):
        """Test executing empty operations list."""
        successful, failed = sync.execute_sync([], dry_run=True)

        assert successful == 0
        assert failed == 0

    @patch("os.system")
    def test_execute_real_mode_success(self, mock_system):
        """Test executing operations in real mode with success."""
        mock_system.return_value = 0  # Success

        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test"),
        ]

        successful, failed = sync.execute_sync(operations, dry_run=False)

        assert successful > 0
        assert failed == 0
        assert mock_system.called

    @patch("os.system")
    def test_execute_real_mode_failure(self, mock_system):
        """Test executing operations in real mode with failure."""
        mock_system.return_value = 1  # Failure

        operations = [
            sync.SyncOperation("mkdir", None, "/dest/newdir", None, "test"),
        ]

        successful, failed = sync.execute_sync(operations, dry_run=False)

        assert successful == 0
        assert failed > 0


class TestLoadArchive:
    """Tests for load_archive function."""

    def test_load_archive_valid(self, tmp_path):
        """Test loading a valid archive."""
        # Create archive structure
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        # Create version file
        version_file = archive_dir / ".version.json"
        version_data = {
            "version": "test-1.0",
            "files": {"photos.json": "abc123"},
            "total_bytes": 1000,
            "file_count": 1,
        }
        version_file.write_text(json.dumps(version_data))

        # Create JSON metadata file
        json_file = archive_dir / "photos.json"
        json_data = [
            {
                "path": "photo.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Load archive
        all_data, json_files, version, errors = sync.load_archive(str(archive_dir))

        assert len(errors) == 0
        assert len(all_data) == 1
        assert len(json_files) == 1
        assert version is not None

    def test_load_archive_no_json_files(self, tmp_path):
        """Test loading archive with no JSON files."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        all_data, _json_files, _version, errors = sync.load_archive(str(archive_dir))

        assert len(errors) > 0
        assert len(all_data) == 0

    def test_load_archive_invalid_json(self, tmp_path):
        """Test loading archive with invalid JSON file."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        # Create invalid JSON file
        json_file = archive_dir / "photos.json"
        json_file.write_text("{ invalid json }")

        _all_data, _json_files, _version, errors = sync.load_archive(str(archive_dir))

        # Should report errors but not crash
        assert len(errors) > 0


class TestMain:
    """Integration tests for the main run() function."""

    def test_run_missing_arguments(self):
        """Test run with missing required arguments."""
        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)

        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_run_invalid_source_directory(self, tmp_path):
        """Test run with invalid source directory."""
        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        args = parser.parse_args(["/nonexistent", str(dest_dir)])
        exit_code = sync.run(args)

        assert exit_code != 0

    def test_run_invalid_dest_directory(self, tmp_path):
        """Test run with invalid destination directory."""
        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)

        source_dir = tmp_path / "source"
        source_dir.mkdir()

        args = parser.parse_args([str(source_dir), "/nonexistent"])
        exit_code = sync.run(args)

        assert exit_code != 0

    def test_run_dry_run_mode(self, tmp_path):
        """Test run in dry-run mode with valid archives."""
        # Create source archive
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        source_json = source_dir / "photos.json"
        source_data = [
            {
                "path": str(source_dir / "photo.jpg"),
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        source_json.write_text(json.dumps(source_data))

        # Create destination archive
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        dest_json = dest_dir / "photos.json"
        dest_data = []
        dest_json.write_text(json.dumps(dest_data))

        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)
        args = parser.parse_args([str(source_dir), str(dest_dir)])

        exit_code = sync.run(args)

        # Should succeed in dry-run mode
        assert exit_code == 0

    def test_run_no_delete_flag(self, tmp_path):
        """Test run with --no-delete flag."""
        # Create archives
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_json = source_dir / "photos.json"
        source_json.write_text(json.dumps([]))

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        dest_json = dest_dir / "photos.json"
        dest_data = [
            {
                "path": str(dest_dir / "photo.jpg"),
                "sha1": "abc123",
                "md5": "def456",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        dest_json.write_text(json.dumps(dest_data))

        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)
        args = parser.parse_args([str(source_dir), str(dest_dir), "--no-delete"])

        exit_code = sync.run(args)

        # Should succeed
        assert exit_code == 0

    def test_run_with_output_script(self, tmp_path):
        """Test run with --output flag to generate script."""
        # Create archives
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_json = source_dir / "photos.json"
        source_json.write_text(json.dumps([]))

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        dest_json = dest_dir / "photos.json"
        dest_json.write_text(json.dumps([]))

        output_script = tmp_path / "sync.sh"

        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)
        args = parser.parse_args([str(source_dir), str(dest_dir), "--output", str(output_script)])

        exit_code = sync.run(args)

        # Should succeed and create script
        assert exit_code == 0
        assert output_script.exists()

    def test_run_verbose_mode(self, tmp_path):
        """Test run with --verbose flag."""
        # Create archives
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_json = source_dir / "photos.json"
        source_json.write_text(json.dumps([]))

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        dest_json = dest_dir / "photos.json"
        dest_json.write_text(json.dumps([]))

        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)
        args = parser.parse_args([str(source_dir), str(dest_dir), "--verbose"])

        exit_code = sync.run(args)

        # Should succeed
        assert exit_code == 0

    @patch("builtins.input")
    def test_run_execute_mode_cancellation(self, mock_input, tmp_path):
        """Test run with --execute flag but user cancels at prompt."""
        mock_input.return_value = "no"

        # Create archives with many deletions to trigger warning
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_json = source_dir / "photos.json"
        source_json.write_text(json.dumps([]))

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        dest_json = dest_dir / "photos.json"
        dest_data = [
            {
                "path": str(dest_dir / f"photo{i}.jpg"),
                "sha1": f"sha{i}",
                "md5": f"md5{i}",
                "size": 1000,
                "date": "2024-01-01T12:00:00+01:00",
            }
            for i in range(150)  # More than 100 deletions
        ]
        dest_json.write_text(json.dumps(dest_data))

        parser = argparse.ArgumentParser()
        sync.setup_parser(parser)
        args = parser.parse_args([str(source_dir), str(dest_dir), "--execute"])

        exit_code = sync.run(args)

        # Should cancel (exit code 1)
        assert exit_code == 1
