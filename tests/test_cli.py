"""Tests for CLI module."""

import argparse
import sys
from unittest.mock import patch

import pytest

from photos_manager import __version__
from photos_manager.cli import main


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
        assert "setmtime" in captured.out
        assert "verify" in captured.out


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


class TestSetmtimeSubcommand:
    """Tests for setmtime subcommand."""

    def test_setmtime_subcommand_calls_run_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that setmtime subcommand delegates to setmtime.run()."""
        with patch("photos_manager.setmtime.run", return_value=0) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "setmtime", "archive.json"])

            exit_code = main()

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert isinstance(args, argparse.Namespace)
            assert args.json_files == ["archive.json"]

    def test_setmtime_with_help_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that setmtime --help displays help message."""
        monkeypatch.setattr(sys, "argv", ["photos", "setmtime", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "setmtime" in captured.out
        assert "timestamp" in captured.out.lower() or "mtime" in captured.out.lower()

    def test_setmtime_returns_error_code_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that setmtime returns error code when run() fails."""
        with patch("photos_manager.setmtime.run", return_value=1) as mock_run:
            monkeypatch.setattr(sys, "argv", ["photos", "setmtime", "archive.json"])

            exit_code = main()

            assert exit_code == 1
            mock_run.assert_called_once()


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
            assert hasattr(args, "directory") or hasattr(args, "json_file")

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
