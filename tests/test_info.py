"""Tests for info module."""

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from photos_manager.common import format_date_verbose
from photos_manager.common import human_size as _human_size
from photos_manager.info import _date_span, _gather_stats, run

_Record = dict[str, str | int]


@pytest.fixture
def info_args(tmp_path: Path) -> Callable[..., argparse.Namespace]:
    """Factory fixture for info command Namespace objects."""

    def factory(**kwargs):
        defaults = {"directory": tmp_path, "stats": False, "top_n": 10}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    return factory


def _make_record(path: str, size: int, date: str) -> _Record:
    return {"path": path, "sha1": "abc", "md5": "def", "size": size, "date": date}


def _write_index(tmp_path: Path, name: str, records: list[_Record]) -> Path:
    f = tmp_path / name
    f.write_text(json.dumps(records), encoding="utf-8")
    return f


@pytest.mark.unit
class TestDateSpan:
    """Tests for _date_span helper."""

    @pytest.mark.parametrize(
        "date_min,date_max,expected",
        [
            ("2024-01-01", "2024-01-01", "0 days"),
            ("2024-01-01", "2024-01-02", "1 day"),
            ("2024-01-01", "2024-01-15", "14 days"),
            ("2024-01-01", "2024-01-31", "30 days"),
        ],
    )
    def test_days(self, date_min: str, date_max: str, expected: str) -> None:
        assert _date_span(date_min, date_max) == expected

    @pytest.mark.parametrize(
        "date_min,date_max,expected",
        [
            ("2024-01-01", "2024-02-01", "1 month"),
            ("2024-01-01", "2024-03-01", "2 months"),
            ("2024-01-01", "2024-12-01", "11 months"),
        ],
    )
    def test_months_only(self, date_min: str, date_max: str, expected: str) -> None:
        assert _date_span(date_min, date_max) == expected

    @pytest.mark.parametrize(
        "date_min,date_max,expected",
        [
            ("2023-01-01", "2024-01-01", "1 year"),
            ("2022-01-01", "2024-01-01", "2 years"),
        ],
    )
    def test_years_only(self, date_min: str, date_max: str, expected: str) -> None:
        assert _date_span(date_min, date_max) == expected

    @pytest.mark.parametrize(
        "date_min,date_max,expected",
        [
            ("2023-01-01", "2024-02-01", "1 year, 1 month"),
            ("2023-01-01", "2024-03-01", "1 year, 2 months"),
            ("2018-03-01", "2024-11-01", "6 years, 8 months"),
            ("2020-06-15", "2023-09-15", "3 years, 3 months"),
        ],
    )
    def test_years_and_months(self, date_min: str, date_max: str, expected: str) -> None:
        assert _date_span(date_min, date_max) == expected


@pytest.mark.unit
class TestHumanSize:
    """Tests for _human_size helper."""

    def test_bytes(self) -> None:
        assert _human_size(0) == "0 B"
        assert _human_size(1) == "1 B"
        assert _human_size(1023) == "1023 B"

    def test_kilobytes(self) -> None:
        assert _human_size(1024) == "1.0 kB"
        assert _human_size(2048) == "2.0 kB"
        assert _human_size(1024 * 1024 - 1).endswith("kB")

    def test_megabytes(self) -> None:
        assert _human_size(1024**2) == "1.0 MB"
        assert _human_size(1024**2 * 500) == "500.0 MB"

    def test_gigabytes(self) -> None:
        assert _human_size(1024**3) == "1.0 GB"
        assert _human_size(1024**3 * 2) == "2.0 GB"

    def test_terabytes(self) -> None:
        assert _human_size(1024**4) == "1.0 TB"
        assert _human_size(1024**4 * 3) == "3.0 TB"


@pytest.mark.unit
class TestTimeAgo:
    """Tests for _time_ago helper."""

    def _ts(self, seconds_ago: int) -> str:
        """Generate ISO 8601 timestamp N seconds in the past."""
        from datetime import UTC, datetime, timedelta

        dt = datetime.now(tz=UTC) - timedelta(seconds=seconds_ago)
        return dt.isoformat()

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (0, "0 seconds ago"),
            (1, "1 second ago"),
            (30, "30 seconds ago"),
            (59, "59 seconds ago"),
        ],
    )
    def test_seconds(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (60, "1 minute ago"),
            (120, "2 minutes ago"),
            (3599, "59 minutes ago"),
        ],
    )
    def test_minutes(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (3600, "1 hour ago"),
            (7200, "2 hours ago"),
            (86399, "23 hours ago"),
        ],
    )
    def test_hours(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (86400, "1 day ago"),
            (86400 * 2, "2 days ago"),
            (86400 * 29, "29 days ago"),
        ],
    )
    def test_days(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (86400 * 30, "1 month ago"),
            (86400 * 60, "2 months ago"),
        ],
    )
    def test_months(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    @pytest.mark.parametrize(
        "seconds_ago,expected",
        [
            (86400 * 365, "1 year ago"),
            (86400 * 730, "2 years ago"),
        ],
    )
    def test_years(self, seconds_ago: int, expected: str) -> None:
        assert expected in format_date_verbose(self._ts(seconds_ago))

    def test_future_timestamp(self) -> None:
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(tz=UTC) + timedelta(seconds=100)).isoformat()
        assert "just now" in format_date_verbose(future)


@pytest.mark.unit
class TestGatherStats:
    """Tests for _gather_stats function."""

    def test_basic_counts_and_sizes(self, tmp_path: Path) -> None:
        """Two index files produce correct aggregate totals."""
        f1 = _write_index(
            tmp_path,
            "a.json",
            [
                _make_record("/photos/a.jpg", 1000, "2022-06-01T10:00:00+00:00"),
                _make_record("/photos/b.jpg", 2000, "2023-01-15T12:00:00+00:00"),
            ],
        )
        f2 = _write_index(
            tmp_path,
            "b.json",
            [
                _make_record("/photos/c.jpg", 500, "2023-07-20T08:00:00+00:00"),
            ],
        )
        files = [f1, f2]
        records: dict[Path, list[_Record]] = {
            f1: [
                _make_record("/photos/a.jpg", 1000, "2022-06-01T10:00:00+00:00"),
                _make_record("/photos/b.jpg", 2000, "2023-01-15T12:00:00+00:00"),
            ],
            f2: [_make_record("/photos/c.jpg", 500, "2023-07-20T08:00:00+00:00")],
        }
        stats = _gather_stats(files, records)

        assert stats["total_files"] == 3
        assert stats["total_size"] == 3500
        assert stats["date_min"] == "2022-06-01"
        assert stats["date_max"] == "2023-07-20"
        assert stats["index_file_count"] == 2
        assert stats["grand_total_size"] == 3500 + stats["index_files_size"]
        assert len(stats["per_index"]) == 2

    def test_no_dates_does_not_crash(self, tmp_path: Path) -> None:
        """Records without a date field are counted but don't affect date range."""
        no_date_rec: _Record = {"path": "/x.jpg", "sha1": "a", "md5": "b", "size": 100}
        f1 = _write_index(tmp_path, "a.json", [no_date_rec])
        files = [f1]
        records: dict[Path, list[_Record]] = {f1: [no_date_rec]}
        stats = _gather_stats(files, records)

        assert stats["total_files"] == 1
        assert stats["total_size"] == 100
        assert stats["date_min"] is None
        assert stats["date_max"] is None
        assert stats["by_year"] == {}

    def test_extensions_grouped_correctly(self, tmp_path: Path) -> None:
        """Mixed extensions including case variants are grouped."""
        f1 = _write_index(
            tmp_path,
            "a.json",
            [
                _make_record("/a.JPG", 100, "2023-01-01T00:00:00+00:00"),
                _make_record("/b.jpg", 200, "2023-01-01T00:00:00+00:00"),
                _make_record("/c.mp4", 300, "2023-01-01T00:00:00+00:00"),
                _make_record("/noext", 50, "2023-01-01T00:00:00+00:00"),
            ],
        )
        files = [f1]
        records: dict[Path, list[_Record]] = {
            f1: [
                _make_record("/a.JPG", 100, "2023-01-01T00:00:00+00:00"),
                _make_record("/b.jpg", 200, "2023-01-01T00:00:00+00:00"),
                _make_record("/c.mp4", 300, "2023-01-01T00:00:00+00:00"),
                _make_record("/noext", 50, "2023-01-01T00:00:00+00:00"),
            ],
        }
        stats = _gather_stats(files, records)
        by_ext = stats["by_extension"]

        assert ".jpg" in by_ext
        assert by_ext[".jpg"][0] == 2  # both .JPG and .jpg
        assert by_ext[".jpg"][1] == 300
        assert ".mp4" in by_ext
        assert "(no ext)" in by_ext


@pytest.mark.integration
class TestRun:
    """Integration tests for run() entry point."""

    def test_run_ok(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """Basic run with two index files produces expected output."""
        data1 = [_make_record("/p/a.jpg", 1000, "2022-06-01T10:00:00+00:00")]
        data2 = [_make_record("/p/b.jpg", 2000, "2023-01-15T12:00:00+00:00")]
        _write_index(tmp_path, "photos_2022.json", data1)
        _write_index(tmp_path, "photos_2023.json", data2)

        result = run(info_args())

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "Archive:" in out
        assert str(tmp_path) in out
        assert "Total files:" in out
        assert "Grand total:" in out
        assert "Date range:" in out
        assert "2022-06-01" in out
        assert "2023-01-15" in out
        assert "Index files:" in out
        assert "photos_2022.json" in out
        assert "photos_2023.json" in out

    def test_run_with_version_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """Version/Last modified/Last verified lines appear when .version.json exists."""
        rec = _make_record("/a.jpg", 100, "2023-01-01T00:00:00+00:00")
        _write_index(tmp_path, "photos.json", [rec])

        version_data = {
            "version": "photos-0.100-001",
            "last_modified": "2025-12-30T12:34:56+00:00",
            "last_verified": "2025-12-30T13:45:23+00:00",
        }
        (tmp_path / ".version.json").write_text(json.dumps(version_data))

        result = run(info_args())

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "Version:" in out
        assert "photos-0.100-001" in out
        assert "Last modified:" in out
        assert "Last verified:" in out
        assert "ago" in out

    def test_run_without_version_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """Version/Last modified/Last verified lines absent when no .version.json."""
        rec = _make_record("/a.jpg", 100, "2023-01-01T00:00:00+00:00")
        _write_index(tmp_path, "photos.json", [rec])

        result = run(info_args())

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "Version:" not in out
        assert "Last modified:" not in out
        assert "Last verified:" not in out

    def test_run_stats_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """--stats flag shows By year and By extension sections."""
        data = [
            _make_record("/p/a.jpg", 1000, "2022-06-01T10:00:00+00:00"),
            _make_record("/p/b.mp4", 2000, "2023-01-15T12:00:00+00:00"),
        ]
        _write_index(tmp_path, "photos.json", data)

        result = run(info_args(stats=True))

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "By year:" in out
        assert "By extension:" in out
        assert "2022" in out
        assert "2023" in out
        assert ".jpg" in out
        assert ".mp4" in out

    def test_run_no_stats_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """Without --stats, By year and By extension sections are absent."""
        _write_index(
            tmp_path,
            "photos.json",
            [_make_record("/p/a.jpg", 1000, "2022-06-01T10:00:00+00:00")],
        )

        result = run(info_args(stats=False))

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "By year:" not in out
        assert "By extension:" not in out

    def test_run_no_json_files(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """Empty directory raises SystemExit."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(SystemExit) as exc_info:
            run(info_args(directory=empty_dir))

        assert "no JSON index files" in str(exc_info.value)

    def test_run_invalid_directory(
        self, tmp_path: Path, info_args: Callable[..., argparse.Namespace]
    ) -> None:
        """Non-existent path raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            run(info_args(directory=tmp_path / "nonexistent"))

        assert "does not exist" in str(exc_info.value) or "not a directory" in str(exc_info.value)

    def test_run_top_n_limits_rows(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        info_args: Callable[..., argparse.Namespace],
    ) -> None:
        """--top-n=2 truncates year table and shows '… and N more'."""
        data = [
            _make_record("/a.jpg", 100, f"{year}-01-01T00:00:00+00:00")
            for year in range(2018, 2025)  # 7 years
        ]
        _write_index(tmp_path, "photos.json", data)

        result = run(info_args(stats=True, top_n=2))

        assert result == os.EX_OK
        out = capsys.readouterr().out
        assert "and 5 more" in out
