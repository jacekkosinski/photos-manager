"""Tests for photos_manager.locate module."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from photos_manager import locate


def _make_entry(path: str, date: str, size: int = 1000) -> dict[str, str | int]:
    """Create a minimal JSON metadata entry."""
    return {
        "path": path,
        "sha1": "a" * 40,
        "md5": "b" * 32,
        "date": date,
        "size": size,
    }


SAMPLE_ENTRIES = [
    _make_entry("camera/100/img_001.jpg", "2025-07-07T10:00:00+02:00"),
    _make_entry("camera/100/img_002.jpg", "2025-07-07T10:05:00+02:00"),
    _make_entry("camera/100/img_003.jpg", "2025-07-07T10:10:00+02:00"),
    _make_entry("camera/101/img_004.jpg", "2025-07-07T12:00:00+02:00"),
    _make_entry("camera/101/img_005.jpg", "2025-07-07T12:05:00+02:00"),
    _make_entry("camera/101/img_006.jpg", "2025-07-07T12:10:00+02:00"),
    _make_entry("phone/202507/img_100.jpg", "2025-07-07T14:00:00+02:00"),
    _make_entry("phone/202507/img_101.jpg", "2025-07-07T14:05:00+02:00"),
]


def _build_sorted_entries(
    entries: list[dict[str, str | int]],
) -> list[tuple[datetime, dict[str, str | int]]]:
    """Convert raw entries to sorted (datetime, entry) tuples."""
    result = []
    for entry in entries:
        dt = datetime.fromisoformat(str(entry["date"]))
        result.append((dt, entry))
    result.sort(key=lambda x: x[0])
    return result


# --- Unit tests ---


@pytest.mark.unit
class TestLoadArchiveEntries:
    """Tests for load_archive_entries function."""

    def test_loads_and_sorts(self, tmp_path: Path) -> None:
        """Test loading entries from JSON file."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        result = locate.load_archive_entries([str(json_file)], None)
        assert len(result) == len(SAMPLE_ENTRIES)
        dates = [dt for dt, _ in result]
        assert dates == sorted(dates)

    def test_filter(self, tmp_path: Path) -> None:
        """Test filtering entries by path substring."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        result = locate.load_archive_entries([str(json_file)], ["phone"])
        assert len(result) == 2
        for _, entry in result:
            assert "phone" in str(entry["path"])

    def test_filter_multiple_or(self, tmp_path: Path) -> None:
        """Test multiple filters combined with OR logic."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        result = locate.load_archive_entries([str(json_file)], ["phone", "101"])
        # phone/202507 (2 entries) + camera/101 (3 entries) = 5
        assert len(result) == 5

    def test_multiple_json_files(self, tmp_path: Path) -> None:
        """Test loading from multiple JSON files."""
        json1 = tmp_path / "a.json"
        json2 = tmp_path / "b.json"
        json1.write_text(json.dumps(SAMPLE_ENTRIES[:3]), encoding="utf-8")
        json2.write_text(json.dumps(SAMPLE_ENTRIES[3:]), encoding="utf-8")
        result = locate.load_archive_entries([str(json1), str(json2)], None)
        assert len(result) == len(SAMPLE_ENTRIES)


@pytest.mark.unit
class TestScanNewFiles:
    """Tests for scan_new_files function."""

    def test_scans_directory(self, tmp_path: Path) -> None:
        """Test scanning directory for files."""
        (tmp_path / "a.jpg").write_text("data")
        (tmp_path / "b.jpg").write_text("data")
        result = locate.scan_new_files(str(tmp_path))
        assert len(result) == 2
        names = [Path(p).name for p, _ in result]
        assert "a.jpg" in names
        assert "b.jpg" in names

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        """Test that files in subdirectories are found recursively."""
        (tmp_path / "file.jpg").write_text("data")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.jpg").write_text("data")
        result = locate.scan_new_files(str(tmp_path))
        assert len(result) == 2
        names = [Path(p).name for p, _ in result]
        assert "file.jpg" in names
        assert "nested.jpg" in names

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning empty directory."""
        result = locate.scan_new_files(str(tmp_path))
        assert result == []


@pytest.mark.unit
class TestWriteScript:
    """Tests for _write_script function."""

    def test_generates_script(self, tmp_path: Path) -> None:
        """Test shell script generation."""
        script_path = str(tmp_path / "move.sh")
        placements = [
            ("/new/a.jpg", "camera/100"),
            ("/new/b.jpg", "camera/101"),
        ]
        locate._write_script(placements, script_path)
        content = Path(script_path).read_text(encoding="utf-8")
        assert "#!/bin/bash" in content
        assert 'mkdir -p "camera/100"' in content
        assert 'mkdir -p "camera/101"' in content
        assert 'mv -iv "/new/a.jpg" "camera/100/a.jpg"' in content
        assert 'mv -iv "/new/b.jpg" "camera/101/b.jpg"' in content

    def test_script_is_executable(self, tmp_path: Path) -> None:
        """Test that generated script has execute permission."""
        script_path = str(tmp_path / "move.sh")
        locate._write_script([("/new/a.jpg", "dir")], script_path)
        mode = Path(script_path).stat().st_mode
        assert mode & 0o111


# --- New series-based algorithm unit tests ---


def _dt(time_str: str) -> datetime:
    """Create a timezone-aware datetime for 2025-07-07 at given HH:MM."""
    h, m = time_str.split(":")
    return datetime(2025, 7, 7, int(h), int(m), 0, tzinfo=timezone(timedelta(hours=2)))


def _nf(
    name: str,
    time_str: str,
    prefix: str | None = None,
    seq: int | None = None,
) -> locate.NewFile:
    """Create a NewFile for testing."""
    return locate.NewFile(path=f"/new/{name}", prefix=prefix, seq=seq, date=_dt(time_str))


@pytest.mark.unit
class TestGroupIntoSeries:
    """Tests for group_into_series function."""

    def test_single_prefix(self) -> None:
        """Test grouping files with the same prefix."""
        files = [
            ("/new/img_004.jpg", _dt("10:00")),
            ("/new/img_005.jpg", _dt("10:05")),
            ("/new/img_007.jpg", _dt("10:10")),
        ]
        result = locate.group_into_series(files)
        assert len(result) == 1
        assert result[0].prefix == "img_"
        assert result[0].seq_range == (4, 7)
        assert len(result[0].files) == 3

    def test_multiple_prefixes(self) -> None:
        """Test grouping files with different prefixes."""
        files = [
            ("/new/img_004.jpg", _dt("10:00")),
            ("/new/dsc_101.jpg", _dt("14:00")),
            ("/new/img_005.jpg", _dt("10:05")),
            ("/new/dsc_102.jpg", _dt("14:05")),
        ]
        result = locate.group_into_series(files)
        assert len(result) == 2
        prefixes = [s.prefix for s in result]
        assert "dsc_" in prefixes
        assert "img_" in prefixes

    def test_files_without_seq(self) -> None:
        """Test that files without sequence numbers become individual series."""
        files = [
            ("/new/notes.txt", _dt("09:00")),
            ("/new/readme.md", _dt("09:30")),
        ]
        result = locate.group_into_series(files)
        assert len(result) == 2
        for s in result:
            assert s.prefix is None
            assert s.seq_range is None
            assert len(s.files) == 1

    def test_mixed_seq_and_no_seq(self) -> None:
        """Test mix of files with and without sequence numbers."""
        files = [
            ("/new/img_004.jpg", _dt("10:00")),
            ("/new/notes.txt", _dt("09:00")),
            ("/new/img_005.jpg", _dt("10:05")),
        ]
        result = locate.group_into_series(files)
        assert len(result) == 2
        # Prefixed series first, then None
        assert result[0].prefix == "img_"
        assert result[1].prefix is None

    def test_gaps_in_series(self) -> None:
        """Test that gaps in numbering are allowed within a series."""
        files = [
            ("/new/img_004.jpg", _dt("10:00")),
            ("/new/img_005.jpg", _dt("10:05")),
            ("/new/img_009.jpg", _dt("10:30")),
            ("/new/img_010.jpg", _dt("10:35")),
        ]
        result = locate.group_into_series(files)
        assert len(result) == 1
        assert result[0].seq_range == (4, 10)
        assert len(result[0].files) == 4

    def test_empty_input(self) -> None:
        """Test empty input returns empty list."""
        assert locate.group_into_series([]) == []


@pytest.mark.unit
class TestSplitSeriesAgainstArchive:
    """Tests for split_series_against_archive function."""

    def _make_dir_seqs(
        self, entries: list[dict[str, str | int]]
    ) -> dict[str, list[tuple[str | None, int]]]:
        """Build dir_seqs from entries."""
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        return locate.build_directory_seqs(dir_entries)

    def test_no_collisions(self) -> None:
        """Test series with no collisions passes through unchanged."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs = self._make_dir_seqs(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "10:15", "img_", 4), _nf("img_005.jpg", "10:20", "img_", 5)],
            seq_range=(4, 5),
        )
        sub, collisions = locate.split_series_against_archive(series, dir_seqs)
        assert len(sub) == 1
        assert len(collisions) == 0
        assert sub[0].seq_range == (4, 5)

    def test_collision_splits_series(self) -> None:
        """Test that archive entries within range split the series."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_006.jpg", "2025-07-07T11:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs = self._make_dir_seqs(entries)
        series = locate.Series(
            prefix="img_",
            files=[
                _nf("img_004.jpg", "10:15", "img_", 4),
                _nf("img_005.jpg", "10:20", "img_", 5),
                _nf("img_007.jpg", "10:30", "img_", 7),
                _nf("img_009.jpg", "10:40", "img_", 9),
            ],
            seq_range=(4, 9),
        )
        sub, collisions = locate.split_series_against_archive(series, dir_seqs)
        assert len(collisions) == 0  # no new files with seq 6
        assert len(sub) == 2
        assert sub[0].seq_range == (4, 5)
        assert sub[1].seq_range == (7, 9)

    def test_collision_with_new_file(self) -> None:
        """Test collision when new file has same seq as archive entry."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_007.jpg", "2025-07-07T11:00:00+02:00"),
            _make_entry("dir_a/img_008.jpg", "2025-07-07T11:30:00+02:00"),
            _make_entry("dir_a/img_020.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        dir_seqs = self._make_dir_seqs(entries)
        series = locate.Series(
            prefix="img_",
            files=[
                _nf("img_004.jpg", "10:15", "img_", 4),
                _nf("img_005.jpg", "10:20", "img_", 5),
                _nf("img_007.jpg", "10:30", "img_", 7),
                _nf("img_009.jpg", "10:40", "img_", 9),
                _nf("img_010.jpg", "10:45", "img_", 10),
            ],
            seq_range=(4, 10),
        )
        sub, collisions = locate.split_series_against_archive(series, dir_seqs)
        assert len(collisions) == 1
        assert collisions[0].new_file.seq == 7
        assert len(sub) == 2
        assert sub[0].seq_range == (4, 5)
        assert sub[1].seq_range == (9, 10)

    def test_all_collisions(self) -> None:
        """Test when all new files collide with archive."""
        entries = [
            _make_entry("dir_a/img_004.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_005.jpg", "2025-07-07T10:05:00+02:00"),
        ]
        dir_seqs = self._make_dir_seqs(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "10:15", "img_", 4), _nf("img_005.jpg", "10:20", "img_", 5)],
            seq_range=(4, 5),
        )
        sub, collisions = locate.split_series_against_archive(series, dir_seqs)
        assert len(sub) == 0
        assert len(collisions) == 2

    def test_single_file_series_passthrough(self) -> None:
        """Test that single-element series (no seq) passes through."""
        entries = [_make_entry("dir_a/img_001.jpg", "2025-07-07T10:00:00+02:00")]
        dir_seqs = self._make_dir_seqs(entries)
        series = locate.Series(prefix=None, files=[_nf("notes.txt", "09:00")], seq_range=None)
        sub, collisions = locate.split_series_against_archive(series, dir_seqs)
        assert len(sub) == 1
        assert len(collisions) == 0


@pytest.mark.unit
class TestFindGapMatch:
    """Tests for find_gap_match function."""

    def _build_indexes(
        self, entries: list[dict[str, str | int]]
    ) -> tuple[
        dict[str, list[tuple[str | None, int]]],
        dict[str, list[tuple[datetime, dict[str, str | int]]]],
    ]:
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        dir_seqs = locate.build_directory_seqs(dir_entries)
        return dir_seqs, dir_entries

    def test_finds_gap_in_single_directory(self) -> None:
        """Test finding a gap in one directory."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_003.jpg", "2025-07-07T09:10:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4), _nf("img_005.jpg", "09:20", "img_", 5)],
            seq_range=(4, 5),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 1
        assert result[0].directory == "dir_a"
        assert result[0].gap == (3, 10)
        assert result[0].time_ok is True

    def test_tightest_gap_wins(self) -> None:
        """Test that the directory with tightest gap is first."""
        entries = [
            # dir_a: gap 3..10 (size 7)
            _make_entry("dir_a/img_003.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
            # dir_b: gap 4..6 (size 2)
            _make_entry("dir_b/img_004.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_b/img_006.jpg", "2025-07-07T10:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_005.jpg", "09:30", "img_", 5)],
            seq_range=(5, 5),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 2
        assert result[0].directory == "dir_b"  # tighter gap

    def test_time_validation_failure(self) -> None:
        """Test that time validation detects wrong ordering."""
        entries = [
            _make_entry("dir_a/img_003.jpg", "2025-08-01T14:00:00+02:00"),  # AFTER new files
            _make_entry("dir_a/img_010.jpg", "2025-08-01T15:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4)],
            seq_range=(4, 4),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 1
        assert result[0].time_ok is False

    def test_no_gap_found(self) -> None:
        """Test when archive has entries in the series range."""
        entries = [
            _make_entry("dir_a/img_003.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_005.jpg", "2025-07-07T09:30:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4), _nf("img_006.jpg", "09:45", "img_", 6)],
            seq_range=(4, 6),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 0  # img_005 blocks the gap

    def test_prefix_mismatch_ignored(self) -> None:
        """Test that entries with different prefix are ignored."""
        entries = [
            _make_entry("dir_a/dsc_003.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/dsc_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4)],
            seq_range=(4, 4),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 0  # no img_ entries in any directory

    def test_no_prefix_mode(self) -> None:
        """Test that match_prefix=False ignores prefix when finding gaps."""
        entries = [
            _make_entry("dir_a/dsc_003.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/dsc_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4)],
            seq_range=(4, 4),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries, match_prefix=False)
        assert len(result) == 1
        assert result[0].directory == "dir_a"

    def test_one_sided_gap_start(self) -> None:
        """Test gap at start of archive (no before_seq)."""
        entries = [
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_020.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(
            prefix="img_",
            files=[_nf("img_004.jpg", "09:15", "img_", 4)],
            seq_range=(4, 4),
        )
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert len(result) == 1
        assert result[0].gap == (None, 10)
        assert result[0].time_ok is True

    def test_single_element_series_returns_empty(self) -> None:
        """Test that series without seq returns no gap matches."""
        entries = [_make_entry("dir_a/img_001.jpg", "2025-07-07T10:00:00+02:00")]
        dir_seqs, dir_entries = self._build_indexes(entries)
        series = locate.Series(prefix=None, files=[_nf("notes.txt", "09:00")], seq_range=None)
        result = locate.find_gap_match(series, dir_seqs, dir_entries)
        assert result == []


@pytest.mark.unit
class TestMatchSingleFile:
    """Tests for match_single_file function."""

    def test_finds_closest_directory(self) -> None:
        """Test matching by timestamp proximity."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES)
        nf = _nf("notes.txt", "10:07")
        result = locate.match_single_file(nf, sorted_entries, 5)
        assert result == "camera/100"

    def test_no_entries(self) -> None:
        """Test with empty archive."""
        nf = _nf("notes.txt", "10:07")
        result = locate.match_single_file(nf, [], 5)
        assert result is None


@pytest.mark.unit
class TestReadFileDate:
    """Tests for read_file_date function."""

    def test_reads_mtime(self, tmp_path: Path) -> None:
        """Test reading file date from mtime."""
        f = tmp_path / "test.jpg"
        f.write_text("data")
        result = locate.read_file_date(str(f))
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_exif_fallback_to_mtime(self, tmp_path: Path) -> None:
        """Test that --exif falls back to mtime for non-image files."""
        f = tmp_path / "test.txt"
        f.write_text("data")
        result = locate.read_file_date(str(f), use_exif=True)
        assert isinstance(result, datetime)


# --- Integration tests ---


def _make_args(**kwargs: object) -> argparse.Namespace:
    """Create a Namespace with default locate args, overridden by kwargs."""
    defaults: dict[str, object] = {
        "directory": "",
        "json_files": [],
        "list": False,
        "context": 5,
        "filter": None,
        "output": None,
        "no_prefix": False,
        "exif": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.integration
class TestRun:
    """Integration tests for run() function."""

    def _setup_archive(self, tmp_path: Path) -> Path:
        """Create a JSON archive file with sample entries."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        return json_file

    def _setup_new_files(
        self, tmp_path: Path, files: list[tuple[str, float]] | None = None
    ) -> Path:
        """Create a directory with new files having specific mtimes."""
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        if files is None:
            # Default: img_002 at 10:07 UTC — fits in camera/100 gap
            f = new_dir / "img_002.jpg"
            f.write_text("photo data")
            target_ts = datetime(2025, 7, 7, 8, 7, 0, tzinfo=UTC).timestamp()
            os.utime(f, (target_ts, target_ts))
        else:
            for name, ts in files:
                f = new_dir / name
                f.write_text("data")
                os.utime(f, (ts, ts))
        return new_dir

    def test_default_mode_gap_match(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test default mode finds gap match for a series."""
        # Archive: img_001..003 in camera/100, img_004..006 in camera/101
        # New file: img_002 — BUT seq 2 already in archive → collision
        # Use distinct numbers instead
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 9, 30, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_005.jpg", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out

    def test_list_mode_shows_context(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test list mode shows archive context around gap."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 9, 30, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_005.jpg", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)], list=True)
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert ">" in captured.out
        assert " <" in captured.out
        assert "dir_a" in captured.out
        assert "gap" in captured.out

    def test_output_mode_generates_script(self, tmp_path: Path) -> None:
        """Test output mode generates shell script."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 9, 30, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_005.jpg", ts)])
        script_path = str(tmp_path / "move.sh")
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)], output=script_path)
        result = locate.run(args)
        assert result == os.EX_OK
        content = Path(script_path).read_text(encoding="utf-8")
        assert "mkdir -p" in content
        assert "mv -iv" in content

    def test_output_mode_refuses_ambiguous(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test -o mode refuses to write script when placement is ambiguous."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+00:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+00:00"),
            _make_entry("dir_b/img_001.jpg", "2025-07-07T09:30:00+00:00"),
            _make_entry("dir_b/img_010.jpg", "2025-07-07T11:30:00+00:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 10, 0, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_005.jpg", ts)])
        script_path = str(tmp_path / "move.sh")
        args = _make_args(
            directory=str(new_dir),
            json_files=[str(json_file)],
            output=script_path,
            no_prefix=True,
        )
        with pytest.raises(SystemExit, match="Use -f to narrow results"):
            locate.run(args)
        captured = capsys.readouterr()
        assert "Ambiguous" in captured.err

    def test_gap_match_narrows_to_correct_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test gap-fitting narrows to the directory with matching seq gap."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+00:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+00:00"),
            _make_entry("dir_b/img_200.jpg", "2025-07-07T10:30:00+00:00"),
            _make_entry("dir_b/img_210.jpg", "2025-07-07T11:30:00+00:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 11, 0, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_105.jpg", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out
        assert "dir_b" not in captured.out

    def test_outside_range_one_sided_gap(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test matching files before archive range via one-sided gap."""
        entries = [
            _make_entry("dir_a/img_200.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_210.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 8, 0, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_190.jpg", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out

    def test_filter_option(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test filter restricts archive entries by path."""
        json_file = self._setup_archive(tmp_path)
        ts = datetime(2025, 7, 7, 12, 2, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_100.jpg", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)], filter=["phone"])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "phone" in captured.out

    def test_invalid_directory(self) -> None:
        """Test that invalid directory raises SystemExit."""
        args = _make_args(directory="/nonexistent", json_files=["a.json"])
        with pytest.raises(SystemExit, match="does not exist"):
            locate.run(args)

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test that empty directory raises SystemExit."""
        json_file = self._setup_archive(tmp_path)
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = _make_args(directory=str(empty_dir), json_files=[str(json_file)])
        with pytest.raises(SystemExit, match="No files found"):
            locate.run(args)

    def test_no_prefix_matches_across_prefixes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --no-prefix matches img_ series against dsc_ gap."""
        entries = [
            _make_entry("dir_a/dsc_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/dsc_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts = datetime(2025, 7, 7, 10, 30, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("img_105.jpg", ts)])
        # Default (prefix matching on): no match because img_ != dsc_
        args_default = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        locate.run(args_default)
        captured = capsys.readouterr()
        assert "no match found" in captured.out
        # With --no-prefix: matches
        args_no_prefix = _make_args(
            directory=str(new_dir), json_files=[str(json_file)], no_prefix=True
        )
        locate.run(args_no_prefix)
        captured = capsys.readouterr()
        assert "dir_a" in captured.out

    def test_collision_detection(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that collisions are detected and reported."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_005.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts1 = datetime(2025, 7, 7, 9, 15, 0, tzinfo=UTC).timestamp()
        ts2 = datetime(2025, 7, 7, 9, 30, 0, tzinfo=UTC).timestamp()
        ts3 = datetime(2025, 7, 7, 10, 30, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(
            tmp_path,
            [
                ("img_003.jpg", ts1),
                ("img_005.jpg", ts2),  # collision!
                ("img_007.jpg", ts3),
            ],
        )
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "Collision" in captured.out
        assert "img_005.jpg" in captured.out
        # Sub-series should still match
        assert "dir_a" in captured.out

    def test_single_file_timestamp_fallback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test file without seq number uses timestamp fallback."""
        json_file = self._setup_archive(tmp_path)
        ts = datetime(2025, 7, 7, 8, 7, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(tmp_path, [("notes.txt", ts)])
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "camera/100" in captured.out
        assert "timestamp" in captured.out

    def test_series_grouping_in_default_mode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that multiple files with same prefix are grouped into one series."""
        entries = [
            _make_entry("dir_a/img_001.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_a/img_010.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        ts1 = datetime(2025, 7, 7, 9, 15, 0, tzinfo=UTC).timestamp()
        ts2 = datetime(2025, 7, 7, 9, 30, 0, tzinfo=UTC).timestamp()
        ts3 = datetime(2025, 7, 7, 9, 45, 0, tzinfo=UTC).timestamp()
        new_dir = self._setup_new_files(
            tmp_path,
            [
                ("img_004.jpg", ts1),
                ("img_005.jpg", ts2),
                ("img_007.jpg", ts3),
            ],
        )
        args = _make_args(directory=str(new_dir), json_files=[str(json_file)])
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "img_[4..7]" in captured.out
        assert "3 files" in captured.out
        assert "dir_a" in captured.out
