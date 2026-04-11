#!/bin/bash
# =============================================================================
# install-complete.sh — Complete eFinder Installation
# 
# Orchestrates all three installation phases:
#   1. Base system setup (user, packages, directories)
#   2. Cedar-solve compilation and database generation
#   3. eFinder application deployment and configuration
#
# Usage:
#   One-line bootstrap (downloads all scripts and runs):
#     curl -sSL https://raw.githubusercontent.com/mconsidine/eFinder_cli/enhanced/install-complete.sh | sudo bash
#
#   Interactive (prompts for passwords):
#     sudo bash install-complete.sh
#
#   Non-interactive (for automation):
#     export WIFI_PASSWORD=your_wifi_pass
#     export SAMBA_PASSWORD=your_samba_pass
#     export USER_PASSWORD=your_user_pass
#     sudo -E bash install-complete.sh --non-interactive
#
# Environment Variables:
#   WIFI_PASSWORD   - WiFi AP password (default: 12345678)
#   SAMBA_PASSWORD  - Samba share password (default: same as WIFI_PASSWORD)
#   USER_PASSWORD   - efinder user password (default: 12345678)
# =============================================================================
set -eo pipefail

NON_INTERACTIVE=false

if [[ "$1" == "--non-interactive" ]] || [[ "$NON_INTERACTIVE" == "1" ]]; then
    NON_INTERACTIVE=true
fi

# Base URL for downloading phase scripts if not present locally
GITHUB_RAW_BASE="https://raw.githubusercontent.com/mconsidine/eFinder_cli/enhanced"

echo "============================================================================="
echo " eFinder Complete Installation"
echo " Mode: $( [ "$NON_INTERACTIVE" = true ] && echo "Non-Interactive" || echo "Interactive" )"
echo "============================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

# Get credentials
if [ "$NON_INTERACTIVE" = false ]; then
    echo ""
    echo "Enter installation credentials:"
    read -rsp "WiFi AP Password (min 8 chars): " WIFI_PASSWORD; echo
    read -rsp "Samba Password (min 8 chars): " SAMBA_PASSWORD; echo
    read -rsp "User 'efinder' Password: " USER_PASSWORD; echo
    
    # Validate passwords
    if [ ${#WIFI_PASSWORD} -lt 8 ]; then
        echo "ERROR: WiFi password must be at least 8 characters"
        exit 1
    fi
    
    export WIFI_PASSWORD
    export SAMBA_PASSWORD
    export USER_PASSWORD
else
    # In non-interactive mode, check environment variables
    : "${WIFI_PASSWORD:=12345678}"
    : "${SAMBA_PASSWORD:=$WIFI_PASSWORD}"
    : "${USER_PASSWORD:=12345678}"
    
    export WIFI_PASSWORD
    export SAMBA_PASSWORD
    export USER_PASSWORD
fi

# Determine script directory (where the phase scripts should be)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Function to download a script if it doesn't exist locally
download_script() {
    local script_name="$1"
    local script_path="$SCRIPT_DIR/$script_name"
    
    if [ ! -f "$script_path" ]; then
        echo "  Downloading $script_name from GitHub..."
        if command -v curl > /dev/null 2>&1; then
            curl -sSL "$GITHUB_RAW_BASE/$script_name" -o "$script_path"
        elif command -v wget > /dev/null 2>&1; then
            wget -q "$GITHUB_RAW_BASE/$script_name" -O "$script_path"
        else
            echo "ERROR: Neither curl nor wget available"
            exit 1
        fi
        chmod +x "$script_path"
    fi
}

# Ensure all phase scripts are available
echo "Preparing installation scripts..."
download_script "install-base.sh"
download_script "install-cedar.sh"
download_script "install-efinder.sh"

echo ""
echo "Installation will proceed in 3 phases:"
echo "  Phase 1: Base system setup (~5 minutes)"
echo "  Phase 2: Cedar-solve compilation (~15-25 minutes on Pi Zero 2W)"
echo "  Phase 3: eFinder application deployment (~3 minutes)"
echo ""

if [ "$NON_INTERACTIVE" = false ]; then
    read -rp "Continue? [Y/n] " confirm
    [[ "$confirm" =~ ^[Nn]$ ]] && { echo "Aborted."; exit 0; }
fi

# Phase 1: Base System Setup
echo ""
echo "============================================================================="
echo " PHASE 1/3: Base System Setup"
echo "============================================================================="

if [ -f "$SCRIPT_DIR/install-base.sh" ]; then
    bash "$SCRIPT_DIR/install-base.sh" 2>&1 | tee /tmp/install-base.log
else
    echo "ERROR: install-base.sh not found in $SCRIPT_DIR"
    exit 1
fi

# Phase 2: Cedar-solve Compilation
echo ""
echo "============================================================================="
echo " PHASE 2/3: Cedar-solve Compilation"
echo "============================================================================="

if [ -f "$SCRIPT_DIR/install-cedar.sh" ]; then
    bash "$SCRIPT_DIR/install-cedar.sh" 2>&1 | tee /tmp/install-cedar.log
else
    echo "ERROR: install-cedar.sh not found in $SCRIPT_DIR"
    exit 1
fi

# Phase 3: eFinder Application
echo ""
echo "============================================================================="
echo " PHASE 3/3: eFinder Application"
echo "============================================================================="

if [ -f "$SCRIPT_DIR/install-efinder.sh" ]; then
    bash "$SCRIPT_DIR/install-efinder.sh" 2>&1 | tee /tmp/install-efinder.log
else
    echo "ERROR: install-efinder.sh not found in $SCRIPT_DIR"
    exit 1
fi

echo "Performing final image slimming..."
# Remove build-time dependencies
apt-get purge -y rustc cargo build-essential cmake pkg-config libssl-dev
# Remove packages orphaned by the purge
apt-get autoremove -y
# Clear out the local repository of retrieved package files
apt-get clean
# Remove man pages and documentation (optional, but saves space)
rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/*

# Installation complete
echo ""
echo "============================================================================="
echo " INSTALLATION COMPLETE!"
echo "============================================================================="
echo ""
echo "Installation logs saved to:"
echo "  /tmp/install-base.log"
echo "  /tmp/install-cedar.log"
echo "  /tmp/install-efinder.log"
echo ""
echo "A reboot is required to activate all changes."
echo ""

if [ "$NON_INTERACTIVE" = false ]; then
    read -rp "Reboot now? [Y/n] " reboot_confirm
    if [[ ! "$reboot_confirm" =~ ^[Nn]$ ]]; then
        echo "Rebooting in 3 seconds..."
        sleep 3
        reboot
    else
        echo "Please reboot manually when ready: sudo reboot"
    fi
else
    echo "Rebooting in 5 seconds (non-interactive mode)..."
    sleep 5
    if command -v systemctl >/dev/null 2>&1; then
      systemctl reboot || true
    else
      echo "Reboot skipped (no systemd environment)"
fi

fi
