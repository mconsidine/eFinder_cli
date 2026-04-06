#!/bin/bash
# =============================================================================
# install-cedar.sh — Phase 2: Cedar-solve Compilation & Installation
# 
# Compiles cedar-detect-server from Rust source and installs cedar-solve
# Python package from source. Generates the star pattern database.
#
# Usage:
#   sudo bash install-cedar.sh
#
# Prerequisites (supplied by install-base.sh):
#   - Rust toolchain (cargo, rustc) via rustup
#   - protobuf-compiler (protoc) — required by cedar-detect build.rs
#   - Python 3 with pip
#   - Build tools (gcc, cmake, pkg-config)
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
CEDAR_SOLVE_DIR=/tmp/cedar-solve
CEDAR_DETECT_DIR=/tmp/cedar-detect
DATABASE_DIR="$EFINDER_HOME/Solver/databases"

echo "============================================================================="
echo " Cedar-solve Build & Installation"
echo "============================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure cargo and protoc are on PATH.
# rustup installs to $HOME/.cargo; under sudo $HOME is /root.
# We also explicitly include /usr/bin so protoc is always visible regardless
# of the sudoers secure_path setting.
# ---------------------------------------------------------------------------
. "$HOME/.cargo/env"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.cargo/bin"

echo "Build environment:"
echo "  PATH : $PATH"
echo "  cargo: $(cargo --version)"
echo "  protoc: $(protoc --version)"

echo ""
echo "[1/5] Cloning cedar-detect repository..."

# Clean any existing clone
if [ -d "$CEDAR_DETECT_DIR" ]; then
    rm -rf "$CEDAR_DETECT_DIR"
fi

git clone --depth 1 https://github.com/smroid/cedar-detect.git "$CEDAR_DETECT_DIR"

echo ""
echo "[2/5] Building cedar-detect-server (Rust binary)..."
echo "  This may take 10-20 minutes on Pi Zero 2W..."

# Build from the repo root; cedar-detect-server is a named binary target
# in the workspace. The binary lands at target/release/cedar-detect-server.
cd "$CEDAR_DETECT_DIR"

echo "Working directory: $(pwd)"
echo "Contents:"
ls -la

# Build in release mode for production performance
cargo build --release --bin cedar-detect-server

# Verify binary was built
BINARY="$CEDAR_DETECT_DIR/target/release/cedar-detect-server"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: cedar-detect-server binary not found after build"
    echo "Expected: $BINARY"
    exit 1
fi

# Install to system path
install -m 755 "$BINARY" /usr/local/bin/cedar-detect-server

echo "  Installed: /usr/local/bin/cedar-detect-server"

# Verify installation
if command -v cedar-detect-server > /dev/null 2>&1; then
    echo "  ✓ cedar-detect-server is available in PATH"
    cedar-detect-server --version 2>/dev/null || echo "  (version flag not supported — binary is present)"
else
    echo "ERROR: cedar-detect-server not found in PATH after installation"
    exit 1
fi

echo ""
echo "[3/5] Cloning and installing cedar-solve Python package from source..."

# Clean any existing clone
if [ -d "$CEDAR_SOLVE_DIR" ]; then
    rm -rf "$CEDAR_SOLVE_DIR"
fi

git clone --depth 1 https://github.com/smroid/cedar-solve.git "$CEDAR_SOLVE_DIR"
cd "$CEDAR_SOLVE_DIR"

# Install with --break-system-packages for Bookworm externally-managed Python
pip3 install --break-system-packages .

# Verify Python import
if python3 -c "import cedar_solve" 2>/dev/null; then
    echo "  ✓ cedar-solve Python package imported successfully"
else
    echo "ERROR: cedar-solve Python import failed"
    exit 1
fi

echo ""
echo "[4/5] Downloading Hipparcos star catalog..."

mkdir -p "$DATABASE_DIR"
cd "$DATABASE_DIR"

if [ ! -f hip_main.dat ]; then
    wget -q --show-progress \
        https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat.gz
    gunzip hip_main.dat.gz
    echo "  ✓ Hipparcos catalog downloaded"
else
    echo "  Hipparcos catalog already present"
fi

echo ""
echo "[5/5] Generating cedar star pattern database..."
echo "  FOV: 15 degrees"
echo "  Pattern stars per FOV: 10"
echo "  Catalog stars per FOV: 200"
echo ""
echo "  This may take 5-15 minutes..."

# Generate database using the Python module's CLI tool.
# Database is written to the current directory as default_database.npz.
python3 -m cedar_solve.generate_database \
    --hipparcos-path hip_main.dat \
    --max-fov 15 \
    --pattern-stars-per-fov 10 \
    --catalog-stars-per-fov 200

# Verify database was created
if [ -f default_database.npz ]; then
    echo "  ✓ Database generated: default_database.npz"
    ls -lh default_database.npz
else
    echo "ERROR: Database file not created"
    exit 1
fi

# Clean up Hipparcos catalog (large file, no longer needed)
rm -f hip_main.dat

# Set ownership
chown -R efinder:efinder "$DATABASE_DIR"

# Clean up source directories
cd /
rm -rf "$CEDAR_SOLVE_DIR"
rm -rf "$CEDAR_DETECT_DIR"

# NOTE: build tool purge (rustc, cargo, build-essential, etc.) is intentionally
# left to install-complete.sh so nothing in Phase 3 is broken by an early purge.

echo ""
echo "============================================================================="
echo " Cedar-solve installation complete"
echo "  Binary  : $(which cedar-detect-server)"
echo "  Python  : cedar_solve module installed"
echo "  Database: $DATABASE_DIR/default_database.npz"
echo "============================================================================="
