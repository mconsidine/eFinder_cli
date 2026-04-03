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
#   8. Mark install complete
#
# Usage (triggered by firstrun.service on first boot, never run directly):
#   /bin/bash /home/efinder/install_cedar_v2.sh
#
# WIFI_PASS and SAMBA_PASS are sourced directly from /home/efinder/config.env
# at the top of this script. The calling service does not need to pre-export
# them; the script is self-contained.
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
INSTALL_MARKER="$EFINDER_HOME/.efinder_installed"

echo "============================================================================="
echo " eFinder first-boot finalisation (Cedar v2 — offline image)"
echo " $(date)"
echo "============================================================================="

# Source credentials from the baked-in config file.
# shellcheck source=/dev/null
source "$EFINDER_HOME/config.env"
export WIFI_PASS SAMBA_PASS

: "${WIFI_PASS:?ERROR: WIFI_PASS not set in $EFINDER_HOME/config.env}"
: "${SAMBA_PASS:?ERROR: SAMBA_PASS not set in $EFINDER_HOME/config.env}"

# ---------------------------------------------------------------------------
# 1. Fix ownership — the efinder user's UID is only known at runtime.
#    Everything under /home/efinder was placed as root during the CI build.
# ---------------------------------------------------------------------------
echo "[1] Fixing ownership of $EFINDER_HOME..."
chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME"
# apply_update.sh must remain root-owned (runs as root via efinder-update.service).
chown root:root "$EFINDER_HOME/Solver/apply_update.sh"

# ---------------------------------------------------------------------------
# 2. WiFi AP SSID — derived from the actual wlan0 MAC at runtime.
#    The connection profile was written to disk during the CI build with a
#    placeholder SSID.  Reload it first so NetworkManager sees the file,
#    then modify the live connection to use the real SSID and password.
# ---------------------------------------------------------------------------
echo "[2] Configuring WiFi AP..."
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || \
      ip link show wlan0 | awk '/ether/{print $2}')
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"

echo "  SSID     : $SSID"
echo "  Password : $WIFI_PASS"

# Write the hotspot info file read by eFinder_cedar_v2.py.
sudo -u "$EFINDER_USER" tee "$EFINDER_HOME/Solver/default_hotspot.txt" > /dev/null <<EOF
ssid:${SSID}
password:${WIFI_PASS}
EOF

# Reload connection files from disk so NetworkManager picks up the
# pre-written efinder-ap.nmconnection before we try to modify it.
nmcli connection reload

nmcli connection modify "efinder-ap" ssid "$SSID"
nmcli connection modify "efinder-ap" wifi-sec.psk "$WIFI_PASS"
nmcli connection up "efinder-ap" || \
    echo "WARNING: nmcli connection up efinder-ap failed — AP may not start until reboot."

echo "  AP profile updated to SSID '$SSID'."

# ---------------------------------------------------------------------------
# 3. Samba password — smbpasswd writes into a live TDB database and cannot
#    be done at image-build time.
# ---------------------------------------------------------------------------
echo "[3] Setting Samba password for $EFINDER_USER..."
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | smbpasswd -s -a "$EFINDER_USER"
systemctl enable --now smbd

# ---------------------------------------------------------------------------
# 4. Boot firmware — config.txt and cmdline.txt modifications touch the live
#    /boot/firmware mount; safe to do here before the first real reboot.
# ---------------------------------------------------------------------------
echo "[4] Configuring /boot/firmware/config.txt..."
BOOT_CONFIG=/boot/firmware/config.txt
cp "$BOOT_CONFIG" "${BOOT_CONFIG}.bak"

sed -i \
    -e '/^\s*dtoverlay=vc4-kms-v3d/s/^/#/' \
    -e '/^\s*max_framebuffers=/s/^/#/' \
    "$BOOT_CONFIG"

sed -i \
    -e '/^\s*dtoverlay=dwc2/d' \
    -e '/^\s*enable_uart/d' \
    -e '/^\s*dtoverlay=arducam/d' \
    -e '/^\s*dtoverlay=imx477/d' \
    -e '/^\s*camera_auto_detect/d' \
    -e '/^# --- eFinder additions/d' \
    -e '/^# IMX477 camera/d' \
    -e '/^# USB gadget serial/d' \
    "$BOOT_CONFIG"

tee -a "$BOOT_CONFIG" > /dev/null <<'EOF'

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
    sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' "$CMDLINE"
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
# 6. Sudoers rule for /bin/date (efinder needs passwordless clock setting).
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
#    Unit files were written into the image during the CI build.
#    daemon-reload + enable are the only runtime steps needed.
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
# 8. Done — mark complete so firstrun.service does not run again.
#    The calling firstrun.service removes .run_firstrun; the marker file here
#    provides an additional human-readable record of when install completed.
# ---------------------------------------------------------------------------
echo ""
echo "============================================================================="
echo " First-boot finalisation complete: $(date)"
echo "   WiFi AP : SSID='$SSID'  Password='$WIFI_PASS'"
echo "   SSH     : ssh efinder@192.168.50.1"
echo "   Samba   : efindershare (user: efinder)"
echo "   Logs    : journalctl -u efinder -f"
echo "============================================================================="

date > "$INSTALL_MARKER"

# Remove the trigger file so firstrun.service's ConditionPathExists guard
# prevents it from running on subsequent boots.
rm -f "$EFINDER_HOME/.run_firstrun"
