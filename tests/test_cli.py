"""Tests for CLI module."""

import argparse
import sys
from unittest.mock import patch

import pytest

from photos_manager import __version__
from photos_manager.cli import main


@pytest.mark.integration
class TestMainFunction:
    """Tests for main() function."""

    def test_main_with_no_arguments_exits_with_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that calling main without arguments exits with error."""
        monkeypatch.setattr(sys, "argv", ["photos"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2  # argparse exits with 2 for invalid args
        captured = capsys.readouterr()
        assert "required" in captured.err.lower() or "following arguments" in captured.err.lower()

    def test_main_with_version_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that --version flag displays version and exits."""
        monkeypatch.setattr(sys, "argv", ["photos", "--version"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out
        assert "photos-manager-cli" in captured.out

    def test_main_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that --help flag displays help message and exits."""
        monkeypatch.setattr(sys, "argv", ["photos", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "photos" in captured.out
        assert "index" in captured.out
        assert "manifest" in captured.out
        assert "fixdates" in captured.out
        assert "verify" in captured.out


@pytest.mark.integration
class TestIndexSubcommand:
    """Tests for index subcommand."""

    def test_index_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that index subcommand delegates to index.run()."""
        with patch("photos_manager.index.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "index", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directory == "/test/path"

    def test_index_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that index --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "index", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "index" in captured.out
        assert "JSON" in captured.out or "metadata" in captured.out

    def test_index_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that index returns error code when run() fails."""
        with patch("photos_manager.index.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "index", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestManifestSubcommand:
    """Tests for manifest subcommand."""

    def test_manifest_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that manifest subcommand delegates to manifest.run()."""
        with patch("photos_manager.manifest.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "manifest", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directory == "/test/path"

    def test_manifest_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that manifest --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "manifest", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "manifest" in captured.out
        assert "version" in captured.out.lower() or "manifest" in captured.out.lower()

    def test_manifest_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that manifest returns error code when run() fails."""
        with patch("photos_manager.manifest.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "manifest", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestFixdatesSubcommand:
    """Tests for fixdates subcommand."""

    def test_fixdates_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that fixdates subcommand delegates to fixdates.run()."""
        with patch("photos_manager.fixdates.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "fixdates", "archive.json"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.json_files == ["archive.json"]

    def test_fixdates_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that fixdates --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "fixdates", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "fixdates" in captured.out
        assert "timestamp" in captured.out.lower() or "mtime" in captured.out.lower()

    def test_fixdates_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that fixdates returns error code when run() fails."""
        with patch("photos_manager.fixdates.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "fixdates", "archive.json"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestVerifySubcommand:
    """Tests for verify subcommand."""

    def test_verify_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that verify subcommand delegates to verify.run()."""
        with patch("photos_manager.verify.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "verify", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directory == "/test/path"

    def test_verify_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that verify --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "verify", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "verify" in captured.out
        assert "integrity" in captured.out.lower() or "verify" in captured.out.lower()

    def test_verify_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that verify returns error code when run() fails."""
        with patch("photos_manager.verify.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "verify", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestFindSubcommand:
    """Tests for find subcommand."""

    def test_find_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that find subcommand delegates to find.run()."""
        with patch("photos_manager.find.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "find", "archive.json", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.json_file == "archive.json"

    def test_find_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that find --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "find", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "find" in captured.out
        assert "archive" in captured.out.lower() or "duplicate" in captured.out.lower()

    def test_find_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that find returns error code when run() fails."""
        with patch("photos_manager.find.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "find", "archive.json", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestPrepareSubcommand:
    """Tests for prepare subcommand."""

    def test_prepare_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that prepare subcommand delegates to prepare.run()."""
        with patch("photos_manager.prepare.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "prepare", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directories == ["/test/path"]

    def test_prepare_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that prepare --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "prepare", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "prepare" in captured.out
        assert "permission" in captured.out.lower() or "ownership" in captured.out.lower()

    def test_prepare_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that prepare returns error code when run() fails."""
        with patch("photos_manager.prepare.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "prepare", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestLocateSubcommand:
    """Tests for locate subcommand."""

    def test_locate_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that locate subcommand delegates to locate.run()."""
        with patch("photos_manager.locate.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "locate", "/test/path", "archive.json"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directory == "/test/path"
            assert args.json_files == ["archive.json"]

    def test_locate_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that locate --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "locate", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "locate" in captured.out
        assert "archive" in captured.out.lower() or "timestamp" in captured.out.lower()

    def test_locate_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that locate returns error code when run() fails."""
        with patch("photos_manager.locate.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "locate", "/test/path", "archive.json"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestSeriesSubcommand:
    """Tests for series subcommand."""

    def test_series_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that series subcommand delegates to series.run()."""
        with patch("photos_manager.series.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "series", "archive.json"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.json_files == ["archive.json"]

    def test_series_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that series --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "series", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "series" in captured.out

    def test_series_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that series returns error code when run() fails."""
        with patch("photos_manager.series.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "series", "archive.json"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestExifdatesSubcommand:
    """Tests for exifdates subcommand."""

    def test_exifdates_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that exifdates subcommand delegates to exifdates.run()."""
        with patch("photos_manager.exifdates.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "exifdates", "archive.json"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.json_file == "archive.json"

    def test_exifdates_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that exifdates --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "exifdates", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "exifdates" in captured.out
        assert "exif" in captured.out.lower() or "date" in captured.out.lower()

    def test_exifdates_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that exifdates returns error code when run() fails."""
        with patch("photos_manager.exifdates.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "exifdates", "archive.json"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestInfoSubcommand:
    """Tests for info subcommand."""

    def test_info_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that info subcommand delegates to info.run()."""
        with patch("photos_manager.info.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "info", "/test/path"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.directory == "/test/path"

    def test_info_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that info --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "info", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "info" in captured.out
        assert "statistic" in captured.out.lower() or "archive" in captured.out.lower()

    def test_info_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that info returns error code when run() fails."""
        with patch("photos_manager.info.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "info", "/test/path"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestSyncSubcommand:
    """Tests for sync subcommand."""

    def test_sync_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that sync subcommand delegates to sync.run()."""
        with patch("photos_manager.sync.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "sync", "/source", "/dest"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.source == "/source"
            assert args.dest == "/dest"

    def test_sync_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that sync --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "sync", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "sync" in captured.out
        assert "source" in captured.out.lower() or "synchronize" in captured.out.lower()

    def test_sync_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that sync returns error code when run() fails."""
        with patch("photos_manager.sync.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "sync", "/source", "/dest"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


@pytest.mark.integration
class TestInvalidSubcommand:
    """Tests for invalid subcommand handling."""

    def test_invalid_subcommand_exits_with_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that invalid subcommand exits with error."""
        monkeypatch.setattr(sys, "argv", ["photos", "invalid_command"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err.lower()
