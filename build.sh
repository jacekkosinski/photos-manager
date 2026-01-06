#!/usr/bin/env bash
# Build script for creating a standalone binary using Nuitka
#
# This script compiles the photos-manager CLI into a single binary
# using Nuitka for Linux amd64 architecture.
#
# Requirements:
#   - Python 3.12+
#   - Nuitka (pip install nuitka)
#   - GCC compiler (sudo apt-get install gcc g++ ccache patchelf)
#
# NOTE: If you're on Mac M2/ARM64, use Docker for AMD64 builds:
#   ./docker-build.sh          # Automated Docker build
#   docker-compose up          # Or use docker-compose
#   See BUILD.md for details
#
# Usage:
#   ./build.sh

set -e  # Exit on error

echo "Building photos-manager CLI with Nuitka..."
echo "Target: Linux amd64"
echo ""

# Check if nuitka is installed
if ! command -v python3 -m nuitka &> /dev/null; then
    echo "Error: Nuitka not found. Install it with:"
    echo "  pip install nuitka"
    exit 1
fi

# Create build directory
mkdir -p dist

# Build with Nuitka
python3 -m nuitka \
    --standalone \
    --onefile \
    --output-dir=dist \
    --output-filename=photos \
    --include-package=photos_manager \
    --python-flag=no_site \
    --python-flag=-O \
    --enable-plugin=no-qt \
    --assume-yes-for-downloads \
    --warn-implicit-exceptions \
    --warn-unusual-code \
    --report=nuitka-report.xml \
    photos_manager/cli.py

echo ""
echo "Build complete!"
echo "Binary location: dist/photos"
echo ""
echo "Test the binary:"
echo "  ./dist/photos --help"
echo "  ./dist/photos mkjson --help"
echo "  ./dist/photos mkversion --help"
echo "  ./dist/photos setmtime --help"
echo "  ./dist/photos verify --help"
