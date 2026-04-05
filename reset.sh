#!/bin/bash
# =============================================================================
# eFinder reset.sh — wipe all eFinder installation artefacts and re-run
# the installer from the repo. Does NOT reburn the OS or remove apt packages.
#
# Usage:
#   bash reset.sh          — interactive (prompts before wiping)
#   bash reset.sh --yes    — non-interactive (no prompts)
#
# After running, the full installer is re-invoked automatically.
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder

# ---------------------------------------------------------------------------
# Confirm before doing anything destructive
# ---------------------------------------------------------------------------
if [[ "${1:-}" != "--yes" ]]; then
    echo "============================================================================="
    echo " eFinder Reset"
    echo " This will remove all eFinder files, services, and configuration."
    echo " apt packages are preserved. The OS is not touched."
    echo " The installer will be re-run automatically afterwards."
    echo "============================================================================="
    read -rp "Continue? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

echo ""
echo "[1] Stopping and disabling services..."
sudo systemctl stop efinder          2>/dev/null || true
sudo systemctl stop efinder-update   2>/dev/null || true
sudo systemctl disable efinder          2>/dev/null || true
sudo systemctl disable efinder-update   2>/dev/null || true
sudo systemctl disable cpu-performance  2>/dev/null || true

echo "[2] Removing systemd unit files..."
sudo rm -f /etc/systemd/system/efinder.service
sudo rm -f /etc/systemd/system/efinder-update.service
sudo rm -f /etc/systemd/system/cpu-performance.service
sudo systemctl daemon-reload

echo "[3] Removing venv and tetra3 source..."
rm -rf "$EFINDER_HOME/venv-efinder"
rm -rf "$EFINDER_HOME/tetra3_source"

echo "[4] Removing repo bundle and Solver directory..."
rm -rf "$EFINDER_HOME/eFinder_cli"
rm -rf "$EFINDER_HOME/Solver"

echo "[5] Clearing uploads directory..."
rm -f "$EFINDER_HOME/uploads/"*

echo "[6] Removing web files..."
sudo rm -f /var/www/html/index.php
sudo rm -f /var/www/html/stream.php
sudo rm -f /var/www/html/log.php
sudo rm -f /var/www/html/upload.php
sudo rm -f /var/www/html/updater.html
sudo rm -f /var/www/html/README.md
sudo a2disconf efinder 2>/dev/null || true
sudo rm -f /etc/apache2/conf-available/efinder.conf
sudo systemctl reload apache2 2>/dev/null || true

echo "[7] Removing sudoers rule..."
sudo rm -f /etc/sudoers.d/efinder-date

echo "[8] Removing helper scripts..."
rm -f "$EFINDER_HOME/station.sh"

echo "[9] Removing fstab tmpfs entries..."
sudo sed -i '/efinder\/Solver\/images/d' /etc/fstab
sudo sed -i '/^tmpfs \/var\/tmp/d' /etc/fstab

echo "[10] Removing sysctl swap setting..."
sudo sed -i '/vm.swappiness/d' /etc/sysctl.conf

echo "[11] Removing NetworkManager AP profile..."
sudo rm -f /etc/NetworkManager/system-connections/efinder-ap.nmconnection
sudo nmcli connection reload 2>/dev/null || true

echo "[12] Removing install marker..."
rm -f "$EFINDER_HOME/.efinder_installed"

echo ""
echo "============================================================================="
echo " Reset complete. Re-running installer..."
echo "============================================================================="
echo ""

curl -sSL \
    https://raw.githubusercontent.com/mconsidine/eFinder_cli/tinySS/install.sh \
    | sudo bash
