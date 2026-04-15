#!/bin/bash
# station.sh — connect to external WiFi (station mode)
# Usage: ~/station.sh [ssid] [password]
# Run ~/ap.sh to return to AP mode after install.
set -e

if [ -z "$1" ]; then
    nmcli device wifi rescan 2>/dev/null || true
    sleep 2
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

# Unblock WiFi radio in case it is blocked on fresh image
sudo rfkill unblock wifi 2>/dev/null || true

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
echo "Connected to: $SSID"
echo "IP Address  : $IP"
echo "Hostname    : efinder.local"
echo ""
echo "You can now run: sudo bash ~/install.sh"
