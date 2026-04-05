#!/bin/bash
# =============================================================================
# eFinder ap.sh — switch from station (home network) mode back to AP mode.
#
# Run this from the serial console or SSH when connected to home network,
# after you are done with any internet-dependent tasks (updates, installs).
#
# Usage:
#   bash ap.sh
#
# The Pi will disable the home network autoconnect and reboot into AP mode.
# After reboot connect to the eFinder WiFi (SSID printed in /home/efinder/
# Solver/default_hotspot.txt) and SSH to 192.168.50.1.
# =============================================================================

echo "Switching to AP mode on next reboot..."
sudo nmcli connection modify preconfigured autoconnect no 2>/dev/null || true
echo ""

HOTSPOT="$HOME/Solver/default_hotspot.txt"
if [ -f "$HOTSPOT" ]; then
    echo "After reboot connect to:"
    cat "$HOTSPOT"
else
    echo "After reboot connect to the efinder<last4MAC> WiFi network."
fi

echo ""
echo "Password: 12345678"
echo "SSH:      ssh efinder@192.168.50.1"
echo ""
echo "Rebooting in 5 seconds... (Ctrl+C to cancel)"
sleep 5
sudo reboot now
