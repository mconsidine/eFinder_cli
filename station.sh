#!/bin/bash
# station.sh -- connect to external WiFi (station mode)
# Usage: ~/station.sh [ssid] [password]
# Run ~/ap.sh to return to AP mode after install.
set -e

echo "Initialising WiFi radio..."

# Unblock WiFi radio -- required on fresh Bookworm images
sudo rfkill unblock wifi
for f in /var/lib/systemd/rfkill/*:wlan; do
    [ -f "$f" ] && echo 0 | sudo tee "$f" > /dev/null
done

# Check if country code is already set.
# raspi-config do_wifi_country requires a reboot to take effect --
# if not yet set, set it now and reboot. Re-run station.sh after reboot.
CURRENT_COUNTRY=$(iw reg get 2>/dev/null | grep -oP '(?<=country )\w+' | head -1)
if [ "$CURRENT_COUNTRY" = "00" ] || [ -z "$CURRENT_COUNTRY" ]; then
    echo "  WiFi country code not set -- setting to US and rebooting."
    echo "  Re-run ~/station.sh after reboot."
    sudo raspi-config nonint do_wifi_country US 2>/dev/null || true
    sleep 2
    sudo reboot
    exit 0
fi

# Restart NetworkManager so it picks up the unblocked radio
sudo systemctl restart NetworkManager
sleep 3

# Confirm wlan0 is present
if ! ip link show wlan0 &>/dev/null; then
    echo "ERROR: wlan0 not found after radio unblock."
    echo "       Check that the Pi has a WiFi module and the overlay is loaded."
    exit 1
fi

echo "WiFi radio ready (country: $CURRENT_COUNTRY)"
echo ""

if [ -z "$1" ]; then
    echo "Scanning for WiFi networks..."
    nmcli device wifi rescan 2>/dev/null || true
    sleep 2
    echo ""
    echo "Available networks:"
    nmcli -f SSID,SIGNAL,SECURITY device wifi list | head -20
    echo ""
    read -rp "Enter SSID: " SSID
    read -rsp "Enter password (blank for open): " PASSWORD
    echo ""
else
    SSID="$1"
    PASSWORD="${2:-}"
fi

[ -z "$SSID" ] && { echo "ERROR: SSID cannot be empty"; exit 1; }

echo "Connecting to: $SSID"

if [ -n "$PASSWORD" ]; then
    sudo nmcli device wifi connect "$SSID" password "$PASSWORD" || {
        echo "Connection failed. Check SSID and password."
        exit 1
    }
else
    sudo nmcli device wifi connect "$SSID" || {
        echo "Connection failed."
        exit 1
    }
fi

# Wait for IP (up to 15 s)
echo "Waiting for IP address..."
IP=""
for i in $(seq 1 15); do
    IP=$(ip -4 addr show wlan0 | grep -oP '(?<=inet )[\d.]+' | head -1)
    [ -n "$IP" ] && break
    sleep 1
done
[ -z "$IP" ] && IP=$(hostname -I | awk '{print $1}')

echo ""
echo "Connected to : $SSID"
echo "IP Address   : $IP"
echo "Hostname     : efinder.local"
echo ""
echo "You can now run: sudo bash ~/install.sh"
