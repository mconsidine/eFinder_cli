#!/bin/bash
# =============================================================================
# eFinder tetra3rs Install Script for Raspberry Pi Zero 2W
# Replaces cedar-detect + cedar-solve with tetra3rs (Rust, PyPI wheel).
# No gRPC, no cross-compilation, no proto stubs needed.
#
# Usage:
#   Interactive : sudo bash install-tetra3rs.sh
#   Automated   : bash install-tetra3rs.sh --non-interactive
#                 (WIFI_PASS and SAMBA_PASS must be exported by caller)
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
VENV="$EFINDER_HOME/venv-efinder"
INSTALL_MARKER="$EFINDER_HOME/.efinder_installed"
NON_INTERACTIVE=false
[[ "$1" == "--non-interactive" ]] && NON_INTERACTIVE=true

# ---------------------------------------------------------------------------
# Guard: must run as efinder user (with sudo)
# ---------------------------------------------------------------------------
if [ "$NON_INTERACTIVE" = false ]; then
    RUNNING_AS="${SUDO_USER:-$(logname 2>/dev/null)}"
    if [ "$RUNNING_AS" != "$EFINDER_USER" ]; then
        echo "ERROR: Run as '$EFINDER_USER': sudo bash install-tetra3rs.sh"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Guard: hardware model
# ---------------------------------------------------------------------------
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
if [[ "$PI_MODEL" != *"Zero 2"* ]]; then
    echo "WARNING: Designed for Raspberry Pi Zero 2W. Detected: $PI_MODEL"
    if [ "$NON_INTERACTIVE" = false ]; then
        read -rp "Continue anyway? [y/N] " confirm
        [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Guard: re-run check
# ---------------------------------------------------------------------------
if [ -f "$INSTALL_MARKER" ] && [ "$NON_INTERACTIVE" = false ]; then
    echo "NOTE: Previously installed. Re-run full install?"
    read -rp "[y/N] " rerun
    [[ "$rerun" =~ ^[Yy]$ ]] || exit 0
fi

echo "============================================================================="
echo " eFinder tetra3rs Installer"
echo " Device : $PI_MODEL"
echo " Mode   : $( [ "$NON_INTERACTIVE" = true ] && echo non-interactive || echo interactive )"
echo "============================================================================="

# Validate sudo and keep alive for duration of install
sudo -v
while true; do sudo -n true; sleep 50; kill -0 "$$" || exit; done 2>/dev/null &
SUDO_KEEPALIVE_PID=$!
trap 'kill $SUDO_KEEPALIVE_PID 2>/dev/null' EXIT

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
if [ "$NON_INTERACTIVE" = true ]; then
    : "${WIFI_PASS:?ERROR: WIFI_PASS must be exported}"
    : "${SAMBA_PASS:?ERROR: SAMBA_PASS must be exported}"
else
    read -rsp "WiFi AP Password [12345678]: " WIFI_PASS;  echo
    WIFI_PASS="${WIFI_PASS:-12345678}"
    read -rsp "Samba Password   [12345678]: " SAMBA_PASS; echo
    SAMBA_PASS="${SAMBA_PASS:-12345678}"
fi

# ---------------------------------------------------------------------------
# 1. System update & packages
# ---------------------------------------------------------------------------
echo ""
echo "[0/8] Waiting for NTP clock sync..."
sudo systemctl restart systemd-timesyncd
for i in $(seq 1 12); do
    if timedatectl status 2>/dev/null | grep -q "System clock synchronized: yes"; then
        echo "  Clock synced."; break
    fi
    echo "  Waiting... ($i/12)"; sleep 5
done

echo ""
echo "[1/8] Updating system packages..."
sudo apt-get update -q
sudo apt-get upgrade -y

echo ""
echo "[2/8] Installing required packages..."
sudo apt-get install -y \
    git \
    python3-pip \
    python3-numpy \
    python3-pillow \
    python3-smbus \
    python3-picamera2 --no-install-recommends \
    python3-scipy \
    libopenblas-dev \
    samba \
    samba-common-bin \
    apache2 \
    php \
    libapache2-mod-php

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "[3/8] Setting up Python virtual environment..."
sudo -u "$EFINDER_USER" python3 -m venv "$VENV" --system-site-packages
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install --prefer-binary "Pillow>=9.0"
"$VENV/bin/pip" install --prefer-binary \
    pyserial \
    adafruit-circuitpython-adxl34x \
    gaia-catalog

# Install tetra3rs — pre-built ARM64 wheel staged by CI, or fall back to PyPI.
TETRA3RS_SRC="$EFINDER_HOME/tetra3rs-src"
TETRA3RS_WHEEL=$(ls "$TETRA3RS_SRC"/*.whl 2>/dev/null | head -1)
if [ -n "$TETRA3RS_WHEEL" ]; then
    echo "  Installing tetra3rs from staged wheel: $TETRA3RS_WHEEL"
    "$VENV/bin/pip" install "$TETRA3RS_WHEEL"
    echo "  tetra3rs installed from staged wheel."
else
    echo "  Installing tetra3rs from PyPI (pre-built ARM64 wheel)..."
    "$VENV/bin/pip" install --prefer-binary tetra3rs
    echo "  tetra3rs installed from PyPI."
fi
echo "  All Python packages installed."

# ---------------------------------------------------------------------------
# 3. Clone eFinder_cli (tetra3rs branch)
# ---------------------------------------------------------------------------
echo ""
echo "[4/8] Cloning eFinder_cli (tetra3rs branch)..."
REPO_URL="https://github.com/mconsidine/eFinder_cli.git"
REPO_DIR="$EFINDER_HOME/eFinder_cli"
cd "$EFINDER_HOME"
if [ ! -d "$REPO_DIR" ]; then
    sudo -u "$EFINDER_USER" git clone --depth 1 --branch tetra3rs "$REPO_URL" "$REPO_DIR"
else
    echo "  Repo already present — removing and recloning..."
    sudo rm -rf "$REPO_DIR"
    sudo -u "$EFINDER_USER" git clone --depth 1 --branch tetra3rs "$REPO_URL" "$REPO_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Directory structure and file deployment
# ---------------------------------------------------------------------------
echo ""
echo "[5/8] Setting up directory structure..."
mkdir -p "$EFINDER_HOME/Solver/images"
mkdir -p "$EFINDER_HOME/uploads"
sudo chmod a+rwx "$EFINDER_HOME/uploads"
sudo chmod a+rwx "$EFINDER_HOME/Solver/images"
sudo chmod a+rwx "$EFINDER_HOME"

find "$REPO_DIR/Solver" -maxdepth 1 -type f | while read -r f; do
    cp "$f" "$EFINDER_HOME/Solver/"
done
sudo chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver"

# RAM-backed tmpfs
grep -q "/var/tmp" /etc/fstab || \
    echo "tmpfs /var/tmp tmpfs nodev,nosuid,size=100M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null
grep -q "$EFINDER_HOME/Solver/images" /etc/fstab || \
    echo "tmpfs $EFINDER_HOME/Solver/images tmpfs nodev,nosuid,size=10M 0 0" | \
    sudo tee -a /etc/fstab > /dev/null
sudo mount -a || echo "WARNING: mount -a had errors"

# ---------------------------------------------------------------------------
# 5. Star database generation
#
# tetra3rs uses Gaia DR3 + Hipparcos catalog (bundled in gaia-catalog package).
# No manual download needed — generate_from_gaia() uses the bundled catalog.
# Database saved as .bin (rkyv format, zero-copy load).
# Fixed filename: efinder-tetra-database.bin
# Cache filename encodes parameters for reference.
# ---------------------------------------------------------------------------
echo ""
echo "[6/8] Generating tetra3rs star database..."
DB_MAX_FOV=11
DB_MAG=8
DB_CACHE="$EFINDER_HOME/Solver/t3rs_fov${DB_MAX_FOV}_mag${DB_MAG}.bin"
DB_FIXED="$EFINDER_HOME/Solver/efinder-tetra-database.bin"

if [ ! -f "$DB_CACHE" ]; then
    echo "  Building database (max_fov=$DB_MAX_FOV, star_max_magnitude=$DB_MAG)..."
    echo "  Uses bundled Gaia DR3 + Hipparcos catalog — no download needed."
    echo "  This will take several minutes on Pi Zero 2W..."
    GEN_SCRIPT="/tmp/gen_database_tetra3rs.py"
    echo "import tetra3rs"                                                  > "$GEN_SCRIPT"
    echo "db = tetra3rs.SolverDatabase.generate_from_gaia("               >> "$GEN_SCRIPT"
    echo "    max_fov_deg=${DB_MAX_FOV},"                                  >> "$GEN_SCRIPT"
    echo "    star_max_magnitude=${DB_MAG}.0,"                             >> "$GEN_SCRIPT"
    echo "    epoch_proper_motion_year=2025.0,"                            >> "$GEN_SCRIPT"
    echo ")"                                                               >> "$GEN_SCRIPT"
    echo "db.save_to_file('${DB_CACHE}')"                                  >> "$GEN_SCRIPT"
    echo "print('Database saved: stars=%d patterns=%d' % (db.num_stars, db.num_patterns))" >> "$GEN_SCRIPT"
    sudo -u "$EFINDER_USER" "$VENV/bin/python3" "$GEN_SCRIPT"
    rm -f "$GEN_SCRIPT"
    echo "  Database generation complete."
else
    echo "  Cache $DB_CACHE already exists -- skipping generation."
fi

echo "  Copying to fixed load name: efinder-tetra-database.bin"
sudo -u "$EFINDER_USER" cp "$DB_CACHE" "$DB_FIXED"
echo "  Database ready."

# ---------------------------------------------------------------------------
# 6. Samba share
# ---------------------------------------------------------------------------
echo ""
echo "[7/8] Configuring Samba file share..."
if ! grep -q "\[efindershare\]" /etc/samba/smb.conf; then
    echo ""                              | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "[efindershare]"               | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "path = /home/efinder"         | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "writeable = Yes"              | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "create mask = 0777"           | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "directory mask = 0777"        | sudo tee -a /etc/samba/smb.conf > /dev/null
    echo "public = no"                  | sudo tee -a /etc/samba/smb.conf > /dev/null
fi
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | sudo smbpasswd -s -a "$EFINDER_USER"
sudo systemctl enable smbd nmbd
sudo systemctl restart smbd nmbd
echo "  Samba configured."

# ---------------------------------------------------------------------------
# WiFi AP SSID derived from MAC
# ---------------------------------------------------------------------------
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "00:00:00:00:00:00")
LAST4=$(echo "$MAC" | tr -d ":" | tail -c 5)
SSID="efinder${LAST4}"

# ---------------------------------------------------------------------------
# Apache / web interface
# ---------------------------------------------------------------------------
echo ""
echo "Configuring Apache web interface..."
sudo mkdir -p /var/www/html
sudo cp -r "$REPO_DIR/Solver/www/"* /var/www/html/ 2>/dev/null || true
sudo chown -R www-data:www-data /var/www/html
sudo systemctl enable apache2
sudo systemctl restart apache2

# ---------------------------------------------------------------------------
# NetworkManager AP profile
# ---------------------------------------------------------------------------
echo "Configuring WiFi AP..."
sudo nmcli connection delete "efinder-ap" 2>/dev/null || true
sudo nmcli connection add \
    type wifi ifname wlan0 con-name "efinder-ap" \
    autoconnect yes ssid "$SSID" -- \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$WIFI_PASS" \
    wifi.mode ap wifi.band bg wifi.channel 6 \
    ipv4.method shared ipv4.addresses "192.168.50.1/24" \
    ipv6.method disabled connection.autoconnect-priority 100
sudo nmcli connection delete "preconfigured" 2>/dev/null || true
echo "  AP profile created (SSID: $SSID)"

# ---------------------------------------------------------------------------
# Helper scripts
# ---------------------------------------------------------------------------
echo "Writing helper scripts..."

AP="$EFINDER_HOME/ap.sh"
echo '#!/bin/bash'                                                    > "$AP"
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
echo 'set -e'                                                         >> "$ST"
echo 'if [ -z "$1" ]; then'                                          >> "$ST"
echo '    nmcli device wifi rescan 2>/dev/null || true; sleep 2'    >> "$ST"
echo '    echo "Available networks:"'                                >> "$ST"
echo '    nmcli -f SSID,SIGNAL,SECURITY device wifi list | head -20' >> "$ST"
echo '    read -rp "Enter SSID: " SSID'                              >> "$ST"
echo '    read -rsp "Enter password: " PASSWORD; echo ""'            >> "$ST"
echo 'else'                                                           >> "$ST"
echo '    SSID="$1"; PASSWORD="${2:-}"'                              >> "$ST"
echo 'fi'                                                             >> "$ST"
echo 'nmcli connection down efinder-ap 2>/dev/null || true'         >> "$ST"
echo 'if [ -n "$PASSWORD" ]; then'                                   >> "$ST"
echo '    nmcli device wifi connect "$SSID" password "$PASSWORD" || { nmcli connection up efinder-ap; exit 1; }' >> "$ST"
echo 'else'                                                           >> "$ST"
echo '    nmcli device wifi connect "$SSID" || { nmcli connection up efinder-ap; exit 1; }' >> "$ST"
echo 'fi'                                                             >> "$ST"
echo 'echo "Connected. Run ~/ap.sh to return to AP mode."'          >> "$ST"
sudo chmod +x "$ST"
sudo chown "$EFINDER_USER:$EFINDER_USER" "$ST"

# ---------------------------------------------------------------------------
# polkit rule for nmcli
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

# ---------------------------------------------------------------------------
# Interface / peripheral setup — BEFORE SSH restart (raspi-config footgun)
# ---------------------------------------------------------------------------
sudo raspi-config nonint do_i2c 0 2>/dev/null || true
sudo raspi-config nonint do_serial_cons 1 2>/dev/null || true

grep -q "vm.swappiness" /etc/sysctl.conf || \
    echo 'vm.swappiness = 0' | sudo tee -a /etc/sysctl.conf > /dev/null

# ---------------------------------------------------------------------------
# SSH — AFTER raspi-config to prevent PasswordAuthentication being reset
# ---------------------------------------------------------------------------
sudo systemctl enable --now ssh
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' \
    /etc/ssh/sshd_config
sudo systemctl restart ssh
echo "  SSH enabled."

# ---------------------------------------------------------------------------
# USB serial tether getty
# ---------------------------------------------------------------------------
sudo mkdir -p /etc/systemd/system/serial-getty@ttyGS0.service.d
echo "[Service]"                                       | sudo tee    /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
echo "ExecStart="                                     | sudo tee -a /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
echo "ExecStart=-/sbin/agetty -L -i 115200 ttyGS0"  | sudo tee -a /etc/systemd/system/serial-getty@ttyGS0.service.d/override.conf > /dev/null
sudo systemctl enable serial-getty@ttyGS0.service

# ---------------------------------------------------------------------------
# Sudoers
# ---------------------------------------------------------------------------
SUDOERS_FILE=/etc/sudoers.d/efinder
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/date"                   | sudo tee    "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /usr/bin/date"              | sudo tee -a "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart efinder"  | sudo tee -a "$SUDOERS_FILE" > /dev/null
echo "$EFINDER_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart efinder" | sudo tee -a "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"

# ---------------------------------------------------------------------------
# 8. Systemd services
# ---------------------------------------------------------------------------
echo ""
echo "[8/8] Installing systemd services..."

CPU_SVC=/etc/systemd/system/cpu-performance.service
echo "[Unit]"                                                        | sudo tee    "$CPU_SVC" > /dev/null
echo "Description=Set CPU governor to performance mode"             | sudo tee -a "$CPU_SVC" > /dev/null
echo "After=sysinit.target"                                         | sudo tee -a "$CPU_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CPU_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$CPU_SVC" > /dev/null
echo "Type=oneshot"                                                  | sudo tee -a "$CPU_SVC" > /dev/null
echo "RemainAfterExit=yes"                                          | sudo tee -a "$CPU_SVC" > /dev/null
echo "ExecStart=/bin/sh -c 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'" | sudo tee -a "$CPU_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$CPU_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$CPU_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$CPU_SVC" > /dev/null

EF_SVC=/etc/systemd/system/efinder.service
echo "[Unit]"                                                        | sudo tee    "$EF_SVC" > /dev/null
echo "Description=eFinder tetra3rs plate solver"                    | sudo tee -a "$EF_SVC" > /dev/null
echo "After=local-fs.target network.target"                         | sudo tee -a "$EF_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$EF_SVC" > /dev/null
echo "[Service]"                                                     | sudo tee -a "$EF_SVC" > /dev/null
echo "Type=simple"                                                   | sudo tee -a "$EF_SVC" > /dev/null
echo "User=efinder"                                                  | sudo tee -a "$EF_SVC" > /dev/null
echo "WorkingDirectory=/home/efinder/Solver"                        | sudo tee -a "$EF_SVC" > /dev/null
echo "Environment=PATH=/home/efinder/venv-efinder/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" | sudo tee -a "$EF_SVC" > /dev/null
echo "ExecStartPre=/bin/sleep 2"                                    | sudo tee -a "$EF_SVC" > /dev/null
echo "ExecStart=/home/efinder/venv-efinder/bin/python /home/efinder/Solver/eFinder-tetra3rs.py" | sudo tee -a "$EF_SVC" > /dev/null
echo "Restart=on-failure"                                            | sudo tee -a "$EF_SVC" > /dev/null
echo "RestartSec=15"                                                 | sudo tee -a "$EF_SVC" > /dev/null
echo "StartLimitIntervalSec=120"                                    | sudo tee -a "$EF_SVC" > /dev/null
echo "StartLimitBurst=4"                                             | sudo tee -a "$EF_SVC" > /dev/null
echo "StandardOutput=journal"                                        | sudo tee -a "$EF_SVC" > /dev/null
echo "StandardError=journal"                                         | sudo tee -a "$EF_SVC" > /dev/null
echo ""                                                              | sudo tee -a "$EF_SVC" > /dev/null
echo "[Install]"                                                     | sudo tee -a "$EF_SVC" > /dev/null
echo "WantedBy=multi-user.target"                                   | sudo tee -a "$EF_SVC" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable cpu-performance.service
sudo systemctl enable efinder.service
echo "  Services installed and enabled."

# ---------------------------------------------------------------------------
# Slim
# ---------------------------------------------------------------------------
echo ""
echo "[slim] Cleaning up..."
sudo apt-get autoremove -y
sudo apt-get clean
sudo rm -rf /usr/share/doc/* /usr/share/man/*
echo "  Done."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "00:00:00:00:00:00")
LAST4=$(echo "$MAC" | tr -d ":" | tail -c 5)
SSID="efinder${LAST4}"

echo ""
echo "============================================================================="
echo " Installation complete."
echo ""
echo "   WiFi AP  : SSID='$SSID'  Password='$WIFI_PASS'  IP=192.168.50.1"
echo "   SSH      : ssh efinder@192.168.50.1"
echo "   SkySafari: connect to $SSID -> TCP port 4060 (LX200)"
echo "   Samba    : efindershare  user=efinder  pass=$SAMBA_PASS"
echo "   Logs     : journalctl -u efinder -f"
echo "   Helpers  : ~/ap.sh   ~/station.sh   ~/sendcmd.sh"
echo "============================================================================="

date > "$INSTALL_MARKER"

if [ "$NON_INTERACTIVE" = false ]; then
    read -rp "Reboot now? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] && sudo reboot now
fi
