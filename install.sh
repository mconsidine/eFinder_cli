#!/bin/bash
# =============================================================================
# eFinder CLI Install Script for Raspberry Pi Zero 2W
# - IMX477 camera (RPi HQ Camera or Arducam IMX477)
# - NetworkManager-based WiFi AP (boots into AP mode by default)
# - SSH enabled on both AP and tethered USB serial modes
# - USB serial tether via g_serial (/dev/ttyUSB0 on host)
# - ap.sh / station.sh for switching between AP and client WiFi
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
# Guard: interactive mode must run as the efinder user (with sudo)
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
# Guard: hardware model check
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
# Guard: skip if already installed (interactive only)
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
# Credentials
# ---------------------------------------------------------------------------
if [ "$NON_INTERACTIVE" = true ]; then
    : "${WIFI_PASS:?ERROR: WIFI_PASS must be exported before calling --non-interactive}"
    : "${SAMBA_PASS:?ERROR: SAMBA_PASS must be exported before calling --non-interactive}"
else
    read -rsp "WiFi AP Password : " WIFI_PASS;  echo
    read -rsp "Samba Password   : " SAMBA_PASS; echo
fi

# ---------------------------------------------------------------------------
# 1. System update & packages
# ---------------------------------------------------------------------------
echo ""
echo "[1/9] Updating system packages..."
sudo apt-get update -q
sudo apt-get upgrade -y

echo ""
echo "[2/9] Installing required packages..."
sudo apt-get install -y \
    python3-pip \
    python3-pil \
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
"$VENV/bin/pip" install \
    grpcio \
    cedar-solve \
    pyserial

# ---------------------------------------------------------------------------
# 3. Clone / update eFinder_cli (tiny_img branch)
# ---------------------------------------------------------------------------
echo ""
echo "[4/9] Cloning eFinder_cli (tiny_img branch)..."
REPO_URL="https://github.com/mconsidine/eFinder_cli.git"
REPO_DIR="$EFINDER_HOME/eFinder_cli"
cd "$EFINDER_HOME"
if [ ! -d "$REPO_DIR" ]; then
    sudo -u "$EFINDER_USER" git clone --branch tiny_img "$REPO_URL" "$REPO_DIR"
else
    echo "  Repo already present — removing and recloning..."
    sudo rm -rf "$REPO_DIR"
    sudo -u "$EFINDER_USER" git clone --branch tiny_img "$REPO_URL" "$REPO_DIR"
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

# Copy support files from repo into working Solver directory
find "$REPO_DIR/Solver" -maxdepth 1 -type f | while read -r f; do
    cp "$f" "$EFINDER_HOME/Solver/"
done
sudo chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver"

# RAM-backed tmpfs mounts
# /var/tmp needs 100M — kernel upgrades fail with 10M
grep -q "/var/tmp" /etc/fstab || \
    echo "tmpfs /var/tmp tmpfs nodev,nosuid,size=100M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null

grep -q "$EFINDER_HOME/Solver/images" /etc/fstab || \
    echo "tmpfs $EFINDER_HOME/Solver/images tmpfs nodev,nosuid,size=10M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null

sudo mount -a || echo "WARNING: mount -a had errors — check /etc/fstab"

# ---------------------------------------------------------------------------
# 5. cedar-detect gRPC stubs
# ---------------------------------------------------------------------------
echo ""
echo "[6/9] Installing cedar-detect gRPC stubs..."
sudo apt-get install -y protobuf-compiler python3-pip
"$VENV/bin/pip" install grpcio-tools

PROTO_DIR="$EFINDER_HOME/cedar-detect-proto"
if [ ! -d "$PROTO_DIR" ]; then
    sudo -u "$EFINDER_USER" git clone \
        https://github.com/smroid/cedar-detect.git "$PROTO_DIR"
fi

"$VENV/bin/python3" -m grpc_tools.protoc \
    -I "$PROTO_DIR/src/proto" \
    --python_out="$EFINDER_HOME/Solver" \
    --pyi_out="$EFINDER_HOME/Solver" \
    --grpc_python_out="$EFINDER_HOME/Solver" \
    "$PROTO_DIR/src/proto/cedar_detect.proto"

sudo chown "$EFINDER_USER:$EFINDER_USER" \
    "$EFINDER_HOME/Solver/cedar_detect_pb2.py" \
    "$EFINDER_HOME/Solver/cedar_detect_pb2_grpc.py"
echo "  gRPC stubs generated."

# ---------------------------------------------------------------------------
# 6. cedar-detect-server binary
# ---------------------------------------------------------------------------
echo ""
echo "[6b] Installing cedar-detect-server binary..."
CEDAR_BIN="$REPO_DIR/Solver/databases/cedar-detect-server"
if [ -f "$CEDAR_BIN" ]; then
    sudo install -m 755 "$CEDAR_BIN" /usr/local/bin/cedar-detect-server
    echo "  cedar-detect-server installed from repo."
else
    echo "  WARNING: cedar-detect-server binary not found in repo."
    echo "           Expected: $CEDAR_BIN"
    echo "           Build it on an aarch64 machine and place it there."
fi

# ---------------------------------------------------------------------------
# 7. Star database
# ---------------------------------------------------------------------------
echo ""
echo "[6c] Generating cedar-solve star database..."
DB_PATH="$EFINDER_HOME/Solver/t3_fov14_mag8"
if [ ! -f "${DB_PATH}.npz" ]; then
    sudo -u "$EFINDER_USER" "$VENV/bin/python3" - << 'PYEOF'
import os, sys
home = '/home/efinder'
sys.path.insert(0, os.path.join(home, 'Solver'))
import tetra3
db = os.path.join(home, 'Solver', 't3_fov14_mag8')
t3 = tetra3.Tetra3(load_database=None)
t3.generate_database(
    max_fov=15, min_fov=12,
    save_as=db,
    star_catalog='hip_main',
    max_magnitude=8.0,
    pattern_stars_per_fov=10,
    catalog_stars_per_fov=20,
)
print('Database saved to', db + '.npz')
PYEOF
else
    echo "  Database already exists — skipping generation."
fi

# ---------------------------------------------------------------------------
# 7. Samba share
# ---------------------------------------------------------------------------
echo ""
echo "[7/9] Configuring Samba file share..."
if ! grep -q "\[efindershare\]" /etc/samba/smb.conf; then
    echo "" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "[efindershare]" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "path = /home/efinder" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "writeable = Yes" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "create mask = 0777" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "directory mask = 0777" | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "public = no" | sudo tee -a /etc/samba/smb.conf > /dev/null
fi
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | sudo smbpasswd -s -a "$EFINDER_USER"
sudo systemctl enable --now smbd

# ---------------------------------------------------------------------------
# 8. Apache / PHP web server
# ---------------------------------------------------------------------------
echo ""
echo "[8/9] Configuring Apache/PHP web server..."
sudo cp "$REPO_DIR/Solver/www/index.php"  /var/www/html/
sudo cp "$REPO_DIR/Solver/www/stream.php" /var/www/html/
[ -f "$REPO_DIR/Solver/www/upload.php" ] && \
    sudo cp "$REPO_DIR/Solver/www/upload.php" /var/www/html/
[ -f "$REPO_DIR/Solver/www/user.ini" ] && \
    sudo cp "$REPO_DIR/Solver/www/user.ini" /etc/php/8.2/apache2/conf.d/ && \
    sudo cp "$REPO_DIR/Solver/www/user.ini" /etc/php/8.2/cli/conf.d/

[ -f /var/www/html/index.html ] && \
    sudo mv /var/www/html/index.html /var/www/html/apacheindex.html

# Apache timeout
echo "Timeout 3600" | sudo tee /etc/apache2/conf-available/efinder.conf > /dev/null
sudo a2enconf efinder

sudo chmod -R 755 /var/www/html
sudo systemctl enable --now apache2

# ---------------------------------------------------------------------------
# 9. Boot firmware (config.txt and cmdline.txt)
# ---------------------------------------------------------------------------
echo ""
echo "[9/9] Writing /boot/firmware/config.txt..."
BOOT_CONFIG=/boot/firmware/config.txt
[ ! -f "${BOOT_CONFIG}.bak" ] && sudo cp "$BOOT_CONFIG" "${BOOT_CONFIG}.bak"

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
    -e '/^# USB gadget/d' \
    "$BOOT_CONFIG"

echo "" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "# --- eFinder additions ---" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "# IMX477 camera (RPi HQ Camera or Arducam IMX477)" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "camera_auto_detect=0" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "dtoverlay=imx477" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "# USB gadget serial (/dev/ttyUSB0 on host, /dev/ttyGS0 on Pi)" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "dtoverlay=dwc2,dr_mode=peripheral" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "enable_uart=1" | sudo tee -a "$BOOT_CONFIG" > /dev/null
echo "  config.txt updated."

CMDLINE=/boot/firmware/cmdline.txt
# Remove any stale gadget entries before adding
sudo sed -i 's/ modules-load=dwc2,g_serial//g' "$CMDLINE"
sudo sed -i 's/ modules-load=dwc2,g_cdc//g'    "$CMDLINE"
if ! grep -q "modules-load=dwc2,g_serial" "$CMDLINE"; then
    sudo sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' "$CMDLINE"
    echo "  cmdline.txt updated (g_serial)."
else
    echo "  cmdline.txt already correct."
fi

# ---------------------------------------------------------------------------
# AP configuration
# ---------------------------------------------------------------------------
echo ""
echo "[AP] Configuring NetworkManager WiFi hotspot..."

# Unblock WiFi radio — required on fresh Bookworm images
sudo rfkill unblock wifi
for f in /var/lib/systemd/rfkill/*:wlan; do
    [ -f "$f" ] && echo 0 | sudo tee "$f" > /dev/null
done

# Set WiFi country code
WIFI_COUNTRY="${WIFI_COUNTRY:-US}"
sudo raspi-config nonint do_wifi_country "$WIFI_COUNTRY" 2>/dev/null || true
echo "  WiFi country: $WIFI_COUNTRY"

MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || \
      ip link show wlan0 | awk '/ether/{print $2}')
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"
echo "  SSID     : $SSID"
echo "  Password : $WIFI_PASS"

echo "ssid:${SSID}"          > "$EFINDER_HOME/Solver/default_hotspot.txt"
echo "password:${WIFI_PASS}" >> "$EFINDER_HOME/Solver/default_hotspot.txt"
sudo chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver/default_hotspot.txt"

# Remove any existing AP profile and write a fresh one
sudo nmcli connection delete "efinder-ap" 2>/dev/null || true

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

# Remove the Pi OS default client profile so it doesn't outbid the AP
sudo nmcli connection delete "preconfigured" 2>/dev/null || true

echo "  AP profile 'efinder-ap' created (SSID: $SSID)"

# ---------------------------------------------------------------------------
# ap.sh and station.sh helper scripts
# ---------------------------------------------------------------------------
echo "[AP] Writing helper scripts..."

AP="$EFINDER_HOME/ap.sh"
echo '#!/bin/bash'                                                    > "$AP"
echo '# ap.sh — switch to Access Point (hotspot) mode'              >> "$AP"
echo '# Usage: ~/ap.sh'                                              >> "$AP"
echo 'set -e'                                                         >> "$AP"
echo 'echo "Switching to AP mode..."'                                >> "$AP"
echo 'ACTIVE=$(nmcli -t -f NAME,TYPE con show --active \' >> "$AP"
echo '    | grep wifi | grep -v efinder-ap | cut -d: -f1)'          >> "$AP"
echo 'nmcli connection down "$ACTIVE" 2>/dev/null || true'           >> "$AP"
echo 'nmcli connection up efinder-ap'                                >> "$AP"
echo 'echo "AP active. SSH: ssh efinder@192.168.50.1"'              >> "$AP"
sudo chmod +x "$AP"
sudo chown "$EFINDER_USER:$EFINDER_USER" "$AP"

ST="$EFINDER_HOME/station.sh"
echo '#!/bin/bash'                                                    > "$ST"
echo '# station.sh — connect to external WiFi (station mode)'       >> "$ST"
echo '# Usage: ~/station.sh [ssid] [password]'                      >> "$ST"
echo '# Run ~/ap.sh to return to AP mode.'                          >> "$ST"
echo 'set -e'                                                         >> "$ST"
echo 'if [ -z "$1" ]; then'                                          >> "$ST"
echo '    nmcli device wifi rescan 2>/dev/null || true; sleep 2'    >> "$ST"
echo '    echo "Available networks:"'                                >> "$ST"
echo '    nmcli -f SSID,SIGNAL,SECURITY device wifi list | head -20' >> "$ST"
echo '    read -rp "Enter SSID: " SSID'                              >> "$ST"
echo '    read -rsp "Enter password (blank=open): " PASSWORD'        >> "$ST"
echo '    echo ""'                                                    >> "$ST"
echo 'else'                                                           >> "$ST"
echo '    SSID="$1"; PASSWORD="${2:-}"'                              >> "$ST"
echo 'fi'                                                             >> "$ST"
echo '[ -z "$SSID" ] && { echo "ERROR: SSID empty"; exit 1; }'     >> "$ST"
echo 'nmcli connection down efinder-ap 2>/dev/null || true'         >> "$ST"
echo 'if [ -n "$PASSWORD" ]; then'                                   >> "$ST"
echo '    nmcli device wifi connect "$SSID" password "$PASSWORD" || {' >> "$ST"
echo '        echo "Failed — returning to AP mode"'                 >> "$ST"
echo '        nmcli connection up efinder-ap; exit 1; }'            >> "$ST"
echo 'else'                                                           >> "$ST"
echo '    nmcli device wifi connect "$SSID" || {'                   >> "$ST"
echo '        echo "Failed — returning to AP mode"'                 >> "$ST"
echo '        nmcli connection up efinder-ap; exit 1; }'            >> "$ST"
echo 'fi'                                                             >> "$ST"
echo 'echo "Waiting for IP..."; IP=""'                               >> "$ST"
echo 'for i in $(seq 1 15); do'                                      >> "$ST"
echo '    IP=$(ip -4 addr show wlan0 \' >> "$ST"
echo '        | grep -oP "(?<=inet )[\d.]+" | grep -v "192\.168\.50\.")' >> "$ST"
echo '    [ -n "$IP" ] && break; sleep 1'                            >> "$ST"
echo 'done'                                                           >> "$ST"
echo '[ -z "$IP" ] && IP=$(hostname -I | awk "{print \$1}")'        >> "$ST"
echo 'echo "Connected to: $SSID  IP: $IP"'                          >> "$ST"
echo 'echo "SSH: ssh efinder@$IP  or  ssh efinder@efinder.local"'   >> "$ST"
echo 'echo "Run ~/ap.sh to return to AP mode."'                     >> "$ST"
sudo chmod +x "$ST"
sudo chown "$EFINDER_USER:$EFINDER_USER" "$ST"

echo "  ap.sh and station.sh written."

# ---------------------------------------------------------------------------
# polkit rule so efinder user can run nmcli without sudo
# ---------------------------------------------------------------------------
sudo mkdir -p /etc/polkit-1/rules.d
POLKIT=/etc/polkit-1/rules.d/50-efinder-nm.rules
echo 'polkit.addRule(function(action, subject) {'                 | sudo tee    "$POLKIT" > /dev/null
echo '    if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 &&' | sudo tee -a "$POLKIT" > /dev/null
echo '        subject.user == "efinder") {'                       | sudo tee -a "$POLKIT" > /dev/null
echo '        return polkit.Result.YES;'                          | sudo tee -a "$POLKIT" > /dev/null
echo '    }'                                                       | sudo tee -a "$POLKIT" > /dev/null
echo '});'                                                         | sudo tee -a "$POLKIT" > /dev/null
sudo chmod 644 "$POLKIT"
echo "  polkit rule written."

# ---------------------------------------------------------------------------
# USB serial tether getty
# ---------------------------------------------------------------------------
echo "[USB] Enabling getty on USB serial gadget (ttyGS0)..."
sudo mkdir -p /etc/systemd/system/serial-getty@ttyGS0.service.d
echo "[Service]"                                       | sudo tee    /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
echo "ExecStart="                                     | sudo tee -a /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
echo "ExecStart=-/sbin/agetty -L -i 115200 ttyGS0"  | sudo tee -a /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
sudo systemctl enable serial-getty@ttyGS0.service
echo "  USB serial getty enabled (screen /dev/ttyUSB0 115200)"

# ---------------------------------------------------------------------------
# SSH — enable without raspi-config to avoid sshd_config being overwritten
# with PasswordAuthentication no (known raspi-config do_ssh bug on Bookworm)
# ---------------------------------------------------------------------------
sudo systemctl enable --now ssh
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' \
    /etc/ssh/sshd_config
sudo systemctl restart ssh
echo "  SSH enabled with password authentication."

# ---------------------------------------------------------------------------
# Interface / peripheral setup
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_i2c 0 2>/dev/null || true
sudo raspi-config nonint do_serial_cons 1 2>/dev/null || true

grep -q "vm.swappiness" /etc/sysctl.conf || \
    echo 'vm.swappiness = 0' | sudo tee -a /etc/sysctl.conf > /dev/null

# ---------------------------------------------------------------------------
# Sudoers
# ---------------------------------------------------------------------------
SUDOERS_FILE=/etc/sudoers.d/efinder
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/date"                   | sudo tee    "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /usr/bin/date"              | sudo tee -a "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart efinder"  | sudo tee -a "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart efinder" | sudo tee -a "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"
echo "  Sudoers rule written."

# ---------------------------------------------------------------------------
# OTA update helper
# ---------------------------------------------------------------------------
APPLY="$EFINDER_HOME/Solver/apply_update.sh"
echo '#!/bin/bash'                                                  | sudo tee    "$APPLY" > /dev/null
echo 'ZIPFILE="/home/efinder/uploads/efinderUpdate.zip"'           | sudo tee -a "$APPLY" > /dev/null
echo '[ ! -f "$ZIPFILE" ] && echo "No update zip." && exit 0'     | sudo tee -a "$APPLY" > /dev/null
echo 'echo "Applying update..."'                                    | sudo tee -a "$APPLY" > /dev/null
echo 'if unzip -o "$ZIPFILE" -d /; then'                          | sudo tee -a "$APPLY" > /dev/null
echo '    find / -name "*.py" -newer "$ZIPFILE" -exec chmod a+rwx {} \; 2>/dev/null || true' | sudo tee -a "$APPLY" > /dev/null
echo '    rm -f "$ZIPFILE"'                                         | sudo tee -a "$APPLY" > /dev/null
echo '    echo "Update applied -- rebooting."'                      | sudo tee -a "$APPLY" > /dev/null
echo '    systemctl reboot'                                         | sudo tee -a "$APPLY" > /dev/null
echo 'else'                                                         | sudo tee -a "$APPLY" > /dev/null
echo '    echo "Update failed -- removing zip."'                    | sudo tee -a "$APPLY" > /dev/null
echo '    rm -f "$ZIPFILE"'                                         | sudo tee -a "$APPLY" > /dev/null
echo 'fi'                                                           | sudo tee -a "$APPLY" > /dev/null
sudo chmod 755 "$APPLY"
sudo chown root:root "$APPLY"

# ---------------------------------------------------------------------------
# Systemd unit files — written with echo/tee, no heredocs
# ---------------------------------------------------------------------------
echo ""
echo "[SVC] Installing systemd services..."

CPU_SVC=/etc/systemd/system/cpu-performance.service
echo "[Unit]"                                                        | sudo tee    "$CPU_SVC" > /dev/null
echo "Description=Set CPU governor to performance mode"             | sudo tee -a "$CPU_SVC" > /dev/null
echo "After=sysinit.target"                                         | sudo tee -a "$CPU_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CPU_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$CPU_SVC" > /dev/null
echo "Type=oneshot"                                                  | sudo tee -a "$CPU_SVC" > /dev/null
echo "RemainAfterExit=yes"                                          | sudo tee -a "$CPU_SVC" > /dev/null
echo "ExecStart=/bin/sh -c 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'" | sudo tee -a "$CPU_SVC" > /dev/null
echo "StandardOutput=journal"                                        | sudo tee -a "$CPU_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CPU_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$CPU_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$CPU_SVC" > /dev/null

UPD_SVC=/etc/systemd/system/efinder-update.service
echo "[Unit]"                                                        | sudo tee    "$UPD_SVC" > /dev/null
echo "Description=eFinder OTA update checker"                       | sudo tee -a "$UPD_SVC" > /dev/null
echo "Before=efinder.service"                                       | sudo tee -a "$UPD_SVC" > /dev/null
echo "After=local-fs.target"                                        | sudo tee -a "$UPD_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$UPD_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$UPD_SVC" > /dev/null
echo "Type=oneshot"                                                  | sudo tee -a "$UPD_SVC" > /dev/null
echo "RemainAfterExit=yes"                                          | sudo tee -a "$UPD_SVC" > /dev/null
echo "User=root"                                                     | sudo tee -a "$UPD_SVC" > /dev/null
echo "WorkingDirectory=/home/efinder"                               | sudo tee -a "$UPD_SVC" > /dev/null
echo "ExecStart=/bin/bash /home/efinder/Solver/apply_update.sh"    | sudo tee -a "$UPD_SVC" > /dev/null
echo "StandardOutput=journal"                                        | sudo tee -a "$UPD_SVC" > /dev/null
echo "StandardError=journal"                                         | sudo tee -a "$UPD_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$UPD_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$UPD_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$UPD_SVC" > /dev/null

CD_SVC=/etc/systemd/system/cedar-detect.service
echo "[Unit]"                                                        | sudo tee    "$CD_SVC" > /dev/null
echo "Description=Cedar-detect star detection gRPC server"         | sudo tee -a "$CD_SVC" > /dev/null
echo "After=local-fs.target"                                        | sudo tee -a "$CD_SVC" > /dev/null
echo "Before=efinder.service"                                       | sudo tee -a "$CD_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CD_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$CD_SVC" > /dev/null
echo "Type=simple"                                                   | sudo tee -a "$CD_SVC" > /dev/null
echo "User=efinder"                                                  | sudo tee -a "$CD_SVC" > /dev/null
echo "ExecStart=/usr/local/bin/cedar-detect-server --port 50051"   | sudo tee -a "$CD_SVC" > /dev/null
echo "Restart=on-failure"                                            | sudo tee -a "$CD_SVC" > /dev/null
echo "RestartSec=5"                                                  | sudo tee -a "$CD_SVC" > /dev/null
echo "StandardOutput=journal"                                        | sudo tee -a "$CD_SVC" > /dev/null
echo "StandardError=journal"                                         | sudo tee -a "$CD_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CD_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$CD_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$CD_SVC" > /dev/null

EF_SVC=/etc/systemd/system/efinder.service
echo "[Unit]"                                                        | sudo tee    "$EF_SVC" > /dev/null
echo "Description=eFinder telescope plate solver"                   | sudo tee -a "$EF_SVC" > /dev/null
echo "After=cedar-detect.service efinder-update.service"           | sudo tee -a "$EF_SVC" > /dev/null
echo "Wants=cedar-detect.service"                                   | sudo tee -a "$EF_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$EF_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$EF_SVC" > /dev/null
echo "Type=simple"                                                   | sudo tee -a "$EF_SVC" > /dev/null
echo "User=efinder"                                                  | sudo tee -a "$EF_SVC" > /dev/null
echo "WorkingDirectory=/home/efinder/Solver"                        | sudo tee -a "$EF_SVC" > /dev/null
echo "Environment=PATH=/home/efinder/venv-efinder/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" | sudo tee -a "$EF_SVC" > /dev/null
echo "ExecStartPre=/bin/sleep 2"                                    | sudo tee -a "$EF_SVC" > /dev/null
echo "ExecStart=/home/efinder/venv-efinder/bin/python /home/efinder/Solver/eFinder.py" | sudo tee -a "$EF_SVC" > /dev/null
echo "Restart=on-failure"                                            | sudo tee -a "$EF_SVC" > /dev/null
echo "RestartSec=15"                                                 | sudo tee -a "$EF_SVC" > /dev/null
echo "StartLimitIntervalSec=120"                                    | sudo tee -a "$EF_SVC" > /dev/null
echo "StartLimitBurst=4"                                             | sudo tee -a "$EF_SVC" > /dev/null
echo "StandardOutput=journal"                                        | sudo tee -a "$EF_SVC" > /dev/null
echo "StandardError=journal"                                         | sudo tee -a "$EF_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$EF_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$EF_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$EF_SVC" > /dev/null

# Single daemon-reload then enable everything
sudo systemctl daemon-reload
sudo systemctl enable cpu-performance.service
sudo systemctl enable efinder-update.service
sudo systemctl enable cedar-detect.service
sudo systemctl enable efinder.service

# Disable client WiFi autoconnect now that all downloads are complete
sudo nmcli connection modify "preconfigured" autoconnect no 2>/dev/null || true

sudo rm -f /etc/cron.d/efinder

echo "  All services installed and enabled."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================================="
echo " Installation complete."
echo ""
echo "   WiFi AP  : SSID='$SSID'  Password='$WIFI_PASS'  IP=192.168.50.1"
echo "   SSH      : ssh efinder@192.168.50.1"
echo "   Tether   : screen /dev/ttyUSB0 115200"
echo "   SkySafari: connect to $SSID -> TCP port 4060 (LX200)"
echo "   Samba    : efindershare  user=efinder  pass=$SAMBA_PASS"
echo "   Logs     : journalctl -u efinder -f"
echo "   Helpers  : ~/ap.sh   ~/station.sh"
echo "============================================================================="

date > "$INSTALL_MARKER"

if [ "$NON_INTERACTIVE" = false ]; then
    read -rp "Reboot now? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] && sudo reboot now
fi
