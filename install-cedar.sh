#!/bin/bash
# =============================================================================
# install-cedar.sh — Phase 2: Cedar-solve Compilation & Installation
# 
# Compiles cedar-detect-server from Rust source and installs cedar-solve
# Python package. Generates the star pattern database.
#
# Usage:
#   sudo bash install-cedar.sh
#
# Prerequisites:
#   - Rust toolchain (cargo, rustc)
#   - Python 3 with pip
#   - Build tools (gcc, cmake, pkg-config)
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
CEDAR_DIR=/tmp/cedar-solve
DATABASE_DIR="$EFINDER_HOME/Solver/databases"

echo "============================================================================="
echo " Cedar-solve Build & Installation"
echo "============================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

echo ""
echo "[1/5] Cloning cedar-solve repository..."

# Clean any existing clone
if [ -d "$CEDAR_DIR" ]; then
    rm -rf "$CEDAR_DIR"
fi

git clone --depth 1 https://github.com/smroid/cedar-solve.git "$CEDAR_DIR"
cd "$CEDAR_DIR"

echo ""
echo "[2/5] Building cedar-detect-server (Rust binary)..."
echo "  This may take 10-20 minutes on Pi Zero 2W..."

git clone --depth 1 https://github.com/smroid/cedar-detect.git cedar-detect-server

cd cedar-detect-server

# Build in release mode for production performance
cargo build --release

# Verify binary was built
if [ ! -f target/release/cedar-detect-server ]; then
    echo "ERROR: cedar-detect-server binary not found after build"
    exit 1
fi

# Install to system path
install -m 755 target/release/cedar-detect-server /usr/local/bin/
echo "  Installed: /usr/local/bin/cedar-detect-server"

# Verify installation
if command -v cedar-detect-server > /dev/null 2>&1; then
    echo "  ✓ cedar-detect-server is available in PATH"
    cedar-detect-server --version 2>/dev/null || echo "  (version info not available)"
else
    echo "ERROR: cedar-detect-server not found in PATH after installation"
    exit 1
fi

echo ""
echo "[3/5] Installing cedar-solve Python package..."

cd "$CEDAR_DIR"

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

# Generate database using the Python module's CLI tool
# Database will be created in current directory as default_database.npz
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

# Clean up source directory
cd /
rm -rf "$CEDAR_DIR"

apt-get purge -y rustc cargo build-essential cmake pkg-config
apt-get autoremove -y
apt-get clean

echo ""
echo "============================================================================="
echo " Cedar-solve installation complete"
echo "  Binary: $(which cedar-detect-server)"
echo "  Python module: cedar_solve"
echo "  Database: $DATABASE_DIR/default_database.npz"
echo "============================================================================="
