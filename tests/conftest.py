"""Shared pytest fixtures for photos_manager test suite."""

import argparse
import grp
import os
import pwd
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def current_user_and_group() -> tuple[str, str]:
    """Return (username, groupname) for the current process owner."""
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    return user, group


@pytest.fixture
def verify_args(tmp_path: Path) -> Callable[..., argparse.Namespace]:
    """Factory fixture that builds argparse.Namespace for verify run().

    Usage:
        def test_foo(self, verify_args):
            args = verify_args()                        # all defaults
            args = verify_args(all=True)                # override a field
            args = verify_args(directory="/custom/path")  # custom path
    """

    def _make(
        directory: str | None = None,
        all: bool = False,  # noqa: A002
        check_timestamps: bool = True,
        tolerance: int = 1,
        check_extra_files: bool = True,
        check_permissions: bool = True,
        owner: str | None = None,
        group: str | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            directory=directory if directory is not None else str(tmp_path),
            all=all,
            check_timestamps=check_timestamps,
            tolerance=tolerance,
            check_extra_files=check_extra_files,
            check_permissions=check_permissions,
            owner=owner,
            group=group,
        )

    return _make
