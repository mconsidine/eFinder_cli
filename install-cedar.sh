#!/bin/bash
# =============================================================================
# install-cedar.sh — Phase 2: Cedar-solve & Cedar-detect Installation
#
# 1. Clones cedar-detect, compiles the Rust gRPC server binary
# 2. Clones cedar-solve (a tetra3 fork), installs it as the 'tetra3' Python
#    module via pip
# 3. Downloads the Hipparcos catalogue and generates the star pattern database
#    using the tetra3 Python API
#
# Usage:
#   sudo bash install-cedar.sh
#
# Prerequisites (supplied by install-base.sh):
#   - Rust toolchain (cargo, rustc) via rustup at /root/.cargo
#   - protobuf-compiler + libprotobuf-dev  (required by cedar-detect build.rs)
#   - python3-pip, build-essential
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
CEDAR_DETECT_DIR=/tmp/cedar-detect
CEDAR_SOLVE_DIR=/tmp/cedar-solve

echo "============================================================================="
echo " Cedar-detect & Cedar-solve Build & Installation"
echo "============================================================================="

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure cargo and protoc are on PATH.
# rustup installs to $HOME/.cargo (which is /root/.cargo when run as root).
# We set PATH explicitly to avoid sudo secure_path stripping /usr/bin (protoc).
# ---------------------------------------------------------------------------
. "$HOME/.cargo/env"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.cargo/bin"

echo "Build environment:"
echo "  PATH  : $PATH"
echo "  cargo : $(cargo --version)"
echo "  protoc: $(protoc --version)"

# ---------------------------------------------------------------------------
# [1/5] cedar-detect — Rust gRPC star-detection server
#
# The cedar-detect repo is a Cargo workspace. The binary target is named
# 'cedar-detect-server' and lives at the workspace root (not in a subdir).
# The compiled binary lands at target/release/cedar-detect-server.
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] Cloning cedar-detect repository..."

rm -rf "$CEDAR_DETECT_DIR"
git clone --depth 1 https://github.com/smroid/cedar-detect.git "$CEDAR_DETECT_DIR"

echo ""
echo "[2/5] Building cedar-detect-server (Rust binary)..."
echo "  This may take 10-20 minutes on Pi Zero 2W..."

cd "$CEDAR_DETECT_DIR"
echo "  Working directory : $(pwd)"
echo "  Workspace contents:"
ls -la

cargo build --release --bin cedar-detect-server

BINARY="$CEDAR_DETECT_DIR/target/release/cedar-detect-server"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: cedar-detect-server binary not found at expected path:"
    echo "  $BINARY"
    echo "Contents of target/release/ :"
    ls "$CEDAR_DETECT_DIR/target/release/" 2>/dev/null || echo "  (directory not found)"
    exit 1
fi

install -m 755 "$BINARY" /usr/local/bin/cedar-detect-server
echo "  Installed: /usr/local/bin/cedar-detect-server"

if command -v cedar-detect-server > /dev/null 2>&1; then
    echo "  ✓ cedar-detect-server available in PATH"
else
    echo "ERROR: cedar-detect-server not found in PATH after installation"
    exit 1
fi

# Clean up source — binary is now in /usr/local/bin
cd /
rm -rf "$CEDAR_DETECT_DIR"

# ---------------------------------------------------------------------------
# [3/5] cedar-solve — Python plate-solver (tetra3 fork)
#
# cedar-solve installs as the Python module 'tetra3' (not 'cedar_solve').
# eFinder_cedar_v2.py does:  import tetra3
# We install system-wide with --break-system-packages so it is visible to
# both the system python3 and any venv created with --system-site-packages.
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Cloning and installing cedar-solve Python package..."

rm -rf "$CEDAR_SOLVE_DIR"
git clone --depth 1 https://github.com/smroid/cedar-solve.git "$CEDAR_SOLVE_DIR"
cd "$CEDAR_SOLVE_DIR"

pip3 install --break-system-packages .

# Verify: cedar-solve installs as 'tetra3', not 'cedar_solve'
if python3 -c "import tetra3" 2>/dev/null; then
    echo "  ✓ tetra3 module (cedar-solve) imported successfully"
else
    echo "ERROR: 'import tetra3' failed after cedar-solve install"
    echo "  Installed packages containing 'tetra':"
    pip3 list 2>/dev/null | grep -i tetra || echo "  (none found)"
    exit 1
fi

# Clean up source
cd /
rm -rf "$CEDAR_SOLVE_DIR"

# ---------------------------------------------------------------------------
# [4/5] Download Hipparcos star catalogue
#
# tetra3 expects hip_main.dat in its package data directory when star_catalog
# is given as a string. We download it there directly.
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Downloading Hipparcos star catalogue..."

# Find the installed tetra3 package directory
TETRA3_PKG=$(python3 -c "import tetra3, os; print(os.path.dirname(tetra3.__file__))")
echo "  tetra3 package directory: $TETRA3_PKG"

cd "$TETRA3_PKG"

if [ ! -f hip_main.dat ]; then
    wget -q --show-progress \
        https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat.gz
    gunzip hip_main.dat.gz
    echo "  ✓ Hipparcos catalogue downloaded ($(du -sh hip_main.dat | cut -f1))"
else
    echo "  Hipparcos catalogue already present"
fi

# ---------------------------------------------------------------------------
# [5/5] Generate star pattern database via the tetra3 Python API
#
# tetra3.Tetra3.generate_database() key parameters:
#   max_fov      — maximum camera FOV the database covers (degrees)
#   save_as      — str → saves into tetra3 package data dir as <name>.npz
#                  This matches how tetra3.Tetra3('cedar_database') loads it.
#   star_catalog — 'hip_main' → reads hip_main.dat from the package dir
#
# eFinder_cedar_v2.py line 268:  t3 = tetra3.Tetra3('cedar_database')
# That str form resolves to <tetra3_package>/cedar_database.npz, so we must
# generate with save_as='cedar_database' (str, not Path) to land there.
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Generating cedar star pattern database..."
echo "  FOV    : 15 degrees"
echo "  Output : $TETRA3_PKG/cedar_database.npz"
echo "  This may take 5-15 minutes..."
echo ""

python3 - <<'PYEOF'
import tetra3

t3 = tetra3.Tetra3(load_database=None)
t3.generate_database(
    max_fov=15,
    save_as='cedar_database',
    star_catalog='hip_main',
)
print("  Database generation complete.")
PYEOF

DB_PATH="$TETRA3_PKG/cedar_database.npz"
if [ -f "$DB_PATH" ]; then
    echo "  ✓ Database created: $DB_PATH"
    ls -lh "$DB_PATH"
else
    echo "ERROR: cedar_database.npz not found at $DB_PATH"
    exit 1
fi

# Clean up Hipparcos catalogue from the package dir (51 MB, no longer needed)
rm -f "$TETRA3_PKG/hip_main.dat"

# NOTE: purge of build tools (rustc, cargo, build-essential…) is intentionally
# left to install-complete.sh so nothing in Phase 3 is broken by an early purge.

echo ""
echo "============================================================================="
echo " Cedar installation complete"
echo "  cedar-detect-server : $(which cedar-detect-server)"
echo "  tetra3 package      : $TETRA3_PKG"
echo "  Database            : $TETRA3_PKG/cedar_database.npz"
echo "============================================================================="
