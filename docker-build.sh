#!/usr/bin/env bash
# Docker build script for AMD64 binary on Mac M2 (ARM64)
#
# This script:
# - Checks Docker and buildx availability
# - Creates/configures multi-platform builder
# - Builds AMD64 binary using Docker
# - Extracts binary to dist/ directory
# - Verifies architecture
#
# Usage:
#   ./docker-build.sh

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
error() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

success() {
    echo -e "${GREEN}$1${NC}"
}

warning() {
    echo -e "${YELLOW}Warning: $1${NC}"
}

info() {
    echo -e "$1"
}

# Banner
echo "========================================"
echo "photos-manager Docker Build for AMD64"
echo "========================================"
echo ""

# Check if Docker is running
info "Checking Docker availability..."
if ! docker info > /dev/null 2>&1; then
    error "Docker is not running. Please start Docker Desktop."
fi
success "✓ Docker is running"

# Check Docker version
DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
info "Docker version: $DOCKER_VERSION"

# Ensure buildx is available
info "Checking buildx availability..."
if ! docker buildx version > /dev/null 2>&1; then
    error "Docker buildx not available. Please update Docker Desktop to latest version."
fi
success "✓ buildx is available"

# Create or use existing builder
BUILDER_NAME="multiarch"
info "Configuring multi-platform builder..."

if docker buildx inspect "$BUILDER_NAME" > /dev/null 2>&1; then
    info "Using existing builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
else
    info "Creating new builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
    docker buildx inspect --bootstrap
fi
success "✓ Builder configured"

# Clean previous build artifacts
info "Cleaning previous build artifacts..."
rm -rf dist-docker
mkdir -p dist

# Build the image
echo ""
echo "========================================"
echo "Building Docker image..."
echo "This may take 5-10 minutes on first run"
echo "Subsequent builds will be faster (cache)"
echo "========================================"
echo ""

docker buildx build \
    --platform=linux/amd64 \
    --target builder \
    --progress=plain \
    --output type=local,dest=./dist-docker \
    . || error "Docker build failed"

echo ""
success "✓ Docker build completed"

# Extract binary
info "Extracting binary from build output..."
BINARY_SRC="dist-docker/build/dist/photos"

if [ ! -f "$BINARY_SRC" ]; then
    error "Binary not found at $BINARY_SRC"
fi

cp "$BINARY_SRC" dist/photos
rm -rf dist-docker
success "✓ Binary extracted to dist/photos"

# Verify binary
echo ""
echo "========================================"
echo "Binary Information"
echo "========================================"

# Check file type
info "Architecture:"
file dist/photos

# Check size
info ""
info "Size:"
ls -lh dist/photos | awk '{print $5, $9}'

# Check if it's AMD64
if file dist/photos | grep -q "x86-64\|x86_64\|amd64"; then
    success "✓ Binary is AMD64/x86-64"
else
    warning "Binary architecture might not be AMD64!"
    file dist/photos
fi

# Try to check dependencies (will fail on ARM64 Mac, that's expected)
info ""
info "Dependencies (this will fail on ARM64 Mac, which is expected):"
ldd dist/photos 2>&1 || warning "Cannot check dependencies on ARM64 Mac (expected)"

# Final summary
echo ""
echo "========================================"
success "Build Complete!"
echo "========================================"
echo ""
info "Binary location: dist/photos"
info ""
info "Next steps:"
info "  1. Copy to AMD64/x86-64 Linux system:"
info "     scp dist/photos user@server:/usr/local/bin/"
info ""
info "  2. Or test in AMD64 Docker container:"
info "     docker run --rm -v \"\$(pwd)/dist:/dist\" debian:trixie /dist/photos --help"
info ""
info "  3. Or use docker-compose for easier testing:"
info "     docker-compose run --rm photos-runtime --help"
echo ""
echo "========================================"
