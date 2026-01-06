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
