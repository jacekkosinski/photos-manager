#!/usr/bin/env python3
"""photos - Unified CLI for photo archive management tools.

This is the main entry point for the photos-manager CLI suite, providing
a unified interface to all photo management commands:
- prepare: Prepare directories for archiving (fix permissions, ownership, filenames)
- locate: Find archive directories for new photos based on timestamps
- index: Generate JSON file with file metadata
- fixdates: Fix file and directory dates to match JSON metadata
- manifest: Generate archive version information
- verify: Verify archive integrity
- info: Show archive statistics
- sync: Synchronize source and destination archives
- dedup: Find duplicate and missing files by comparing with archive

Usage:
    photos prepare /path/to/directory --dry-run
    photos locate /path/to/new/photos archive.json
    photos index /path/to/directory
    photos fixdates archive.json
    photos manifest /path/to/archive
    photos verify /path/to/archive
    photos info /path/to/archive
    photos sync /source/archive /dest/archive
    photos dedup archive.json /path/to/scan -d -m
"""

import argparse
import sys
from typing import cast

from photos_manager import (
    __version__,
    dedup,
    exifdates,
    fixdates,
    index,
    info,
    locate,
    manifest,
    prepare,
    series,
    sync,
    verify,
)


def main() -> int:
    """Main CLI entry point with subcommand dispatch.

    Creates a unified argument parser with subcommands for each tool.
    Delegates to the appropriate module's run() function based on the
    selected subcommand.

    Returns:
        int: Exit code from the executed subcommand
            - 0 (os.EX_OK): Successful execution
            - 1+: Error occurred during processing

    Examples:
        $ photos index /path/to/photos
        $ photos manifest /path/to/archive --output version.json
        $ photos fixdates archive.json --all
        $ photos verify /path/to/archive --all
    """
    # Create main parser
    parser = argparse.ArgumentParser(
        prog="photos",
        description="Unified CLI for photo archive management tools",
        epilog="Use 'photos <command> --help' for more information on a specific command.",
    )

    # Add version info
    parser.add_argument(
        "--version",
        action="version",
        version=f"photos-manager-cli {__version__}",
    )

    # Create subparsers for each command
    subparsers = parser.add_subparsers(
        title="available commands",
        description="Photo archive management commands",
        dest="command",
        required=True,
        help="Command to execute",
    )

    # prepare subcommand
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Prepare directories for archiving",
        description="Check and fix permissions, ownership, and filenames for archiving",
    )
    prepare.setup_parser(prepare_parser)
    prepare_parser.set_defaults(func=prepare.run)

    # locate subcommand
    locate_parser = subparsers.add_parser(
        "locate",
        help="Find archive directories for new photos based on timestamps",
        description="Find where new photos belong in archive by matching timestamps",
    )
    locate.setup_parser(locate_parser)
    locate_parser.set_defaults(func=locate.run)

    # index subcommand
    index_parser = subparsers.add_parser(
        "index",
        help="Generate JSON file with file metadata from directory",
        description="Generate JSON file with file metadata from directory",
    )
    index.setup_parser(index_parser)
    index_parser.set_defaults(func=index.run)

    # fixdates subcommand
    fixdates_parser = subparsers.add_parser(
        "fixdates",
        help="Fix file and directory dates to match JSON metadata",
        description="Fix file and directory timestamps to match JSON metadata",
    )
    fixdates.setup_parser(fixdates_parser)
    fixdates_parser.set_defaults(func=fixdates.run)

    # manifest subcommand
    manifest_parser = subparsers.add_parser(
        "manifest",
        help="Generate archive manifest information",
        description="Generate manifest information from JSON files",
    )
    manifest.setup_parser(manifest_parser)
    manifest_parser.set_defaults(func=manifest.run)

    # verify subcommand
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify archive integrity",
        description="Verify archive integrity based on JSON metadata",
    )
    verify.setup_parser(verify_parser)
    verify_parser.set_defaults(func=verify.run)

    # info subcommand
    info_parser = subparsers.add_parser(
        "info",
        help="Show archive statistics",
        description="Show human-readable statistics from JSON index files",
    )
    info.setup_parser(info_parser)
    info_parser.set_defaults(func=info.run)

    # sync subcommand
    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize source and destination archives",
        description="Generate minimal sync commands for archive synchronization",
    )
    sync.setup_parser(sync_parser)
    sync_parser.set_defaults(func=sync.run)

    # series subcommand
    series_parser = subparsers.add_parser(
        "series",
        help="Detect and separate interleaved photo series",
        description="Analyze archive directories for mixed camera series",
    )
    series.setup_parser(series_parser)
    series_parser.set_defaults(func=series.run)

    # exifdates subcommand
    exifdates_parser = subparsers.add_parser(
        "exifdates",
        help="Detect and fix JSON date fields from EXIF/GPS data",
        description="Compare EXIF/GPS timestamps against JSON metadata and optionally update JSON",
    )
    exifdates.setup_parser(exifdates_parser)
    exifdates_parser.set_defaults(func=exifdates.run)

    # dedup subcommand
    dedup_parser = subparsers.add_parser(
        "dedup",
        help="Find duplicate and missing files by comparing with archive",
        description="Find files that exist in archive (duplicates) and files not in archive",
    )
    dedup.setup_parser(dedup_parser)
    dedup_parser.set_defaults(func=dedup.run)

    # Parse arguments and execute
    args = parser.parse_args()
    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())
