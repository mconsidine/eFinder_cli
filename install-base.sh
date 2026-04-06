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
apt-get install -y --no-install-recommends\
    git curl wget unzip \
    python3-pip python3-venv \
    python3-pil python3-smbus python3-picamera2 python3-scipy \
    samba samba-common-bin \
    apache2 php8.2 libapache2-mod-php8.2 \
    build-essential cmake pkg-config \
    libcfitsio-dev libssl-dev

echo "Installing rust/cargo"
set -e

curl https://sh.rustup.rs -sSf | sh -s -- -y
. "$HOME/.cargo/env"

# GitHub Actions compatibility (safe on normal Linux too)
if [ -n "$GITHUB_PATH" ]; then
    echo "$HOME/.cargo/bin" >> "$GITHUB_PATH"
fi

cargo --version

# Optional: full system upgrade (commented out for speed in automated builds)
# apt-get upgrade -y

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

systemctl daemon-reload
systemctl enable cpu-performance.service

echo ""
echo "============================================================================="
echo " Base system setup complete"
echo "  User: $EFINDER_USER"
echo "  Home: $EFINDER_HOME"
echo "============================================================================="
