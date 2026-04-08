#!/bin/bash
# =============================================================================
# install-base.sh — Phase 1: Base System Setup
# 
# Sets up the base system: user account, directories, and core packages.
# Can be run standalone or as part of automated image build.
#
# Usage:
#   sudo bash install-base.sh
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
USER_PASSWORD="${USER_PASSWORD:-12345678}"

echo "============================================================================="
echo " eFinder Base System Setup"
echo "============================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

echo ""
echo "[1/4] Updating package lists..."
apt-get update

echo ""
echo "[2/4] Installing base packages..."
# Note: python3-pil (apt Pillow) is intentionally excluded here.
# When apt installs Pillow it creates a dist-info directory without a pip
# RECORD file.  Any subsequent 'pip install' that has Pillow as a dependency
# will build a new wheel, then fail trying to uninstall the apt version
# because there is no RECORD to guide the removal.
# Solution: install Pillow once via pip below, before anything else touches it.
#
# libjpeg-dev and zlib1g-dev are the build deps Pillow needs if no binary
# wheel is available for this platform/Python combination.
apt-get install -y --no-install-recommends \
    git curl wget unzip \
    python3-pip python3-venv \
    python3-smbus python3-picamera2 python3-scipy \
    libjpeg-dev zlib1g-dev \
    samba samba-common-bin \
    apache2 php8.2 libapache2-mod-php8.2 \
    build-essential cmake pkg-config \
    libcfitsio-dev libssl-dev \
    protobuf-compiler \
    libprotobuf-dev

echo ""
echo "  Disabling piwheels extra index..."
# Raspberry Pi OS bakes piwheels.org into /etc/pip.conf as an extra-index-url.
# Inside a chroot build environment the SSL cert store is incomplete and TLS
# to piwheels consistently fails with SSLZeroReturnError, causing every pip
# call to retry 5 times before falling back to PyPI.  We override pip.conf
# to use PyPI only.  On a real Pi this is harmless — PyPI carries aarch64
# wheels for all packages we need.
mkdir -p /etc
cat > /etc/pip.conf << 'PIPCFG'
[global]
index-url = https://pypi.org/simple
extra-index-url =
PIPCFG
echo "  pip.conf written — piwheels disabled."

echo ""
echo "  Installing Pillow via pip (avoids apt dist-info/RECORD conflict)..."
# --only-binary=:all: uses a pre-built wheel so libjpeg/zlib are not needed
# at install time (they are still present above in case a source build is ever
# required).  Pillow >=9,<11 is compatible with Python 3.11 on Bookworm and
# with picamera2.
pip3 install --break-system-packages "Pillow>=9.0,<11.0" --only-binary=:all:

echo "Installing rust/cargo"
set -e

curl https://sh.rustup.rs -sSf | sh -s -- -y
. "$HOME/.cargo/env"

# GitHub Actions compatibility (safe on normal Linux too)
if [ -n "$GITHUB_PATH" ]; then
    echo "$HOME/.cargo/bin" >> "$GITHUB_PATH"
fi

cargo --version

echo ""
echo "[3/4] Creating efinder user and directory structure..."

# Create efinder user if it doesn't exist
if ! id -u "$EFINDER_USER" > /dev/null 2>&1; then
    useradd -m -s /bin/bash "$EFINDER_USER"
    echo "${EFINDER_USER}:${USER_PASSWORD}" | chpasswd
    usermod -aG sudo,video "$EFINDER_USER"
    echo "  User '$EFINDER_USER' created with password: $USER_PASSWORD"
else
    echo "  User '$EFINDER_USER' already exists"
fi

# Create directory structure
mkdir -p "$EFINDER_HOME/Solver/images"
mkdir -p "$EFINDER_HOME/Solver/databases"
mkdir -p "$EFINDER_HOME/Solver/www"
mkdir -p "$EFINDER_HOME/uploads"

# Set permissions
chmod a+rwx "$EFINDER_HOME/uploads"
chmod a+rwx "$EFINDER_HOME/Solver/images"
chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME"

echo ""
echo "[4/4] System tuning..."

# Disable swap for SD card longevity
if command -v dphys-swapfile > /dev/null 2>&1; then
    dphys-swapfile swapoff 2>/dev/null || true
    dphys-swapfile uninstall 2>/dev/null || true
    systemctl disable dphys-swapfile 2>/dev/null || true
fi

# Set swappiness to 0
grep -q "vm.swappiness" /etc/sysctl.conf || \
    echo 'vm.swappiness = 0' >> /etc/sysctl.conf

# CPU performance mode
cat > /etc/systemd/system/cpu-performance.service << 'EOF'
[Unit]
Description=Set CPU governor to performance mode
After=sysinit.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'

[Install]
WantedBy=multi-user.target
EOF

systemctl enable --root=/ cpu-performance.service

echo ""
echo "============================================================================="
echo " Base system setup complete"
echo "  User: $EFINDER_USER"
echo "  Home: $EFINDER_HOME"
echo "============================================================================="
