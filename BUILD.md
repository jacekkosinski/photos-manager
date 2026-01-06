# Building Standalone Binary

This document explains how to build a standalone binary for the photos-manager CLI using Nuitka.

## Overview

The photos-manager CLI can be compiled into a single standalone binary using Nuitka, which provides:
- **Single executable**: No Python installation needed on target systems
- **Fast startup**: C-compiled code with optimizations
- **Self-contained**: All dependencies bundled
- **Linux amd64 target**: Optimized for Debian 13.2 and similar distributions

## Prerequisites

### On Build System

You need the following installed on the system where you build the binary:

1. **Python 3.12+**
   ```bash
   python3 --version  # Should be 3.12 or higher
   ```

2. **Nuitka**
   ```bash
   pip install nuitka
   ```

3. **C Compiler and Build Tools** (for Debian/Ubuntu):
   ```bash
   sudo apt-get update
   sudo apt-get install gcc g++ ccache patchelf
   ```

4. **Project Dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

### On Target System

The target system (Debian 13.2) only needs:
- **glibc** (usually pre-installed)
- **No Python installation required**
- **No pip or virtualenv required**

## Build Process

### Quick Build

Simply run the build script:

```bash
./build.sh
```

This will:
1. Check for Nuitka installation
2. Create `dist/` directory
3. Compile `photos_manager/cli.py` into a single binary
4. Output binary to `dist/photos`
5. Generate build report in `nuitka-report.xml`

## Building with Docker (Mac M2/ARM64)

If you're on Mac M2 (ARM64) and need to build for AMD64/x86_64 architecture, use Docker for cross-compilation.

**Why Docker?** Nuitka does NOT support cross-compilation. The binary's architecture must match the build system's architecture. Docker with `--platform=linux/amd64` runs an AMD64 Linux container, ensuring the output binary is AMD64.

### Prerequisites

1. **Docker Desktop for Mac** (version 20.10+ with buildx support)
   ```bash
   docker --version          # Should be 20.10+
   docker buildx version     # Check buildx availability
   ```

2. **Enable Multi-platform builds** in Docker Desktop:
   - Open Docker Desktop
   - Go to Settings → Features in development
   - Enable "Use containerd for pulling and storing images"
   - Restart Docker Desktop

### Option 1: Quick Build with docker-compose (Recommended)

The easiest way to build:

```bash
# Build and extract binary in one command
docker-compose up

# The AMD64 binary will be in dist/photos
ls -lh dist/photos

# Verify architecture
file dist/photos
# Expected: ELF 64-bit LSB executable, x86-64, ...
```

**What it does:**
- Builds multi-stage Docker image for AMD64
- Compiles code with Nuitka inside container
- Compresses binary with UPX (~50% size reduction)
- Automatically extracts binary to `dist/` directory
- Shows binary info (size, architecture, dependencies)

### Option 2: Build with docker-build.sh Script

For more control and verbose output:

```bash
# Make script executable (first time only)
chmod +x docker-build.sh

# Build AMD64 binary
./docker-build.sh
```

**Features:**
- Checks Docker and buildx availability
- Creates/configures multi-platform builder automatically
- Shows detailed build progress
- Verifies binary architecture
- Provides clear next steps

### Option 3: Manual Docker Build

For advanced users who want full control:

```bash
# Create multi-platform builder (first time only)
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap

# Build and extract binary
docker buildx build \
    --platform=linux/amd64 \
    --target builder \
    --output type=local,dest=./dist-docker \
    .

# Copy binary to dist/
mkdir -p dist
cp dist-docker/build/dist/photos dist/
rm -rf dist-docker
```

### Verify the Build

After building, verify the binary is correct:

```bash
# Check architecture (on Mac)
file dist/photos
# Expected output: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked...

# Check size (with UPX compression)
ls -lh dist/photos
# Expected: ~8-12 MB (with UPX)
# Without UPX: ~15-25 MB

# Test in AMD64 Docker container (recommended)
docker run --rm -v "$(pwd)/dist:/dist" debian:trixie /dist/photos --help
docker run --rm -v "$(pwd)/dist:/dist" debian:trixie /dist/photos --version

# Or use docker-compose runtime service
docker-compose run --rm photos-runtime --help
docker-compose run --rm photos-runtime mkjson --help
```

### Build Performance

**First build:**
- Downloads Debian trixie base image (~150 MB)
- Downloads build tools and dependencies (~350 MB)
- Compiles with Nuitka (~3-5 minutes)
- Compresses with UPX (~30 seconds)
- **Total: ~5-10 minutes**

**Subsequent builds:**
- Docker uses cached layers
- Only changed files trigger rebuild
- **Total: ~1-2 minutes**

### Troubleshooting Docker Build

#### "docker buildx not found"

**Solution:**
```bash
# Update Docker Desktop to latest version
# Minimum required: 20.10+

# Verify installation
docker buildx version
```

#### "exec format error" when running binary

**Problem:** Binary is ARM64 instead of AMD64.

**Solution:**
```bash
# Ensure --platform=linux/amd64 is set
# Check Dockerfile line 15: FROM --platform=linux/amd64 debian:trixie

# Rebuild with docker-build.sh (handles platform correctly)
./docker-build.sh

# Verify architecture
file dist/photos | grep x86-64
```

#### Build takes too long / hangs

**Solutions:**
```bash
# 1. Increase Docker resources
# Docker Desktop → Settings → Resources
# Recommended: 4+ CPU cores, 8+ GB RAM

# 2. Clean Docker cache
docker builder prune -a

# 3. Check Docker logs
docker-compose up  # Shows detailed output
```

#### "Cannot connect to Docker daemon"

**Solution:**
```bash
# Start Docker Desktop
open -a Docker

# Wait for Docker to start (~30 seconds)
# Verify with:
docker info
```

#### Binary size larger than expected

**Problem:** UPX compression might have failed.

**Check:**
```bash
# Build logs should show:
# "Compressing binary with UPX..."
# "UPX compression completed!"

# If missing, UPX might not be installed in container
# Rebuild and check output
docker-compose up
```

**Without UPX:** ~15-25 MB
**With UPX:** ~8-12 MB (~50% reduction)

#### "platform does not match" warning

**Explanation:** This is expected on Mac M2 (ARM64) when building AMD64.

Docker emulates AMD64 architecture using QEMU, which is why build is slower. This is normal and the binary will be correct.

### Docker Build Architecture

The build uses multi-stage Dockerfile:

**Stage 1 (builder):**
- Base: `debian:trixie` for AMD64
- Installs: Python 3.12, gcc, g++, ccache, patchelf, upx
- Compiles: Nuitka builds binary
- Compresses: UPX reduces size by ~50%

**Stage 2 (runtime):**
- Base: `debian:trixie-slim` (minimal)
- Only contains: compiled binary + minimal glibc
- Used for: testing binary in container

### Cleaning Up

Remove Docker artifacts when done:

```bash
# Remove built images
docker-compose down --rmi all

# Remove builder cache (frees disk space)
docker builder prune -a

# Remove dangling images
docker image prune -a
```

### Manual Build

If you need more control, you can run Nuitka directly:

```bash
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
    photos_manager/cli.py
```

### Build Options Explained

- `--standalone`: Create self-contained binary with all dependencies
- `--onefile`: Pack everything into a single executable file
- `--output-dir=dist`: Output directory for the binary
- `--output-filename=photos`: Name of the output binary
- `--include-package=photos_manager`: Include entire package
- `--python-flag=no_site`: Don't load site packages
- `--python-flag=-O`: Enable Python optimizations
- `--enable-plugin=no-qt`: Disable Qt plugin (not needed)
- `--assume-yes-for-downloads`: Auto-confirm downloads (dependency packs)
- `--warn-implicit-exceptions`: Show potential exception warnings
- `--warn-unusual-code`: Show unusual code patterns

## Testing the Binary

After building, test the binary:

```bash
# Show help
./dist/photos --help

# Test each subcommand
./dist/photos mkjson --help
./dist/photos mkversion --help
./dist/photos setmtime --help
./dist/photos verify --help

# Run actual commands
./dist/photos mkjson /path/to/test/directory
./dist/photos mkversion /path/to/test/directory
```

## Deployment

### Copy to Target System

Transfer the binary to your Debian 13.2 system:

```bash
# Using scp
scp dist/photos user@debian-server:/usr/local/bin/

# Or rsync
rsync -av dist/photos user@debian-server:/usr/local/bin/
```

### Installation on Target System

```bash
# Make it executable (if not already)
chmod +x /usr/local/bin/photos

# Verify it works
photos --version
photos --help

# Use it
photos mkjson /path/to/photos
photos verify /path/to/archive
```

## Build Size

Expected binary size:
- **~15-25 MB** (includes Python runtime + dependencies)
- **Compressed with UPX**: ~8-12 MB (optional, see below)

### Optional: Compress with UPX

To reduce binary size, you can compress it with UPX:

```bash
# Install UPX
sudo apt-get install upx

# Compress the binary
upx --best --lzma dist/photos

# This will reduce size by ~50-60%
```

**Note**: UPX compression may slightly increase startup time (~50-100ms) but significantly reduces file size.

## Troubleshooting

### "Nuitka not found"

```bash
pip install --upgrade nuitka
```

### "gcc: command not found"

```bash
sudo apt-get install build-essential gcc g++
```

### "ccache: command not found"

```bash
sudo apt-get install ccache
```

### "Module not found" errors during build

Make sure all dependencies are installed:

```bash
pip install -e ".[dev]"
```

### Binary doesn't run on target system

Check glibc version compatibility:

```bash
# On build system
ldd --version

# On target system
ldd --version

# They should be similar or target >= build system
```

### Large binary size

1. Use UPX compression (see above)
2. Use `--python-flag=-OO` for more aggressive optimization
3. Use `--remove-output` to clean up intermediate files

## CI/CD Integration

You can integrate the build process into CI/CD:

```yaml
# Example GitHub Actions workflow
name: Build Binary

on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install nuitka
          pip install -e ".[dev]"
      - name: Build binary
        run: ./build.sh
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          name: photos-binary
          path: dist/photos
```

## Advanced Options

### Build with Debug Symbols

For debugging:

```bash
python3 -m nuitka \
    --standalone \
    --onefile \
    --debug \
    --output-dir=dist \
    --output-filename=photos-debug \
    photos_manager/cli.py
```

### Build with Profiling

For performance analysis:

```bash
python3 -m nuitka \
    --standalone \
    --onefile \
    --profile \
    --output-dir=dist \
    --output-filename=photos-profile \
    photos_manager/cli.py
```

### Cross-Compilation

Nuitka doesn't directly support cross-compilation. To build for Debian 13.2 from another system:

1. Use Docker with Debian 13.2 image
2. Or use a Debian 13.2 VM for building
3. Or build on the target system directly

## Performance

Nuitka-compiled binaries are typically:
- **30-50% faster** than interpreted Python
- **Instant startup** (no Python interpreter initialization)
- **Lower memory usage** (no CPython overhead)

## Alternative: PyInstaller

If Nuitka doesn't work for your use case, you can use PyInstaller instead:

```bash
# Install PyInstaller
pip install pyinstaller

# Build binary
pyinstaller \
    --onefile \
    --name photos \
    --hidden-import=photos_manager \
    photos_manager/cli.py

# Binary will be in dist/photos
```

**Note**: PyInstaller binaries are typically larger (~40-60 MB) and slower to start than Nuitka binaries.

## References

- [Nuitka Documentation](https://nuitka.net/doc/user-manual.html)
- [Nuitka GitHub](https://github.com/Nuitka/Nuitka)
- [UPX Documentation](https://upx.github.io/)
