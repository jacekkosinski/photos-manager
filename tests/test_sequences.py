"""Tests for photos_manager.sequences module."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from photos_manager import sequences


def _make_entry(path: str, date: str, size: int = 1000) -> dict[str, str | int]:
    """Create a minimal JSON metadata entry."""
    return {
        "path": path,
        "sha1": "a" * 40,
        "md5": "b" * 32,
        "date": date,
        "size": size,
    }


# --- Unit tests ---


@pytest.mark.unit
class TestDetectSequences:
    """Tests for detect_sequences function."""

    def test_single_monotonic_sequence(self) -> None:
        """Test that a monotonic sequence produces one group."""
        files = [
            ("dir/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC)),
            ("dir/img_002.jpg", "img_", 2, datetime(2025, 1, 2, tzinfo=UTC)),
            ("dir/img_003.jpg", "img_", 3, datetime(2025, 1, 3, tzinfo=UTC)),
        ]
        result = sequences.detect_sequences(files)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_two_interleaved_sequences(self) -> None:
        """Test detection of two interleaved sequences."""
        files = [
            ("dir/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC)),
            ("dir/img_002.jpg", "img_", 2, datetime(2025, 1, 2, tzinfo=UTC)),
            ("dir/dsc_001.jpg", "dsc_", 1, datetime(2025, 1, 3, tzinfo=UTC)),
            ("dir/img_003.jpg", "img_", 3, datetime(2025, 1, 4, tzinfo=UTC)),
        ]
        result = sequences.detect_sequences(files)
        assert len(result) == 2
        assert len(result[0]) == 3
        assert len(result[1]) == 1

    def test_decreasing_sequence_splits(self) -> None:
        """Test that a fully decreasing sequence produces one seq per file."""
        files = [
            ("dir/img_003.jpg", "img_", 3, datetime(2025, 1, 1, tzinfo=UTC)),
            ("dir/img_002.jpg", "img_", 2, datetime(2025, 1, 2, tzinfo=UTC)),
            ("dir/img_001.jpg", "img_", 1, datetime(2025, 1, 3, tzinfo=UTC)),
        ]
        result = sequences.detect_sequences(files)
        assert len(result) == 3

    def test_empty_input(self) -> None:
        """Test with no files."""
        assert sequences.detect_sequences([]) == []

    def test_equal_seq_numbers_stay_together(self) -> None:
        """Test that equal seq numbers continue the same sequence."""
        files = [
            ("dir/img_005.jpg", "img_", 5, datetime(2025, 1, 1, tzinfo=UTC)),
            ("dir/img_005.cr3", "img_", 5, datetime(2025, 1, 1, tzinfo=UTC)),
            ("dir/img_006.jpg", "img_", 6, datetime(2025, 1, 2, tzinfo=UTC)),
        ]
        result = sequences.detect_sequences(files)
        assert len(result) == 1

    def test_sequence_spans_directories(self) -> None:
        """Test that a sequence can span multiple directories."""
        files = [
            ("cam/100/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC)),
            ("cam/100/img_002.jpg", "img_", 2, datetime(2025, 1, 2, tzinfo=UTC)),
            ("cam/101/img_003.jpg", "img_", 3, datetime(2025, 1, 3, tzinfo=UTC)),
            ("cam/101/img_004.jpg", "img_", 4, datetime(2025, 1, 4, tzinfo=UTC)),
        ]
        result = sequences.detect_sequences(files)
        assert len(result) == 1
        assert len(result[0]) == 4


@pytest.mark.unit
class TestLoadFiles:
    """Tests for load_files function."""

    def test_loads_and_sorts_by_date(self, tmp_path: Path) -> None:
        """Test that entries are loaded and sorted by date."""
        entries = [
            _make_entry("dir_a/img_002.jpg", "2025-01-02T10:00:00+01:00"),
            _make_entry("dir_a/img_001.jpg", "2025-01-01T10:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        result = sequences.load_files([str(json_file)], None)
        assert len(result) == 2
        assert result[0][2] == 1  # seq 1 first (earlier date)

    def test_filter(self, tmp_path: Path) -> None:
        """Test path filtering."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("dir_b/img_001.jpg", "2025-01-01T12:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        result = sequences.load_files([str(json_file)], ["dir_a"])
        assert len(result) == 1
        assert "dir_a" in result[0][0]

    def test_skips_files_without_seq(self, tmp_path: Path) -> None:
        """Test that files without sequence numbers are skipped."""
        entries = [
            _make_entry("dir_a/readme.txt", "2025-01-01T10:00:00+01:00"),
            _make_entry("dir_a/img_001.jpg", "2025-01-01T11:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        result = sequences.load_files([str(json_file)], None)
        assert len(result) == 1

    def test_pools_multiple_directories(self, tmp_path: Path) -> None:
        """Test that files from multiple directories are pooled together."""
        entries = [
            _make_entry("cam/100/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("cam/101/img_002.jpg", "2025-01-02T10:00:00+01:00"),
            _make_entry("cam/200/dsc_001.jpg", "2025-01-01T11:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        result = sequences.load_files([str(json_file)], None)
        assert len(result) == 3


@pytest.mark.unit
class TestSeqDirectories:
    """Tests for _seq_directories helper."""

    def test_returns_dirs_by_frequency(self) -> None:
        """Test that directories are ordered by frequency."""
        seq = [
            ("cam/100/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC)),
            ("cam/100/img_002.jpg", "img_", 2, datetime(2025, 1, 2, tzinfo=UTC)),
            ("cam/101/img_003.jpg", "img_", 3, datetime(2025, 1, 3, tzinfo=UTC)),
        ]
        dirs = sequences._seq_directories(seq)
        assert dirs[0] == "cam/100"
        assert "cam/101" in dirs


@pytest.mark.unit
class TestWriteScript:
    """Tests for write_script function."""

    def test_generates_move_commands(self, tmp_path: Path) -> None:
        """Test shell script generation for selected sequences."""
        seqs = [
            [("dir_a/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC))],
            [("dir_a/img_050.jpg", "img_", 50, datetime(2025, 1, 2, tzinfo=UTC))],
        ]
        script_path = str(tmp_path / "move.sh")
        sequences.write_script(seqs, [2], "dir_a", script_path)
        content = Path(script_path).read_text(encoding="utf-8")
        assert "#!/bin/bash" in content
        assert 'mkdir -p "dir_a_s2"' in content
        assert 'mv -iv "dir_a/img_050.jpg" "dir_a_s2/img_050.jpg"' in content
        assert "dir_a_s1" not in content

    def test_invalid_sequence_index(self, tmp_path: Path) -> None:
        """Test that invalid sequence index raises SystemExit."""
        seqs = [[("dir_a/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC))]]
        with pytest.raises(SystemExit, match="out of range"):
            sequences.write_script(seqs, [5], "dir_a", str(tmp_path / "move.sh"))

    def test_script_is_executable(self, tmp_path: Path) -> None:
        """Test that generated script has execute permission."""
        seqs = [
            [("dir_a/img_001.jpg", "img_", 1, datetime(2025, 1, 1, tzinfo=UTC))],
            [("dir_a/img_050.jpg", "img_", 50, datetime(2025, 1, 2, tzinfo=UTC))],
        ]
        script_path = tmp_path / "move.sh"
        sequences.write_script(seqs, [2], "dir_a", str(script_path))
        assert script_path.stat().st_mode & 0o111


# --- Integration tests ---


@pytest.mark.integration
class TestRun:
    """Integration tests for run() function."""

    def _make_archive(self, tmp_path: Path) -> Path:
        """Create archive JSON with mixed sequences spanning directories."""
        entries = [
            # Main sequence: 100/img_001 → 100/img_002 → 101/img_003
            _make_entry("cam/100/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("cam/100/img_002.jpg", "2025-01-01T11:00:00+01:00"),
            # Interleaved: seq drops back (new sequence from different camera)
            _make_entry("cam/100/dsc_001.jpg", "2025-01-01T12:00:00+01:00"),
            # Main continues in next directory
            _make_entry("cam/101/img_003.jpg", "2025-01-01T13:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        return json_file

    def test_default_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test default summary output."""
        json_file = self._make_archive(tmp_path)
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=None,
            select=None,
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "4 files, 2 sequences" in captured.out

    def test_single_sequence_no_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that a single monotonic sequence shows count only."""
        entries = [
            _make_entry("dir/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("dir/img_002.jpg", "2025-01-01T11:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=None,
            select=None,
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "1 sequence" in captured.out

    def test_list_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test columnar listing."""
        json_file = self._make_archive(tmp_path)
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=True,
            output=None,
            select=None,
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "Seq 1" in captured.out
        assert "Seq 2" in captured.out

    def test_list_shows_directory_in_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that columnar listing includes directory name."""
        json_file = self._make_archive(tmp_path)
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=True,
            output=None,
            select=None,
            target=None,
        )
        sequences.run(args)
        captured = capsys.readouterr()
        # Should show dir/filename, not just filename
        assert "100/" in captured.out or "101/" in captured.out

    def test_output_mode(self, tmp_path: Path) -> None:
        """Test shell script generation."""
        json_file = self._make_archive(tmp_path)
        script_path = str(tmp_path / "move.sh")
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=script_path,
            select=[2],
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        content = Path(script_path).read_text(encoding="utf-8")
        assert "mkdir -p" in content
        assert "mv -iv" in content

    def test_output_with_target(self, tmp_path: Path) -> None:
        """Test -o with explicit -t target directory."""
        json_file = self._make_archive(tmp_path)
        script_path = str(tmp_path / "move.sh")
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=script_path,
            select=[2],
            target="my_target",
        )
        sequences.run(args)
        content = Path(script_path).read_text(encoding="utf-8")
        assert 'mkdir -p "my_target_s2"' in content

    def test_select_requires_output(self, tmp_path: Path) -> None:
        """Test that -S without -o raises SystemExit."""
        json_file = self._make_archive(tmp_path)
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=None,
            select=[1],
            target=None,
        )
        with pytest.raises(SystemExit, match="-S/--select requires -o"):
            sequences.run(args)

    def test_filter_option(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test filtering by path narrows results."""
        entries = [
            _make_entry("cam/100/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("phone/img_001.jpg", "2025-01-01T12:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=["cam"],
            list=False,
            output=None,
            select=None,
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "1 file" in captured.out

    def test_cross_directory_sequence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that sequences spanning directories are detected correctly."""
        entries = [
            _make_entry("cam/100/img_001.jpg", "2025-01-01T10:00:00+01:00"),
            _make_entry("cam/100/img_002.jpg", "2025-01-01T11:00:00+01:00"),
            _make_entry("cam/101/img_003.jpg", "2025-01-01T12:00:00+01:00"),
            _make_entry("cam/101/img_004.jpg", "2025-01-01T13:00:00+01:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        args = argparse.Namespace(
            json_files=[str(json_file)],
            filter=None,
            list=False,
            output=None,
            select=None,
            target=None,
        )
        result = sequences.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "1 sequence" in captured.out
