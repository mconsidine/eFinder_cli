#!/bin/bash
# =============================================================================
# eFinder CLI Install Script for Raspberry Pi Zero 2W
# - IMX477 camera (RPi HQ Camera or Arducam IMX477)
# - NetworkManager-based WiFi AP (boots into AP mode by default)
# - SSH enabled on both AP and tethered USB serial modes
# - Clean venv with system-site-packages
#
# Usage:
#   Interactive : sudo bash install.sh
#   Automated   : bash install.sh --non-interactive
#                 (WIFI_PASS and SAMBA_PASS must be exported by the caller)
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
VENV="$EFINDER_HOME/venv-efinder"
INSTALL_MARKER="$EFINDER_HOME/.efinder_installed"
NON_INTERACTIVE=false
[[ "$1" == "--non-interactive" ]] && NON_INTERACTIVE=true

# ---------------------------------------------------------------------------
# Guard: when running interactively, must be run as the efinder user (with
# sudo). Skipped in non-interactive mode (called from firstrun.sh as root).
# ---------------------------------------------------------------------------
if [ "$NON_INTERACTIVE" = false ]; then
    RUNNING_AS="${SUDO_USER:-$(logname 2>/dev/null)}"
    if [ "$RUNNING_AS" != "$EFINDER_USER" ]; then
        echo "ERROR: Run this script as the '$EFINDER_USER' user, e.g.:"
        echo "       sudo bash install.sh   (while logged in as $EFINDER_USER)"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Guard: check hardware model. In non-interactive mode, log a warning and
# continue rather than prompting — no terminal is available.
# ---------------------------------------------------------------------------
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
if [[ "$PI_MODEL" != *"Zero 2"* ]]; then
    echo "WARNING: This script is designed for Raspberry Pi Zero 2W."
    echo "         Detected: $PI_MODEL"
    if [ "$NON_INTERACTIVE" = false ]; then
        read -rp "Continue anyway? [y/N] " confirm
        [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
    else
        echo "         Non-interactive mode — continuing regardless."
    fi
fi

# ---------------------------------------------------------------------------
# Guard: skip expensive steps if already completed (re-run safety).
# In non-interactive mode, always proceed (re-runs are intentional).
# ---------------------------------------------------------------------------
if [ -f "$INSTALL_MARKER" ] && [ "$NON_INTERACTIVE" = false ]; then
    echo "NOTE: $INSTALL_MARKER exists — this device has been installed before."
    read -rp "Re-run full install anyway? [y/N] " rerun
    [[ "$rerun" =~ ^[Yy]$ ]] || exit 0
fi

echo "============================================================================="
echo " eFinder CLI Installer"
echo " Device : $PI_MODEL"
echo " Mode   : $( [ "$NON_INTERACTIVE" = true ] && echo non-interactive || echo interactive )"
echo "============================================================================="

# ---------------------------------------------------------------------------
# Credentials: from environment (non-interactive) or user prompts
# ---------------------------------------------------------------------------
if [ "$NON_INTERACTIVE" = true ]; then
    : "${WIFI_PASS:?ERROR: WIFI_PASS must be exported before calling --non-interactive}"
    : "${SAMBA_PASS:?ERROR: SAMBA_PASS must be exported before calling --non-interactive}"
else
    read -rsp "WiFi AP Password : " WIFI_PASS;  echo
    read -rsp "Samba Password   : " SAMBA_PASS; echo
fi

# ---------------------------------------------------------------------------
# 1. System update & package installation
# ---------------------------------------------------------------------------
echo ""
echo "[1/9] Updating system packages..."
sudo apt update
sudo apt upgrade -y

echo ""
echo "[2/9] Installing required packages..."
sudo apt install -y \
    python3-pip \
    python3-pil \
    python3-pil.imagetk \
    python3-smbus \
    python3-picamera2 \
    python3-scipy \
    samba \
    samba-common-bin \
    apache2 \
    php8.2 \
    libapache2-mod-php8.2

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "[3/9] Setting up Python virtual environment..."
sudo -u "$EFINDER_USER" python3 -m venv "$VENV" --system-site-packages
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install adafruit-circuitpython-adxl34x gdown

# ---------------------------------------------------------------------------
# 3. Clone eFinder_cli
# ---------------------------------------------------------------------------
echo ""
echo "[4/9] Cloning eFinder_cli (tinySS branch)..."
REPO_URL="https://github.com/mconsidine/eFinder_cli.git"
REPO_DIR="$EFINDER_HOME/eFinder_cli"
cd "$EFINDER_HOME"
if [ ! -d "$REPO_DIR" ]; then
    sudo -u "$EFINDER_USER" git clone --branch tinySS "$REPO_URL" "$REPO_DIR"
else
    echo "  Repo already present — fetching latest tinySS..."
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" fetch origin
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" checkout tinySS
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" pull origin tinySS
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
find "$REPO_DIR/Solver" -maxdepth 1 -type f | while read -r f; do
    cp "$f" "$EFINDER_HOME/Solver/"
done
sudo chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver"

# RAM-backed tmpfs mounts — add only if not already present
grep -q "/var/tmp" /etc/fstab || \
    echo "tmpfs /var/tmp tmpfs nodev,nosuid,size=10M 0 0" | sudo tee -a /etc/fstab > /dev/null

grep -q "$EFINDER_HOME/Solver/images" /etc/fstab || \
    echo "tmpfs $EFINDER_HOME/Solver/images tmpfs nodev,nosuid,size=10M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null

# Activate mounts — warn but do not abort on failure
sudo mount -a || echo "WARNING: mount -a had errors — check /etc/fstab entries"

# ---------------------------------------------------------------------------
# 5. Install Tetra3 star-pattern matching library
# ---------------------------------------------------------------------------
echo ""
echo "[6/9] Installing Tetra3..."
if [ ! -d "$EFINDER_HOME/tetra3" ]; then
    sudo -u "$EFINDER_USER" git clone https://github.com/esa/tetra3.git "$EFINDER_HOME/tetra3"
fi
cd "$EFINDER_HOME/tetra3"
"$VENV/bin/pip" install .

TETRA3_DATA=$("$VENV/bin/python3" -c \
    "import tetra3, os; print(os.path.join(os.path.dirname(tetra3.__file__), 'data'))" \
    2>/dev/null) || TETRA3_DATA=""

if [ -z "$TETRA3_DATA" ]; then
    echo "  WARNING: Could not determine tetra3 data path — skipping database download."
else
    echo "  Tetra3 data directory: $TETRA3_DATA"
    sudo -u "$EFINDER_USER" "$VENV/bin/gdown" \
        --output "$TETRA3_DATA" \
        --folder \
        https://drive.google.com/drive/folders/1uxbdttpg0Dpp8OuYUDY9arYoeglfZzcX \
    || echo "  WARNING: gdown failed. Download Tetra3 databases manually if needed."
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

# Use $SAMBA_PASS from environment (set above from config.env or user prompt)
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | sudo smbpasswd -s -a "$EFINDER_USER"
sudo systemctl enable --now smbd

# ---------------------------------------------------------------------------
# 7. Apache / PHP web server
# ---------------------------------------------------------------------------
echo ""
echo "[8/9] Configuring Apache/PHP web server..."
sudo cp "$REPO_DIR/Solver/www/index.php"    /var/www/html/
sudo cp "$REPO_DIR/Solver/www/upload.php"   /var/www/html/
sudo cp "$REPO_DIR/Solver/www/updater.html" /var/www/html/
sudo cp "$REPO_DIR/Solver/www/user.ini"     /etc/php/8.2/apache2/conf.d/
sudo cp "$REPO_DIR/Solver/www/user.ini"     /etc/php/8.2/cli/conf.d/

[ -f /var/www/html/index.html ] && sudo mv /var/www/html/index.html /var/www/html/apacheindex.html

sudo chmod -R 755 /var/www/html
sudo systemctl enable --now apache2

# ---------------------------------------------------------------------------
# 8. Boot firmware configuration (config.txt)
# ---------------------------------------------------------------------------
echo ""
echo "[9/9] Writing /boot/firmware/config.txt..."
BOOT_CONFIG=/boot/firmware/config.txt
BACKUP=/boot/firmware/config.txt.bak
sudo cp "$BOOT_CONFIG" "$BACKUP"

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
    -e '/^# Arducam IMX477/d' \
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

echo "config.txt updated."

# ---------------------------------------------------------------------------
# 8b. cmdline.txt
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
# ---------------------------------------------------------------------------
echo ""
echo "[AP] Configuring NetworkManager WiFi hotspot..."

MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || ip link show wlan0 | awk '/ether/{print $2}')
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"

echo "  SSID     : $SSID"
echo "  Password : $WIFI_PASS"

sudo -u "$EFINDER_USER" tee "$EFINDER_HOME/Solver/default_hotspot.txt" > /dev/null <<EOF
ssid:${SSID}
password:${WIFI_PASS}
EOF

nmcli connection delete "efinder-ap" 2>/dev/null || true

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

echo "  AP profile 'efinder-ap' created."
echo "  Connect to SSID '$SSID' then SSH to 192.168.50.1"

# ---------------------------------------------------------------------------
# 10. USB gadget / tethered serial
# ---------------------------------------------------------------------------
echo ""
echo "[USB] Enabling getty on USB serial gadget interface..."
sudo systemctl enable getty@ttyGS0.service 2>/dev/null || \
    sudo systemctl enable serial-getty@ttyGS0.service 2>/dev/null || \
    echo "  Note: USB serial getty will activate after reboot."

# ---------------------------------------------------------------------------
# 11. SSH daemon
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_ssh 0
sudo systemctl enable --now ssh

# ---------------------------------------------------------------------------
# 12. Interface / peripheral setup
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_serial_cons 1

grep -q "vm.swappiness" /etc/sysctl.conf || \
    echo 'vm.swappiness = 0' | sudo tee -a /etc/sysctl.conf > /dev/null

# CPU performance governor — write all unit files before daemon-reload
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

SUDOERS_FILE=/etc/sudoers.d/efinder-date
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/date" | \
        sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    echo "  Sudoers rule written: efinder may run /bin/date without password."
fi

# ---------------------------------------------------------------------------
# 13. Deploy eFinder.py
# The script is called from the cloned repo directory, so eFinder.py lives
# in the Solver/ subdirectory relative to this script.
# ---------------------------------------------------------------------------
echo ""
echo "[13] Deploying eFinder application..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EFINDER_SRC="$SCRIPT_DIR/Solver/eFinder.py"

if [ -f "$EFINDER_SRC" ]; then
    sudo cp "$EFINDER_SRC" "$EFINDER_HOME/Solver/eFinder.py"
    sudo chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver/eFinder.py"
    sudo chmod 755 "$EFINDER_HOME/Solver/eFinder.py"
    echo "  eFinder.py deployed from $EFINDER_SRC"
else
    echo "  WARNING: $EFINDER_SRC not found — eFinder.py was not deployed."
    echo "           Copy it manually to $EFINDER_HOME/Solver/eFinder.py"
fi

# ---------------------------------------------------------------------------
# 14. Write OTA update helper script
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 15. Write all systemd unit files, then do a single daemon-reload,
#     then enable everything. This avoids stale unit cache issues.
# ---------------------------------------------------------------------------
echo ""
echo "[15] Installing systemd services..."

sudo tee /etc/systemd/system/efinder-update.service > /dev/null <<'EOF'
[Unit]
Description=eFinder OTA update checker
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
StartLimitIntervalSec=120
StartLimitBurst=4
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Single daemon-reload after all unit files are written
sudo systemctl daemon-reload

# Now enable everything in one pass
sudo systemctl enable cpu-performance.service
sudo systemctl enable efinder-update.service
sudo systemctl enable efinder.service

# Remove old cron-based autostart if present
sudo rm -f /etc/cron.d/efinder

echo "  All services installed and enabled."
echo "  View logs with: journalctl -u efinder -f"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================================="
echo " Installation complete."
echo ""
echo "   WiFi AP  : SSID='$SSID'  Password='$WIFI_PASS'"
echo "   SSH (AP) : ssh efinder@192.168.50.1"
echo "   USB      : serial console on ttyGS0 (CoolTerm / screen / minicom)"
echo "   SkySafari: connect to $SSID → TCP port 4060 (LX200)"
echo ""
echo " Camera    : IMX477 via imx477 overlay (HQ Camera or Arducam IMX477)"
echo " Samba     : \\\\<ip>\\efindershare  (user: efinder / pass: $SAMBA_PASS)"
echo " Logs      : journalctl -u efinder -f"
echo "============================================================================="
echo ""

# Write completion marker
date > "$INSTALL_MARKER"

# Disable client-mode WiFi autoconnect now that all downloads are complete.
# This profile may not exist if the Pi was not set up via Raspberry Pi Imager.
echo "Disabling autoconnect on 'preconfigured' WiFi client profile (if present)..."
nmcli connection modify "preconfigured" autoconnect no 2>/dev/null || true

# Reboot prompt — skipped in non-interactive mode (firstrun.sh handles reboot)
if [ "$NON_INTERACTIVE" = false ]; then
    read -rp "Reboot now? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        sudo reboot now
    fi
fi
