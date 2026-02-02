# Multi-stage Dockerfile for building AMD64 binary on Mac M2
# Stage 1: Builder - Compile with Nuitka
# Stage 2: Runtime - Minimal image for testing

# ==============================================================================
# Stage 1: Builder
# ==============================================================================
FROM --platform=linux/amd64 debian:trixie AS builder

LABEL maintainer="Jacek Kosiński <jacek.kosinski@softflow.tech>"
LABEL description="Build stage for photos-manager CLI (AMD64)"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.13 \
    python3.13-dev \
    python3-pip \
    gcc \
    g++ \
    make \
    ccache \
    patchelf \
    upx-ucl \
    file \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.13 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.13 1

# Set working directory
WORKDIR /build

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY photos_manager/ ./photos_manager/

# Install Python dependencies
# Note: We don't use Poetry in Docker to keep the build simpler
RUN pip3 install --no-cache-dir --break-system-packages \
    nuitka

# Build with Nuitka
RUN echo "Building binary with Nuitka..." && \
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
        photos_manager/cli.py && \
    echo "Nuitka build completed!"

# Compress binary with UPX
RUN echo "Compressing binary with UPX..." && \
    upx --best --lzma dist/photos && \
    echo "UPX compression completed!"

# Verify architecture and display binary info
RUN echo "Binary information:" && \
    file dist/photos && \
    ls -lh dist/photos && \
    ldd dist/photos || true

# ==============================================================================
# Stage 2: Runtime (for testing in container)
# ==============================================================================
FROM --platform=linux/amd64 debian:trixie-slim AS runtime

LABEL maintainer="Jacek Kosiński <jacek.kosinski@softflow.tech>"
LABEL description="Runtime image for photos-manager CLI (AMD64)"

# Install only minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libc6 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled binary from builder stage
COPY --from=builder /build/dist/photos /usr/local/bin/photos

# Verify binary works
RUN photos --version || photos --help

# Set entrypoint
ENTRYPOINT ["photos"]
CMD ["--help"]

# ==============================================================================
# Usage:
#
# Build and extract binary:
#   docker buildx build --platform=linux/amd64 --target builder \
#     --output type=local,dest=./dist .
#
# Build runtime image:
#   docker build --platform=linux/amd64 -t photos-manager .
#
# Run binary in container:
#   docker run --rm photos-manager index --help
# ==============================================================================
