#!/bin/bash
# =============================================================================
# install-cedar.sh — Phase 2: Cedar-solve & Cedar-detect Installation
#
# cedar-solve's setup.sh does:
#   python -m venv .cedar_venv
#   source .cedar_venv/bin/activate
#   pip install -e ".[dev,docs,cedar-detect]"
#
# This installs cedar-solve in editable mode inside a venv that lives within
# the cloned repo.  The 'tetra3' module resolves directly to files inside the
# clone, so the repo must remain at its permanent location forever.
#
# eFinder_cedar_v2.py does 'import tetra3' from system Python, not from the
# venv.  We therefore also install cedar-solve into system Python in editable
# mode so both paths work.
#
# Steps:
#   1. Build cedar-detect Rust gRPC server binary
#   2. Clone cedar-solve to permanent location, run its setup.sh logic
#   3. Also install tetra3 into system Python (editable, --ignore-installed)
#   4. Download Hipparcos catalogue into the tetra3 source directory
#   5. Generate the star pattern database via the tetra3 Python API
#
# Usage:
#   sudo bash install-cedar.sh
#
# Prerequisites (supplied by install-base.sh):
#   - Rust toolchain (cargo, rustc) via rustup at /root/.cargo
#   - protobuf-compiler + libprotobuf-dev (for cedar-detect build.rs)
#   - python3-pip, python3-venv, build-essential
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
CEDAR_DETECT_DIR=/tmp/cedar-detect
CEDAR_SOLVE_DIR="$EFINDER_HOME/cedar-solve"   # permanent — tetra3 lives here

echo "============================================================================="
echo " Cedar-detect & Cedar-solve Build & Installation"
echo "============================================================================="

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure cargo and protoc are on PATH.
# ---------------------------------------------------------------------------
. "$HOME/.cargo/env"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.cargo/bin"

echo "Build environment:"
echo "  PATH  : $PATH"
echo "  cargo : $(cargo --version)"
echo "  protoc: $(protoc --version)"

# ---------------------------------------------------------------------------
# [1/5] cedar-detect — Rust gRPC star-detection server
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] Cloning and building cedar-detect..."

rm -rf "$CEDAR_DETECT_DIR"
git clone --depth 1 https://github.com/smroid/cedar-detect.git "$CEDAR_DETECT_DIR"
cd "$CEDAR_DETECT_DIR"

cargo build --release --bin cedar-detect-server

BINARY="$CEDAR_DETECT_DIR/target/release/cedar-detect-server"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: binary not found at $BINARY"
    ls "$CEDAR_DETECT_DIR/target/release/" 2>/dev/null || true
    exit 1
fi

install -m 755 "$BINARY" /usr/local/bin/cedar-detect-server
echo "  ✓ cedar-detect-server installed to /usr/local/bin/"

# Compile gRPC Python stubs from the proto file before deleting the source.
# eFinder_cedar_v2.py imports cedar_detect_pb2 and cedar_detect_pb2_grpc
# from ~/Solver/ — these must be pre-compiled into the image.
PROTO_SRC="$CEDAR_DETECT_DIR/src/proto/cedar_detect.proto"
STUB_DEST="$EFINDER_HOME/Solver"
mkdir -p "$STUB_DEST"

if [ -f "$PROTO_SRC" ]; then
    python3 -m grpc_tools.protoc \
        -I "$CEDAR_DETECT_DIR/src/proto" \
        --python_out="$STUB_DEST" \
        --grpc_python_out="$STUB_DEST" \
        "$PROTO_SRC"
    echo "  ✓ gRPC stubs compiled to $STUB_DEST"
    ls "$STUB_DEST"/cedar_detect_pb2*.py
else
    echo "ERROR: proto file not found at $PROTO_SRC"
    exit 1
fi

cd /
rm -rf "$CEDAR_DETECT_DIR"

# ---------------------------------------------------------------------------
# [2/5] Clone cedar-solve to permanent location
#
# The repo must never be deleted — editable installs point directly into it.
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Cloning cedar-solve..."

if [ -d "$CEDAR_SOLVE_DIR" ]; then
    echo "  Existing clone found — pulling latest..."
    git -C "$CEDAR_SOLVE_DIR" pull
else
    git clone --depth 1 https://github.com/smroid/cedar-solve.git "$CEDAR_SOLVE_DIR"
fi

chown -R "$EFINDER_USER:$EFINDER_USER" "$CEDAR_SOLVE_DIR"

# ---------------------------------------------------------------------------
# [3/5] Replicate cedar-solve's setup.sh, then also install into system Python
#
# setup.sh does:
#   python -m venv .cedar_venv
#   source .cedar_venv/bin/activate
#   pip install -e ".[dev,docs,cedar-detect]"
#
# We run this as the efinder user so the venv is owned correctly.
# 'python' may not exist on Bookworm; we use python3 explicitly.
#
# We then ALSO install cedar-solve into system Python in editable mode so
# that eFinder_cedar_v2.py can 'import tetra3' without activating the venv.
# --ignore-installed prevents pip touching apt-managed packages (e.g. Pillow).
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Setting up cedar-solve venv and installing..."

# -----------------------------------------------------------------------
# Patch pyproject.toml to remove upper version bounds on dependencies.
# cedar-solve pins hard maximums (e.g. Pillow<10, numpy<2) that conflict
# with newer versions already installed in our image.  There is no known
# functional reason for these upper bounds.  We strip any ",<version"
# or standalone "<version" constraint so pip resolves against whatever
# is actually present.
#   "Pillow>=8.0,<10"  ->  "Pillow>=8.0"
#   "numpy<2"          ->  "numpy"
# -----------------------------------------------------------------------
if [ -f "$CEDAR_SOLVE_DIR/pyproject.toml" ]; then
    echo "  Patching pyproject.toml — removing upper version bounds..."
    # Remove ,<N.N style upper bounds (with optional whitespace after comma)
    sed -i 's/,[[:space:]]*<[0-9][0-9.]*//g' "$CEDAR_SOLVE_DIR/pyproject.toml"
    # Remove standalone <N.N upper bounds (package listed with only an upper bound)
    sed -i 's/[[:space:]]*<[0-9][0-9.]*//g' "$CEDAR_SOLVE_DIR/pyproject.toml"
    echo "  Done. Effective dependencies:"
    python3 -c "
import re, sys
with open('$CEDAR_SOLVE_DIR/pyproject.toml') as f:
    content = f.read()
in_deps = False
for line in content.splitlines():
    if 'dependencies' in line and '=' in line:
        in_deps = True
    if in_deps:
        print(' ', line)
    if in_deps and line.strip() == ']':
        break
" 2>/dev/null || true
else
    echo "  WARNING: pyproject.toml not found — skipping patch"
fi

cd "$CEDAR_SOLVE_DIR"

# Create the .cedar_venv as efinder user (replicates setup.sh step 1)
sudo -u "$EFINDER_USER" python3 -m venv "$CEDAR_SOLVE_DIR/.cedar_venv"

# Install cedar-solve into the venv in editable mode with all extras
# (replicates setup.sh steps 2+3, substituting python3 for python)
echo "  Installing into .cedar_venv (editable, with cedar-detect extras)..."
sudo -u "$EFINDER_USER" \
    "$CEDAR_SOLVE_DIR/.cedar_venv/bin/pip" install \
    --upgrade pip

sudo -u "$EFINDER_USER" \
    "$CEDAR_SOLVE_DIR/.cedar_venv/bin/pip" install \
    -e "$CEDAR_SOLVE_DIR[dev,docs,cedar-detect]"

echo "  ✓ cedar-solve installed in .cedar_venv"

# Also install into system Python so eFinder can import tetra3 without
# activating the venv.  Editable mode means both installs share the same
# source files in $CEDAR_SOLVE_DIR — no duplication.
echo ""
echo "  Installing tetra3 into system Python (editable, for eFinder import)..."
pip3 install \
    --break-system-packages \
    --ignore-installed \
    -e "$CEDAR_SOLVE_DIR[cedar-detect]"

# Verify
if python3 -c "import tetra3; print('  tetra3 location:', tetra3.__file__)" 2>/dev/null; then
    echo "  ✓ tetra3 importable from system Python"
else
    echo "ERROR: 'import tetra3' failed"
    exit 1
fi

# ---------------------------------------------------------------------------
# [4/5] Download Hipparcos star catalogue
#
# Editable install means tetra3.__file__ points into $CEDAR_SOLVE_DIR/tetra3/
# Plain string args to generate_database resolve relative to that directory.
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Downloading Hipparcos star catalogue..."

TETRA3_PKG=$(python3 -c "import tetra3, os; print(os.path.dirname(tetra3.__file__))")
echo "  tetra3 source directory: $TETRA3_PKG"

# hip_main.dat goes in the tetra3 package root (not data/)
# tetra3._build_catalog_path resolves plain string to <package_root>/hip_main.dat
mkdir -p "$TETRA3_PKG/data"
cd "$TETRA3_PKG"

if [ ! -f hip_main.dat ]; then
    wget -q --show-progress --no-check-certificate \
        https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat
    echo "  ✓ Hipparcos catalogue downloaded ($(du -sh hip_main.dat | cut -f1))"
else
    echo "  Hipparcos catalogue already present"
fi

# ---------------------------------------------------------------------------
# [5/5] Generate star pattern database via the tetra3 Python API
#
# save_as='cedar_database' (str) → written to tetra3/data/ as
# cedar_database.npz, which is where tetra3.Tetra3('cedar_database') finds it.
# This matches line 268 of eFinder_cedar_v2.py:
#   t3 = tetra3.Tetra3('cedar_database')
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Generating cedar star pattern database..."
echo "  FOV    : 15 degrees"
echo "  Output : $TETRA3_PKG/data/t3_fov14_mag8.npz"
echo "  This may take 5-15 minutes..."

# Change to a neutral directory so Python does not find tetra3.py in cwd
# and import it as a flat module instead of the installed tetra3 package.
# If cwd is inside the tetra3 source tree, 'import tetra3' resolves to
# tetra3.py directly, which then fails on 'from tetra3.breadth_first_combinations'
# because a flat file has no sub-modules.
cd /tmp

python3 - <<'PYEOF'
import os
import tetra3

t3 = tetra3.Tetra3(load_database=None)
hip_path = os.path.join(os.path.dirname(tetra3.__file__), 'hip_main.dat')
t3.generate_database(
    max_fov=14,
    save_as='t3_fov14_mag8',
    star_catalog=hip_path,
    star_max_magnitude=8,
)
print("  Database generation complete.")
PYEOF

DB_PATH="$TETRA3_PKG/data/t3_fov14_mag8.npz"
if [ -f "$DB_PATH" ]; then
    echo "  ✓ Database created: $DB_PATH"
    ls -lh "$DB_PATH"
else
    echo "ERROR: t3_fov14_mag8.npz not found at $DB_PATH"
    exit 1
fi

# Clean up Hipparcos catalogue (51 MB, not needed at runtime)
rm -f "$TETRA3_PKG/hip_main.dat"

# Fix ownership of everything in the cedar-solve dir
chown -R "$EFINDER_USER:$EFINDER_USER" "$CEDAR_SOLVE_DIR"

# NOTE: purge of build tools (rustc, cargo, build-essential…) is left to
# install-complete.sh so nothing in Phase 3 is broken by an early purge.

echo ""
echo "============================================================================="
echo " Cedar installation complete"
echo "  cedar-detect-server : $(which cedar-detect-server)"
echo "  cedar-solve clone   : $CEDAR_SOLVE_DIR"
echo "  cedar-solve venv    : $CEDAR_SOLVE_DIR/.cedar_venv"
echo "  tetra3 source       : $TETRA3_PKG"
echo "  Database            : $DB_PATH"
echo "============================================================================="
