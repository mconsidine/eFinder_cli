#!/bin/bash
# =============================================================================
# eFinder install_cedar_v2.sh — first-boot finalisation only
#
# Everything that previously required internet access (apt packages, Python
# venv, cedar-detect binary, gRPC stubs, star database, web files) is now
# baked into the image during the CI build.
#
# This script's only remaining job is to perform the handful of tasks that
# CANNOT be done at image-build time because they depend on runtime state:
#
#   1. Fix filesystem ownership  (efinder user UID is assigned at runtime)
#   2. Set the WiFi AP SSID from the actual wlan0 MAC address
#   3. Write the Samba password into the running smbd
#   4. Write /boot/firmware/config.txt and cmdline.txt camera/USB overlays
#   5. Activate fstab tmpfs mounts
#   6. Apply sudoers rule for /bin/date
#   7. Enable all pre-installed systemd units
#   8. Mark install complete and reboot
#
# Usage (called from firstrun.sh, never run directly):
#   bash /home/efinder/install_cedar_v2.sh
#
# WIFI_PASS and SAMBA_PASS are sourced from /home/efinder/config.env before
# this script is called.
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
INSTALL_MARKER="$EFINDER_HOME/.efinder_installed"

echo "============================================================================="
echo " eFinder first-boot finalisation (Cedar v2 — offline image)"
echo " $(date)"
echo "============================================================================="

# WIFI_PASS and SAMBA_PASS must already be in the environment (from config.env).
: "${WIFI_PASS:?ERROR: WIFI_PASS not set}"
: "${SAMBA_PASS:?ERROR: SAMBA_PASS not set}"

# ---------------------------------------------------------------------------
# 1. Fix ownership — the efinder user's UID is only known at runtime.
#    Everything under /home/efinder was placed as root during the CI build.
# ---------------------------------------------------------------------------
echo "[1] Fixing ownership of $EFINDER_HOME..."
chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME"

# ---------------------------------------------------------------------------
# 2. WiFi AP SSID — derived from the actual wlan0 MAC at runtime.
# ---------------------------------------------------------------------------
echo "[2] Configuring WiFi AP..."
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || \
      ip link show wlan0 | awk '/ether/{print $2}')
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"

echo "  SSID     : $SSID"
echo "  Password : $WIFI_PASS"

# Write the hotspot info file that eFinder.py can read.
sudo -u "$EFINDER_USER" tee "$EFINDER_HOME/Solver/default_hotspot.txt" > /dev/null <<EOF
ssid:${SSID}
password:${WIFI_PASS}
EOF

# The AP connection profile was pre-created in the image with SSID
# "efinder_PLACEHOLDER".  Update the SSID and password to the real values now.
nmcli connection modify "efinder-ap" ssid "$SSID"
nmcli connection modify "efinder-ap" wifi-sec.psk "$WIFI_PASS"
nmcli connection up "efinder-ap" || true

echo "  AP profile updated to SSID '$SSID'."

# ---------------------------------------------------------------------------
# 3. Samba password — smbpasswd writes into a live TDB database and cannot
#    be done offline.
# ---------------------------------------------------------------------------
echo "[3] Setting Samba password for $EFINDER_USER..."
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | smbpasswd -s -a "$EFINDER_USER"
systemctl enable --now smbd

# ---------------------------------------------------------------------------
# 4. Boot firmware — config.txt and cmdline.txt modifications require the
#    live /boot/firmware mount; safe to do here before the first real reboot.
# ---------------------------------------------------------------------------
echo "[4] Configuring /boot/firmware/config.txt..."
BOOT_CONFIG=/boot/firmware/config.txt
sudo cp "$BOOT_CONFIG" "${BOOT_CONFIG}.bak"

sudo sed -i \
    -e '/^\s*dtoverlay=vc4-kms-v3d/s/^/#/' \
    -e '/^\s*max_framebuffers=/s/^/#/' \
    "$BOOT_CONFIG"

sudo sed -i \
    -e '/^\s*dtoverlay=dwc2/d' \
    -e '/^\s*enable_uart/d' \
    -e '/^\s*dtoverlay=arducam/d' \
    -e '/^\s*dtoverlay=imx477/d' \
    -e '/^\s*camera_auto_detect/d' \
    -e '/^# --- eFinder additions/d' \
    -e '/^# IMX477 camera/d' \
    -e '/^# USB gadget serial/d' \
    "$BOOT_CONFIG"

sudo tee -a "$BOOT_CONFIG" > /dev/null <<'EOF'

# --- eFinder additions ---
# IMX477 camera (RPi HQ Camera or Arducam IMX477)
camera_auto_detect=0
dtoverlay=imx477

# USB gadget serial — enables /dev/ttyGS0 for tethered console
dtoverlay=dwc2,dr_mode=peripheral
enable_uart=1
EOF

echo "  config.txt updated."

CMDLINE=/boot/firmware/cmdline.txt
if ! grep -q "modules-load=dwc2,g_serial" "$CMDLINE"; then
    sudo sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' "$CMDLINE"
    echo "  cmdline.txt updated."
else
    echo "  cmdline.txt already correct — no change."
fi

# ---------------------------------------------------------------------------
# 5. Activate tmpfs mounts (fstab entries were written during CI build).
# ---------------------------------------------------------------------------
echo "[5] Activating tmpfs mounts..."
mount -a || echo "WARNING: mount -a had errors — check /etc/fstab"

# ---------------------------------------------------------------------------
# 6. Sudoers rule for /bin/date (efinder needs to set the clock).
# ---------------------------------------------------------------------------
echo "[6] Writing sudoers rule..."
SUDOERS_FILE=/etc/sudoers.d/efinder-date
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/date" | \
        tee "$SUDOERS_FILE" > /dev/null
    chmod 440 "$SUDOERS_FILE"
    echo "  Sudoers rule written."
else
    echo "  Sudoers rule already present."
fi

# ---------------------------------------------------------------------------
# 7. Enable all pre-installed systemd units.
#    The unit files were written into the image during the CI build;
#    daemon-reload and enable are the only runtime steps needed.
# ---------------------------------------------------------------------------
echo "[7] Enabling systemd services..."
systemctl daemon-reload
systemctl enable cpu-performance.service
systemctl enable efinder-update.service
systemctl enable cedar-detect.service
systemctl enable efinder.service
systemctl enable ssh
echo "  All services enabled."

# ---------------------------------------------------------------------------
# 8. Done — mark complete and trigger the real first operational reboot.
# ---------------------------------------------------------------------------
echo ""
echo "============================================================================="
echo " First-boot finalisation complete: $(date)"
echo "   WiFi AP : SSID='$SSID'  Password='$WIFI_PASS'"
echo "   SSH     : ssh efinder@192.168.50.1"
echo "   Samba   : efindershare (user: efinder)"
echo "============================================================================="

date > "$INSTALL_MARKER"
