#!/usr/bin/env python3
"""photos - Unified CLI for photo archive management tools.

This is the main entry point for the photos-manager CLI suite, providing
a unified interface to all photo management commands:
- mkjson: Generate JSON file with file metadata
- mkversion: Generate archive version information
- setmtime: Update file timestamps based on metadata
- verify: Verify archive integrity

Usage:
    photos mkjson /path/to/directory
    photos mkversion /path/to/archive
    photos setmtime archive.json
    photos verify /path/to/archive
"""

import argparse
import sys
from typing import cast

from photos_manager import mkjson, mkversion, setmtime, verify


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
        $ photos mkjson /path/to/photos
        $ photos mkversion /path/to/archive --output version.json
        $ photos setmtime archive.json --all
        $ photos verify /path/to/archive --all --check-timestamps
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
        version="photos-manager-cli 0.1.0",
    )

    # Create subparsers for each command
    subparsers = parser.add_subparsers(
        title="available commands",
        description="Photo archive management commands",
        dest="command",
        required=True,
        help="Command to execute",
    )

    # mkjson subcommand
    mkjson_parser = subparsers.add_parser(
        "mkjson",
        help="Generate JSON file with file metadata from directory",
        description="Generate JSON file with file metadata from directory",
    )
    mkjson.setup_parser(mkjson_parser)
    mkjson_parser.set_defaults(func=mkjson.run)

    # mkversion subcommand
    mkversion_parser = subparsers.add_parser(
        "mkversion",
        help="Generate archive version information",
        description="Generate version information from JSON files",
    )
    mkversion.setup_parser(mkversion_parser)
    mkversion_parser.set_defaults(func=mkversion.run)

    # setmtime subcommand
    setmtime_parser = subparsers.add_parser(
        "setmtime",
        help="Update file timestamps based on metadata",
        description="Set file and directory timestamps based on JSON metadata",
    )
    setmtime.setup_parser(setmtime_parser)
    setmtime_parser.set_defaults(func=setmtime.run)

    # verify subcommand
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify archive integrity",
        description="Verify archive integrity based on JSON metadata",
    )
    verify.setup_parser(verify_parser)
    verify_parser.set_defaults(func=verify.run)

    # Parse arguments and execute
    args = parser.parse_args()
    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())
