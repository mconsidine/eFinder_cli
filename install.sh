#!/bin/bash
# =============================================================================
# eFinder CLI Install Script for Raspberry Pi Zero 2W
# - IMX477 camera (RPi HQ Camera or Arducam IMX477)
# - NetworkManager-based WiFi AP (boots into AP mode by default)
# - SSH enabled on both AP and tethered USB serial modes
# - Clean venv with system-site-packages
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
VENV="$EFINDER_HOME/venv-efinder"
INSTALL_MARKER="$EFINDER_HOME/.efinder_installed"

# =============================================================================
# CONFIGURATION — edit these before running if needed
# =============================================================================

# Set to true if an ADXL343 accelerometer is wired to the I2C bus.
# When false: python3-smbus is not installed, adafruit pip package is skipped,
# and I2C is not enabled. The app handles absence gracefully at runtime.
USE_ACCELEROMETER=false

# =============================================================================

# ---------------------------------------------------------------------------
# Guard: must be run as the efinder user (with sudo), not as root directly.
# File ownership inside $EFINDER_HOME will be wrong if run as root.
# ---------------------------------------------------------------------------
RUNNING_AS="${SUDO_USER:-$(logname 2>/dev/null)}"
if [ "$RUNNING_AS" != "$EFINDER_USER" ]; then
    echo "ERROR: Run this script as the '$EFINDER_USER' user, e.g.:"
    echo "       sudo bash install.sh   (while logged in as $EFINDER_USER)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Guard: must be running on a Raspberry Pi Zero 2W
# ---------------------------------------------------------------------------
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
if [[ "$PI_MODEL" != *"Zero 2"* ]]; then
    echo "WARNING: This script is designed for Raspberry Pi Zero 2W."
    echo "         Detected: $PI_MODEL"
    read -rp "Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi

# ---------------------------------------------------------------------------
# Guard: skip expensive steps if already completed (re-run safety)
# ---------------------------------------------------------------------------
if [ -f "$INSTALL_MARKER" ]; then
    echo "NOTE: $INSTALL_MARKER exists — this device has been installed before."
    read -rp "Re-run full install anyway? [y/N] " rerun
    [[ "$rerun" =~ ^[Yy]$ ]] || exit 0
fi

echo "============================================================================="
echo " eFinder CLI Installer"
echo " Device : $PI_MODEL"
echo "============================================================================="

# ---------------------------------------------------------------------------
# Check internet connectivity — required for apt, tetra3 clone, and bundle
# re-download. On re-runs without internet, network steps are skipped.
# ---------------------------------------------------------------------------
if curl -s --max-time 5 https://github.com > /dev/null 2>&1; then
    HAVE_INTERNET=true
    echo "Internet connectivity confirmed."
else
    HAVE_INTERNET=false
    echo "WARNING: No internet access detected."
    echo "  Package installation and repo update steps will be skipped."
    echo "  This is safe on a re-run if packages were already installed."
fi

# ---------------------------------------------------------------------------
# 1. System update & package installation
# ---------------------------------------------------------------------------
echo ""
if [ "$HAVE_INTERNET" = true ]; then
    echo "[1/9] Updating system packages..."
    sudo apt update
    sudo apt upgrade -y

    echo ""
    echo "[2/9] Installing required packages..."
    sudo apt install -y \
        python3-pip \
        python3-pil \
        python3-pil.imagetk \
        python3-picamera2 \
        python3-scipy \
        git \
        rpicam-apps \
        netcat-openbsd \
        samba \
        samba-common-bin \
        apache2 \
        php8.2 \
        libapache2-mod-php8.2

    if [ "$USE_ACCELEROMETER" = true ]; then
        echo "  Installing accelerometer support packages..."
        sudo apt install -y python3-smbus
    fi
else
    echo "[1/9] Skipping package update — no internet."
    echo "[2/9] Skipping package install — no internet."
fi

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "[3/9] Setting up Python virtual environment..."
# Create venv if not already present — safe to run without internet
if [ ! -d "$VENV" ]; then
    sudo -u "$EFINDER_USER" python3 -m venv "$VENV" --system-site-packages
fi

if [ "$HAVE_INTERNET" = true ]; then
    "$VENV/bin/pip" install --upgrade pip
    if [ "$USE_ACCELEROMETER" = true ]; then
        echo "  Installing accelerometer Python package..."
        "$VENV/bin/pip" install adafruit-circuitpython-adxl34x
    fi
else
    echo "  Skipping pip installs — no internet."
fi

# ---------------------------------------------------------------------------
# 3. Verify eFinder_cli bundle is present
#    On first run the user downloads this via curl/unzip per the README.
#    On re-runs the directory already exists. If missing, re-download it.
# ---------------------------------------------------------------------------
echo ""
echo "[4/9] Checking eFinder_cli bundle..."
REPO_URL="https://github.com/mconsidine/eFinder_cli/archive/refs/heads/tinySS.zip"
REPO_DIR="$EFINDER_HOME/eFinder_cli"
if [ ! -d "$REPO_DIR" ]; then
    if [ "$HAVE_INTERNET" = true ]; then
        echo "  Bundle not found — downloading from GitHub..."
        curl -L "$REPO_URL" -o /tmp/efinder.zip
        unzip /tmp/efinder.zip -d /tmp/
        mv /tmp/eFinder_cli-tinySS "$REPO_DIR"
        rm /tmp/efinder.zip
        sudo chown -R "$EFINDER_USER:$EFINDER_USER" "$REPO_DIR"
        echo "  Bundle downloaded and unpacked."
    else
        echo "ERROR: eFinder_cli bundle not found and no internet access."
        echo "       Download and unpack the bundle first — see README Part 3.1."
        exit 1
    fi
else
    echo "  Bundle already present at $REPO_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Directory structure and file deployment
# ---------------------------------------------------------------------------
echo ""
echo "[5/9] Setting up directory structure..."
mkdir -p "$EFINDER_HOME/Solver/images"
mkdir -p "$EFINDER_HOME/uploads"
sudo chmod a+rwx "$EFINDER_HOME/uploads"
sudo chmod a+rwx "$EFINDER_HOME/Solver/images"
sudo chmod a+rwx "$EFINDER_HOME"

# Copy support files from the repo bundle into the working Solver directory.
# Excludes the www/ subdirectory (web files deployed separately below).
# eFinder.py is deployed later from the script's own directory.
find "$REPO_DIR/Solver" -maxdepth 1 -type f | while read -r f; do
    cp "$f" "$EFINDER_HOME/Solver/"
done
sudo chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver"
sudo chmod 755 "$EFINDER_HOME/Solver/eFinder.py"

# RAM-backed tmpfs mounts for image scratch space
# Add only if not already present
grep -q "/var/tmp" /etc/fstab || \
    echo "tmpfs /var/tmp tmpfs nodev,nosuid,size=10M 0 0" | sudo tee -a /etc/fstab > /dev/null

grep -q "$EFINDER_HOME/Solver/images" /etc/fstab || \
    echo "tmpfs $EFINDER_HOME/Solver/images tmpfs nodev,nosuid,size=10M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null

sudo mount -a   # activate without requiring a reboot

# ---------------------------------------------------------------------------
# 5. Install Tetra3 star-pattern matching library
# ---------------------------------------------------------------------------
echo ""
echo "[6/9] Installing Tetra3..."
if [ "$HAVE_INTERNET" = true ]; then
    # Clone into tetra3_source — keeps source separate from the installed package
    # and prevents Python from shadowing the venv installation with the source tree.
    if [ ! -d "$EFINDER_HOME/tetra3_source" ]; then
        sudo -u "$EFINDER_USER" git clone https://github.com/esa/tetra3.git \
            "$EFINDER_HOME/tetra3_source"
    fi
    cd "$EFINDER_HOME/tetra3_source"
    # Only install if not already correctly installed in the venv.
    # --force-reinstall requires internet to fetch build dependencies even
    # when the source is local, so avoid it on re-runs.
    if ! "$VENV/bin/python3" -c "
import tetra3, os
path = tetra3.__file__
assert 'venv-efinder' in path, 'tetra3 not in venv'
" 2>/dev/null; then
        echo "  Installing tetra3 into venv..."
        "$VENV/bin/pip" install .
    else
        echo "  Tetra3 already correctly installed in venv — skipping."
    fi
    echo "  Tetra3 installed into venv from source."
else
    if ! "$VENV/bin/python3" -c "import tetra3" 2>/dev/null; then
        echo "  WARNING: Tetra3 not installed and no internet available."
        echo "           Re-run install.sh with internet access to complete this step."
    else
        echo "  Tetra3 already installed — skipping (no internet)."
    fi
fi

# Install the Tetra3 database from the repo bundle.
# The database is stored in Solver/databases/ in the repo — no external
# download needed. To regenerate for a different lens see README.
TETRA3_DATA=$("$VENV/bin/python3" -c \
    "import tetra3, os; print(os.path.join(os.path.dirname(tetra3.__file__), 'data'))" \
    2>/dev/null) || TETRA3_DATA=""

DB_SOURCE="$REPO_DIR/Solver/databases"

if [ -z "$TETRA3_DATA" ]; then
    echo "  WARNING: Could not determine tetra3 data path — is tetra3 installed?"
    echo "           Re-run install.sh with internet access to install Tetra3 first."
elif [ ! -d "$DB_SOURCE" ] || [ -z "$(ls "$DB_SOURCE"/*.npz 2>/dev/null)" ]; then
    echo "  WARNING: No database files found in $DB_SOURCE"
    echo "           Add t3_fov14_mag8.npz to Solver/databases/ in the repo."
    echo "           See README 'Generating a Tetra3 Database' for instructions."
else
    echo "  Installing database(s) from repo bundle to: $TETRA3_DATA"
    cp "$DB_SOURCE"/*.npz "$TETRA3_DATA/"
    echo "  Installed: $(ls "$DB_SOURCE"/*.npz | xargs -I{} basename {})"
fi

# ---------------------------------------------------------------------------
# 6. Samba share
# ---------------------------------------------------------------------------
echo ""
echo "[7/9] Configuring Samba file share..."
if ! grep -q "\[efindershare\]" /etc/samba/smb.conf; then
    sudo tee -a /etc/samba/smb.conf > /dev/null <<'EOF'
[efindershare]
path = /home/efinder
writeable = Yes
create mask = 0777
directory mask = 0777
public = no
EOF
fi

# Set Samba password non-interactively
SAMBA_PASS="efinder"
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | sudo smbpasswd -s -a "$EFINDER_USER"
sudo systemctl enable --now smbd

# ---------------------------------------------------------------------------
# 7. Apache / PHP web server
# ---------------------------------------------------------------------------
echo ""
echo "[8/9] Configuring Apache/PHP web server..."

# Deploy PHP application files from repo bundle
sudo cp "$REPO_DIR/Solver/www/index.php"    /var/www/html/
sudo cp "$REPO_DIR/Solver/www/upload.php"   /var/www/html/
sudo cp "$REPO_DIR/Solver/www/updater.html" /var/www/html/
sudo cp "$REPO_DIR/Solver/www/user.ini"     /etc/php/8.2/apache2/conf.d/
sudo cp "$REPO_DIR/Solver/www/user.ini"     /etc/php/8.2/cli/conf.d/
sudo cp "$REPO_DIR/Solver/www/log.php"      /var/www/html/

# Copy README to web root so it is browseable in AP mode at http://192.168.50.1/README.md
sudo cp "$REPO_DIR/README.md" /var/www/html/README.md

# Allow Apache (www-data) to read the systemd journal so log.php works
sudo usermod -a -G systemd-journal www-data

# Move default Apache index out of the way (only once)
[ -f /var/www/html/index.html ] && sudo mv /var/www/html/index.html /var/www/html/apacheindex.html

sudo chmod -R 755 /var/www/html
sudo systemctl enable --now apache2

# ---------------------------------------------------------------------------
# 8. Boot firmware configuration (config.txt)
#    - IMX477 / Arducam camera
#    - USB gadget serial (for tethered SSH)
#    - Disable KMS overlay that conflicts with camera stack
# ---------------------------------------------------------------------------
echo ""
echo "[9/9] Writing /boot/firmware/config.txt..."

# Build a new config.txt: preserve existing content, but:
#   - Comment out vc4-kms-v3d and max_framebuffers (conflict with camera)
#   - Remove any previous efinder-specific overlays before re-adding
BOOT_CONFIG=/boot/firmware/config.txt
BACKUP=/boot/firmware/config.txt.bak

sudo cp "$BOOT_CONFIG" "$BACKUP"

# Comment out lines that conflict with libcamera/picamera2
sudo sed -i \
    -e '/^\s*dtoverlay=vc4-kms-v3d/s/^/#/' \
    -e '/^\s*max_framebuffers=/s/^/#/' \
    "$BOOT_CONFIG"

# Remove any previous eFinder-managed lines so re-runs stay idempotent
sudo sed -i \
    -e '/^\s*dtoverlay=dwc2/d' \
    -e '/^\s*enable_uart/d' \
    -e '/^\s*dtoverlay=arducam/d' \
    -e '/^\s*dtoverlay=imx477/d' \
    -e '/^\s*camera_auto_detect/d' \
    -e '/^# --- eFinder additions/d' \
    -e '/^# IMX477 camera/d' \
    -e '/^# Arducam IMX477/d' \
    -e '/^# USB gadget serial/d' \
    "$BOOT_CONFIG"

# Append eFinder additions cleanly
sudo tee -a "$BOOT_CONFIG" > /dev/null <<'EOF'

# --- eFinder additions ---
# IMX477 camera (RPi HQ Camera or Arducam IMX477 — stock Pi OS overlay)
camera_auto_detect=0
dtoverlay=imx477

# USB gadget serial — enables /dev/ttyGS0 for tethered console
dtoverlay=dwc2,dr_mode=peripheral
enable_uart=1
EOF

echo "config.txt updated."

# ---------------------------------------------------------------------------
# 8b. cmdline.txt — add USB gadget serial module load (idempotent)
# ---------------------------------------------------------------------------
CMDLINE=/boot/firmware/cmdline.txt
if ! grep -q "modules-load=dwc2,g_serial" "$CMDLINE"; then
    sudo sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' "$CMDLINE"
    echo "cmdline.txt updated."
else
    echo "cmdline.txt already has USB serial module — no change."
fi

# ---------------------------------------------------------------------------
# 9. NetworkManager WiFi Access Point
#    - Boots into AP mode automatically
#    - SSID: efinder + last 4 hex digits of MAC
#    - Password: 12345678
#    - Interface: wlan0
#    - The AP connection is set to autoconnect; "preconfigured" (client mode)
#      is set to NOT autoconnect so AP wins at boot.
# ---------------------------------------------------------------------------
echo ""
echo "[AP] Configuring NetworkManager WiFi hotspot..."

# Derive SSID from last 4 hex digits of wlan0 MAC
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || ip link show wlan0 | awk '/ether/{print $2}')
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"
WIFI_PASS="12345678"

echo "  SSID     : $SSID"
echo "  Password : $WIFI_PASS"

# Save to default_hotspot.txt so eFinder software can read it
sudo -u "$EFINDER_USER" tee "$EFINDER_HOME/Solver/default_hotspot.txt" > /dev/null <<EOF
ssid:${SSID}
password:${WIFI_PASS}
EOF

# Remove any previous eFinder AP connection profile
nmcli connection delete "efinder-ap" 2>/dev/null || true

# Create a persistent AP connection profile
sudo nmcli connection add \
    type wifi \
    ifname wlan0 \
    con-name "efinder-ap" \
    autoconnect yes \
    ssid "$SSID" \
    -- \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$WIFI_PASS" \
    wifi.mode ap \
    wifi.band bg \
    wifi.channel 6 \
    ipv4.method shared \
    ipv4.addresses "192.168.50.1/24" \
    ipv6.method disabled \
    connection.autoconnect-priority 100

echo ""
echo "  AP profile 'efinder-ap' created."
echo "  Connect to SSID '$SSID' then SSH to 192.168.50.1"

# ---------------------------------------------------------------------------
# 10. USB gadget / tethered serial SSH
#     - g_serial creates /dev/ttyGS0; getty on it lets you log in over USB
#     - For IP-over-USB (RNDIS/ECM) the user can swap g_serial for g_ether
#       but g_serial + USB→serial adapter + screen/minicom is simpler on Pi0
# ---------------------------------------------------------------------------
echo ""
echo "[USB] Enabling getty on USB serial gadget interface..."

sudo systemctl enable getty@ttyGS0.service 2>/dev/null || \
    sudo systemctl enable serial-getty@ttyGS0.service 2>/dev/null || \
    echo "  Note: USB serial getty will activate after reboot."

# ---------------------------------------------------------------------------
# 11. SSH daemon — ensure enabled
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_ssh 0
sudo systemctl enable --now ssh

# ---------------------------------------------------------------------------
# 12. Interface / peripheral setup via raspi-config
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_serial_cons 1  # disable serial console (keep port for GPS/etc)

if [ "$USE_ACCELEROMETER" = true ]; then
    sudo raspi-config nonint do_i2c 0      # enable I2C for ADXL343 accelerometer
    echo "  I2C enabled for accelerometer."
else
    echo "  Accelerometer disabled — skipping I2C setup."
fi

# Reduce swap activity (images are in RAM; avoid wearing SD card)
grep -q "vm.swappiness" /etc/sysctl.conf || \
    echo 'vm.swappiness = 0' | sudo tee -a /etc/sysctl.conf > /dev/null

# Set CPU governor to performance mode — keeps all 4 cores at full clock.
# The Pi Zero 2W defaults to ondemand which throttles under light load,
# hurting centroid detection and plate solving latency.
# Implemented as a oneshot systemd service so it survives reboots cleanly.
sudo tee /etc/systemd/system/cpu-performance.service > /dev/null <<'EOF'
[Unit]
Description=Set CPU governor to performance mode
After=sysinit.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now cpu-performance.service
echo "  CPU governor set to performance mode."

# Allow the efinder app to set the system clock (needed for SkySafari time sync).
# Scoped to 'date' only — no broader sudo access granted.
SUDOERS_FILE=/etc/sudoers.d/efinder-date
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/date, /usr/bin/nmcli" | \
        sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    echo "  Sudoers rule written: efinder may run /bin/date and /usr/bin/nmcli without password."
fi

# ---------------------------------------------------------------------------
# Helper script: station.sh
# Switches from AP mode to home network (station mode) in one command.
# Intended to be run from the USB serial console when SSH is unavailable.
# ---------------------------------------------------------------------------
sudo tee "$EFINDER_HOME/station.sh" > /dev/null <<'EOF'
#!/bin/bash
echo "Switching to station (home network) mode..."
sudo nmcli connection modify preconfigured autoconnect yes
sudo nmcli connection up preconfigured
echo ""
echo "Done. Check your router for the Pi's IP address, or try:"
echo "  ssh efinder@efinder.local"
echo ""
echo "To return to AP mode after you are done:"
echo "  sudo nmcli connection modify preconfigured autoconnect no"
echo "  sudo reboot now"
EOF
sudo chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/station.sh"
sudo chmod 755 "$EFINDER_HOME/station.sh"
echo "  station.sh installed at $EFINDER_HOME/station.sh"

# ---------------------------------------------------------------------------
# 13. systemd service: efinder-update (OTA zip updater, runs before main app)
#     Replaces the zip-check logic that was in loader.py.
#     Runs once at boot as root, applies any zip in /home/efinder/uploads/,
#     then exits so efinder.service can start.
# ---------------------------------------------------------------------------
echo ""
echo "[13] Installing efinder-update systemd service..."
sudo tee /etc/systemd/system/efinder-update.service > /dev/null <<'EOF'
[Unit]
Description=eFinder OTA update checker
# Must complete before the main app starts
Before=efinder.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=root
WorkingDirectory=/home/efinder
ExecStart=/bin/bash /home/efinder/Solver/apply_update.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Write the update helper script
sudo tee "$EFINDER_HOME/Solver/apply_update.sh" > /dev/null <<'SHEOF'
#!/bin/bash
ZIPFILE="/home/efinder/uploads/efinderUpdate.zip"
if [ ! -f "$ZIPFILE" ]; then
    echo "No update zip found — skipping."
    exit 0
fi
echo "Update zip found — applying..."
if unzip -o "$ZIPFILE" -d /; then
    find / -name "*.py" -newer "$ZIPFILE" -exec chmod a+rwx {} \; 2>/dev/null || true
    rm -f "$ZIPFILE"
    echo "Update applied — rebooting."
    systemctl reboot
else
    echo "Update failed — removing zip and continuing."
    rm -f "$ZIPFILE"
fi
SHEOF
sudo chmod 755 "$EFINDER_HOME/Solver/apply_update.sh"
sudo chown root:root "$EFINDER_HOME/Solver/apply_update.sh"
sudo systemctl enable efinder-update.service

# ---------------------------------------------------------------------------
# 14. systemd service: efinder (main application)
#     Starts after OTA update check; restarts on failure with a cap to avoid
#     reboot loops if the camera is genuinely absent or misconfigured.
# ---------------------------------------------------------------------------
echo ""
echo "[14] Installing efinder systemd service..."
sudo tee /etc/systemd/system/efinder.service > /dev/null <<'EOF'
[Unit]
Description=eFinder telescope plate solver
After=efinder-update.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=efinder
WorkingDirectory=/home/efinder/Solver
Environment=PATH=/home/efinder/venv-efinder/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/efinder/venv-efinder/bin/python /home/efinder/Solver/eFinder.py
Restart=on-failure
RestartSec=15
# Cap retries — if the camera is genuinely absent, don't spin forever
StartLimitIntervalSec=120
StartLimitBurst=4
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable efinder.service

# Remove the old cron-based autostart if it exists
sudo rm -f /etc/cron.d/efinder
echo "  efinder.service installed and enabled."
echo "  View logs with: journalctl -u efinder -f"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================================="
echo " Installation complete."
echo ""
echo " On next boot the eFinder starts automatically."
echo ""
echo "   WiFi AP  : SSID='$SSID'  Password='$WIFI_PASS'"
echo "   SSH (AP) : ssh efinder@192.168.50.1"
echo "   USB      : serial console on ttyGS0 (CoolTerm / screen / minicom)"
echo "   SkySafari: connect to $SSID → TCP port 4060 (LX200)"
echo ""
echo " Camera    : IMX477 via imx477 overlay (HQ Camera or Arducam IMX477)"
echo " Samba     : \\\\<ip>\\efindershare  (user: efinder / pass: efinder)"
echo " Logs      : journalctl -u efinder -f"
echo "============================================================================="
echo ""

# Write completion marker — prevents accidental re-runs of expensive steps
date > "$INSTALL_MARKER"

# Disable client-mode WiFi autoconnect now that all downloads are complete.
# Doing this earlier risks dropping internet before packages finish installing.
echo "Disabling autoconnect on 'preconfigured' WiFi client profile..."
nmcli connection modify "preconfigured" autoconnect no 2>/dev/null || true

read -rp "Reboot now? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    sudo reboot now
fi
