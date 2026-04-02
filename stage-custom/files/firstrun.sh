#!/bin/bash
set -e
LOG=/home/efinder/firstrun.log
exec > >(tee -a "$LOG") 2>&1

echo "=== eFinder first-boot setup: $(date) ==="

# Source the pre-baked credentials
source /home/efinder/config.env

# Export them so install.sh can read them as env vars instead of prompting
export WIFI_SSID WIFI_PASS SAMBA_PASS

cd /home/efinder
bash /home/efinder/install.sh --non-interactive

# Disable this service so it never runs again
systemctl disable firstrun.service
rm -f /etc/systemd/system/firstrun.service

echo "=== First-boot setup complete: $(date) ==="
reboot
