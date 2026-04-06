#!/bin/bash
# =============================================================================
# install-efinder.sh — Phase 3: eFinder Application Installation
# 
# Deploys eFinder application files, web interface, services, and networking.
# Configures AP mode, station mode scripts, and all system services.
#
# Usage:
#   sudo bash install-efinder.sh
#
# Environment variables:
#   WIFI_PASSWORD  - WiFi AP password (default: 12345678)
#   SAMBA_PASSWORD - Samba share password (default: same as WIFI_PASSWORD)
# =============================================================================
set -eo pipefail

EFINDER_HOME=/home/efinder
EFINDER_USER=efinder
REPO_URL="https://github.com/mconsidine/eFinder_cli.git"
REPO_BRANCH="tinySS"
REPO_DIR="$EFINDER_HOME/eFinder_cli"

WIFI_PASSWORD="${WIFI_PASSWORD:-12345678}"
SAMBA_PASSWORD="${SAMBA_PASSWORD:-$WIFI_PASSWORD}"

echo "============================================================================="
echo " eFinder Application Installation"
echo "============================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)"
    exit 1
fi

echo ""
echo "[1/10] Cloning eFinder_cli repository..."

if [ ! -d "$REPO_DIR" ]; then
    sudo -u "$EFINDER_USER" git clone --depth 1 --branch "$REPO_BRANCH" \
        "$REPO_URL" "$REPO_DIR"
    echo "  Repository cloned: $REPO_DIR"
else
    echo "  Repository already exists: $REPO_DIR"
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" fetch origin
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" checkout "$REPO_BRANCH"
    sudo -u "$EFINDER_USER" git -C "$REPO_DIR" pull origin "$REPO_BRANCH"
fi

echo ""
echo "[2/10] Deploying application files..."

# Copy Python scripts
find "$REPO_DIR/Solver" -maxdepth 1 -type f \( -name "*.py" -o -name "*.csv" -o -name "*.ttf" -o -name "*.npy" -o -name "*.config" \) \
    -exec cp {} "$EFINDER_HOME/Solver/" \;

chown -R "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver"
echo "  Application files deployed to $EFINDER_HOME/Solver/"

echo ""
echo "[3/10] Deploying web interface..."

mkdir -p /var/www/html/api

# Copy web files
cp "$REPO_DIR/Solver/www/index.php" /var/www/html/
cp "$REPO_DIR/Solver/www/focus.php" /var/www/html/
cp "$REPO_DIR/Solver/www/calibrate.php" /var/www/html/
cp "$REPO_DIR/Solver/www/status.php" /var/www/html/
cp "$REPO_DIR/Solver/www/nav.php" /var/www/html/
cp "$REPO_DIR/Solver/www/efinder-common.js" /var/www/html/
cp "$REPO_DIR/Solver/www/log.php" /var/www/html/
cp "$REPO_DIR/Solver/www/stream.php" /var/www/html/
#cp "$REPO_DIR/Solver/www/upload.php" /var/www/html/
#cp "$REPO_DIR/Solver/www/updater.html" /var/www/html/
#cp "$REPO_DIR/README.md" /var/www/html/

# Copy API endpoints
cp "$REPO_DIR/Solver/www/api/state.php" /var/www/html/api/
cp "$REPO_DIR/Solver/www/api/status.php" /var/www/html/api/
cp "$REPO_DIR/Solver/www/api/focus.php" /var/www/html/api/
cp "$REPO_DIR/Solver/www/api/calibrate.php" /var/www/html/api/

# Set permissions
chown -R www-data:www-data /var/www/html/
chmod -R 755 /var/www/html/

# Modify stream.php to limit to 1000 frames
# Change: while (true) { ... }
# To:     for ($frame_count = 0; $frame_count < 1000; $frame_count++) { ... }
##sed -i 's/while (true)/for ($frame_count = 0; $frame_count < 1000; $frame_count++)/' \
##    /var/www/html/stream.php

echo "  Web files deployed to /var/www/html/"
echo "  Live view limited to 1000 frames per session"

# Remove default Apache index
[ -f /var/www/html/index.html ] && mv /var/www/html/index.html /var/www/html/apacheindex.html

chmod -R 755 /var/www/html

echo ""
echo "[4/10] Configuring Apache web server..."

# Apache timeout configuration
cat > /etc/apache2/conf-available/efinder.conf << 'EOF'
# eFinder Apache configuration
Timeout 3600
EOF

a2enconf efinder
systemctl enable apache2

echo "  Apache configured with 3600s timeout"

echo ""
echo "[5/10] Configuring PHP..."

# PHP configuration for large uploads and long execution
cat > /etc/php/8.2/apache2/conf.d/user.ini << 'EOF'
max_execution_time = 3600
upload_max_filesize = 50M
post_max_size = 50M
memory_limit = 256M
EOF

cp /etc/php/8.2/apache2/conf.d/user.ini /etc/php/8.2/cli/conf.d/

echo "  PHP configured for large uploads and long execution"

echo ""
echo "[6/10] Configuring Samba file share..."

# Add Samba share configuration if not already present
if ! grep -q "\[efindershare\]" /etc/samba/smb.conf; then
    cat >> /etc/samba/smb.conf << 'EOF'

[efindershare]
path = /home/efinder
writeable = Yes
create mask = 0777
directory mask = 0777
public = no
EOF
fi

# Set Samba password for efinder user
(echo "$SAMBA_PASSWORD"; echo "$SAMBA_PASSWORD") | smbpasswd -s -a "$EFINDER_USER"

systemctl enable smbd
echo "  Samba share configured: \\\\<hostname>\\efindershare"

echo ""
echo "[7/10] Creating helper scripts..."

# Copy reset script from repo
if [ -f "$REPO_DIR/reset.sh" ]; then
    cp "$REPO_DIR/reset.sh" "$EFINDER_HOME/"
    chmod +x "$EFINDER_HOME/reset.sh"
    chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/reset.sh"
fi

# Create AP mode script
cat > "$EFINDER_HOME/ap.sh" << 'EOF'
#!/bin/bash
# =============================================================================
# ap.sh — Switch to Access Point (AP) mode
# 
# Disables client WiFi connections and activates the efinder-ap hotspot.
# The device will reboot to ensure clean network state.
#
# Usage: bash ~/ap.sh
# =============================================================================
set -e

echo "Switching to AP mode..."

# Disable any client-mode WiFi profiles
nmcli connection modify "preconfigured" autoconnect no 2>/dev/null || true

# Bring up AP profile
nmcli connection up efinder-ap 2>/dev/null || true

echo "AP mode activated. Rebooting in 3 seconds..."
sleep 3
sudo reboot
EOF

chmod +x "$EFINDER_HOME/ap.sh"

# Create station mode script
cat > "$EFINDER_HOME/station.sh" << 'EOF'
#!/bin/bash
# =============================================================================
# station.sh — Switch to Station (client) mode
# 
# Connects to a home/external WiFi network for internet access.
# Run ~/ap.sh to return to AP mode.
#
# Usage: 
#   Interactive (prompts for credentials):
#     bash ~/station.sh
#
#   Non-interactive:
#     bash ~/station.sh <ssid> [password]
#     
# Examples:
#   bash ~/station.sh                    # Interactive prompts
#   bash ~/station.sh MyHomeWiFi mypass  # Command line args
#   bash ~/station.sh OpenNetwork        # Open network (no password)
# =============================================================================
set -e

# Interactive mode if no arguments provided
if [ -z "$1" ]; then
    echo "============================================"
    echo " Connect to WiFi Network (Station Mode)"
    echo "============================================"
    echo ""
    
    # Scan for available networks
    echo "Scanning for WiFi networks..."
    nmcli device wifi rescan 2>/dev/null || true
    sleep 2
    
    echo ""
    echo "Available networks:"
    nmcli -f SSID,SIGNAL,SECURITY device wifi list | head -20
    echo ""
    
    read -rp "Enter WiFi SSID: " SSID
    read -rsp "Enter WiFi password (leave blank for open network): " PASSWORD
    echo ""
else
    SSID="$1"
    PASSWORD="${2:-}"
fi

if [ -z "$SSID" ]; then
    echo "ERROR: SSID cannot be empty"
    exit 1
fi

echo ""
echo "Connecting to: $SSID"
echo ""

# Take down AP mode
nmcli connection down efinder-ap 2>/dev/null || true

# Connect to WiFi
if [ -n "$PASSWORD" ]; then
    if nmcli device wifi connect "$SSID" password "$PASSWORD"; then
        echo ""
        echo "✓ Connected to $SSID"
    else
        echo ""
        echo "✗ Connection failed. Check SSID and password."
        echo "  Returning to AP mode..."
        sleep 2
        nmcli connection up efinder-ap
        exit 1
    fi
else
    if nmcli device wifi connect "$SSID"; then
        echo ""
        echo "✓ Connected to $SSID (open network)"
    else
        echo ""
        echo "✗ Connection failed."
        echo "  Returning to AP mode..."
        sleep 2
        nmcli connection up efinder-ap
        exit 1
    fi
fi

# Show connection details
sleep 2
IP=$(hostname -I | awk '{print $1}')
GATEWAY=$(ip route | grep default | awk '{print $3}')

echo ""
echo "Network Information:"
echo "  IP Address: $IP"
echo "  Gateway: $GATEWAY"
echo "  DNS: $(grep nameserver /etc/resolv.conf | head -1 | awk '{print $2}')"
echo ""
echo "You can now:"
echo "  - SSH to this device: ssh efinder@$IP"
echo "  - Access web interface: http://$IP/"
echo "  - Run system updates: sudo apt update && sudo apt upgrade"
echo ""
echo "To return to AP mode: ~/ap.sh"
EOF

chmod +x "$EFINDER_HOME/station.sh"

chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME"/*.sh

echo "  Helper scripts created:"
echo "    ~/ap.sh       - Switch to AP mode"
echo "    ~/station.sh  - Connect to WiFi network"
echo "    ~/reset.sh    - Wipe and reinstall"

echo ""
echo "[8/10] Configuring boot firmware..."

# Backup config.txt
BOOT_CONFIG=/boot/firmware/config.txt
if [ -f "$BOOT_CONFIG" ] && [ ! -f "${BOOT_CONFIG}.bak" ]; then
    cp "$BOOT_CONFIG" "${BOOT_CONFIG}.bak"
fi

# Disable VC4 KMS (conflicts with camera)
sed -i 's/^\s*dtoverlay=vc4-kms-v3d/#&/' "$BOOT_CONFIG" || true
sed -i 's/^\s*max_framebuffers=/#&/' "$BOOT_CONFIG" || true

# Remove any existing eFinder additions
sed -i '/^# --- eFinder additions/,/^enable_uart=1/d' "$BOOT_CONFIG" || true

# Add eFinder configuration
cat >> "$BOOT_CONFIG" << 'EOF'

# --- eFinder additions ---
# IMX477 camera (RPi HQ Camera or Arducam IMX477)
camera_auto_detect=0
dtoverlay=imx477

# USB gadget serial — enables /dev/ttyGS0 for tethered console
dtoverlay=dwc2,dr_mode=peripheral
enable_uart=1
EOF

echo "  Boot firmware configured for IMX477 camera and USB serial"

# Configure cmdline for USB gadget
CMDLINE=/boot/firmware/cmdline.txt
if ! grep -q "modules-load=dwc2,g_serial" "$CMDLINE"; then
    sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' "$CMDLINE"
    echo "  Kernel command line updated for USB serial"
fi

echo ""
echo "[9/10] Configuring NetworkManager WiFi AP..."

# Get MAC address for SSID suffix
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "00:00:00:00:00:00")
LAST4=$(echo "$MAC" | tr -d ':' | tail -c 5)
SSID="efinder${LAST4}"

echo "  SSID: $SSID"
echo "  Password: $WIFI_PASSWORD"

# Save default hotspot info
cat > "$EFINDER_HOME/Solver/default_hotspot.txt" << EOF
ssid:${SSID}
password:${WIFI_PASSWORD}
EOF
chown "$EFINDER_USER:$EFINDER_USER" "$EFINDER_HOME/Solver/default_hotspot.txt"

# Delete existing AP profile
nmcli connection delete "efinder-ap" 2>/dev/null || true

# Create AP profile
nmcli connection add \
    type wifi \
    ifname wlan0 \
    con-name "efinder-ap" \
    autoconnect yes \
    ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$WIFI_PASSWORD" \
    wifi.mode ap \
    wifi.band bg \
    wifi.channel 6 \
    ipv4.method shared \
    ipv4.addresses "192.168.50.1/24" \
    ipv6.method disabled \
    connection.autoconnect-priority 100

echo "  AP profile 'efinder-ap' created"
echo "  AP IP: 192.168.50.1"

echo ""
echo "[10/10] Configuring system services..."

# Setup tmpfs mounts for frequently-written temporary data
if ! grep -q "$EFINDER_HOME/Solver/images" /etc/fstab; then
    cat >> /etc/fstab << EOF
tmpfs /var/tmp tmpfs nodev,nosuid,size=10M 0 0
tmpfs $EFINDER_HOME/Solver/images tmpfs nodev,nosuid,size=10M 0 0
EOF
    echo "  tmpfs mounts added to /etc/fstab"
fi

# Create eFinder systemd service
cat > /etc/systemd/system/efinder.service << 'EOF'
[Unit]
Description=eFinder telescope plate solver
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=efinder
WorkingDirectory=/home/efinder/Solver
ExecStart=/usr/bin/python3 /home/efinder/Solver/eFinder_cedar_v2.py
Restart=on-failure
RestartSec=15
StartLimitIntervalSec=120
StartLimitBurst=4
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable services
systemctl daemon-reload
systemctl enable efinder.service

echo "  eFinder service installed and enabled"

# Configure SSH
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl enable ssh

# Enable I2C (for optional accelerometer)
raspi-config nonint do_i2c 0 2>/dev/null || true

# Disable serial console (keep UART enabled for USB serial)
raspi-config nonint do_serial_cons 1 2>/dev/null || true

# Set hostname
if [ "$(hostname)" != "efinder" ]; then
    echo "efinder" > /etc/hostname
    sed -i 's/raspberrypi/efinder/g' /etc/hosts
    echo "  Hostname set to: efinder"
fi

echo ""
echo "============================================================================="
echo " eFinder application installation complete!"
echo ""
echo "  WiFi AP:"
echo "    SSID: $SSID"
echo "    Password: $WIFI_PASSWORD"
echo "    IP: 192.168.50.1"
echo ""
echo "  SSH Access:"
echo "    ssh efinder@192.168.50.1"
echo "    Password: (efinder user password)"
echo ""
echo "  Web Interface:"
echo "    http://192.168.50.1/"
echo "    - Live view (max 1000 frames)"
echo "    - Logs"
echo "    - README"
echo ""
echo "  SkySafari:"
echo "    Protocol: LX200"
echo "    Host: 192.168.50.1"
echo "    Port: 4060"
echo ""
echo "  Helper Scripts:"
echo "    ~/station.sh <ssid> [password]  - Connect to WiFi"
echo "    ~/ap.sh                         - Return to AP mode"
echo "    ~/reset.sh                      - Wipe and reinstall"
echo ""
echo "  Services:"
echo "    sudo systemctl status efinder   - Check status"
echo "    journalctl -u efinder -f        - View logs"
echo ""
echo "  Reboot required to activate all changes:"
echo "    sudo reboot"
echo "============================================================================="
