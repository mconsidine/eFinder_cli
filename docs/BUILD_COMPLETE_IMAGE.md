# Complete eFinder OS Image Build Instructions

## Overview

This guide walks through creating a complete, bootable eFinder OS image from scratch, including:
- Cedar-solve plate solver
- OnStepX mount serial connection
- Focus assist
- Alignment calibration wizard
- On-demand web interface (zero overhead when not accessed)

**Build time:** ~3 hours  
**Result:** Burnable SD card image ready for Pi Zero 2W

---

## Prerequisites

### Hardware
- Raspberry Pi Zero 2W (for testing)
- 16GB+ microSD card
- SD card reader
- Computer running Linux/Mac/WSL2

### Software
- Git
- Python 3.9+
- SD card flashing tool (Raspberry Pi Imager, Etcher, or `dd`)

---

## Method 1: GitHub Actions Build (Recommended)

**Easiest method - builds image in the cloud**

### Step 1: Prepare Repository

```bash
# Clone your repo
cd ~/eFinder_cli
git checkout tinySS

# Create directories
mkdir -p .github/workflows
mkdir -p Solver/www/api

# Copy all files to repo
cp /path/to/build-efinder-image.yml .github/workflows/
cp /path/to/install-*.sh .
cp /path/to/onstepx_serial.py Solver/
cp /path/to/focus_assist.py Solver/
cp /path/to/alignment_calibration.py Solver/

# Copy web files
cp /path/to/index.php Solver/www/
cp /path/to/focus.php Solver/www/
cp /path/to/calibrate.php Solver/www/
cp /path/to/status.php Solver/www/
cp /path/to/nav.php Solver/www/
cp /path/to/efinder-common.js Solver/www/
cp /path/to/api/*.php Solver/www/api/
```

### Step 2: Update GitHub PAT

Your GitHub Personal Access Token needs `workflow` scope:

1. Go to https://github.com/settings/tokens
2. Edit your existing token or create new one
3. Check "workflow" permission
4. Save token
5. Update `~/githubtokenmattc.txt` with new token

### Step 3: Push to GitHub

```bash
git add .
git commit -m "Add modular installation and web interface"
git push origin tinySS
```

### Step 4: Trigger Build

1. Go to https://github.com/mconsidine/eFinder_cli/actions
2. Select "Build eFinder Pi OS Image"
3. Click "Run workflow"
4. Configure:
   - Pi OS date: `2025-11-24`
   - WiFi password: `12345678` (or your preference)
5. Click "Run workflow"

### Step 5: Wait for Build

Build takes ~45-60 minutes. Monitor progress in Actions tab.

### Step 6: Download Image

Once complete:
1. Click on the completed workflow run
2. Scroll to "Artifacts"
3. Download `efinder-image-2025-11-24`
4. Also download `installation-instructions`

---

## Method 2: Manual Build (Advanced)

**For local testing and development**

### Prerequisites

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y \
    qemu-system-arm \
    qemu-user-static \
    binfmt-support \
    kpartx \
    wget \
    xz-utils
```

### Step 1: Download Base Image

```bash
cd ~/
mkdir efinder-build
cd efinder-build

# Download Pi OS Lite
wget https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-11-24/2025-11-24-raspios-bookworm-arm64-lite.img.xz

# Extract
unxz 2025-11-24-raspios-bookworm-arm64-lite.img.xz
```

### Step 2: Mount Image

```bash
# Create loop device
sudo losetup -fP 2025-11-24-raspios-bookworm-arm64-lite.img

# Find loop device (probably /dev/loop0)
losetup -l

# Mount partitions
sudo mkdir -p /mnt/pi-boot /mnt/pi-root
sudo mount /dev/loop0p1 /mnt/pi-boot   # boot partition
sudo mount /dev/loop0p2 /mnt/pi-root   # root partition
```

### Step 3: Prepare for Chroot

```bash
# Copy QEMU ARM binary
sudo cp /usr/bin/qemu-aarch64-static /mnt/pi-root/usr/bin/

# Mount system directories
sudo mount --bind /dev /mnt/pi-root/dev
sudo mount --bind /proc /mnt/pi-root/proc
sudo mount --bind /sys /mnt/pi-root/sys
```

### Step 4: Chroot and Install

```bash
# Enter chroot
sudo chroot /mnt/pi-root /bin/bash

# Now inside Pi filesystem
export USER_PASSWORD=12345678
export WIFI_PASSWORD=12345678
export SAMBA_PASSWORD=12345678

# Copy install scripts to /tmp
# (you'll need to copy these from host to /mnt/pi-root/tmp first)
bash /tmp/install-base.sh
bash /tmp/install-cedar.sh
bash /tmp/install-efinder.sh

# Clean up
apt-get clean
rm -rf /var/lib/apt/lists/*
rm -rf /tmp/cedar-solve

# Exit chroot
exit
```

### Step 5: Unmount and Compress

```bash
# Unmount everything
sudo umount /mnt/pi-root/dev
sudo umount /mnt/pi-root/proc
sudo umount /mnt/pi-root/sys
sudo umount /mnt/pi-root
sudo umount /mnt/pi-boot

# Detach loop
sudo losetup -d /dev/loop0

# Compress
xz -6 -T0 2025-11-24-raspios-bookworm-arm64-lite.img

# Result: 2025-11-24-raspios-bookworm-arm64-lite.img.xz
```

---

## Method 3: Install on Running Pi

**Fastest for testing, not distributable**

### Step 1: Flash Base OS

1. Download Pi OS Lite (Bookworm, 64-bit)
2. Flash to SD card using Raspberry Pi Imager
3. **Before writing:**
   - Enable SSH
   - Set username: `efinder`
   - Set password: `12345678`
   - Configure WiFi (your home network)

### Step 2: Boot and Connect

```bash
# Insert SD card in Pi, power on
# Wait 60 seconds for boot

# Connect via SSH
ssh efinder@efinder.local
# Password: 12345678
```

### Step 3: One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/mconsidine/eFinder_cli/tinySS/install-complete.sh | sudo bash
```

This will:
1. Download all three phase scripts
2. Prompt for passwords (or use defaults)
3. Install everything (~30 minutes)
4. Reboot into AP mode

### Step 4: Verify Installation

After reboot:
1. Connect to WiFi: `efinderXXXX` (password: `12345678`)
2. Browse to: `http://192.168.50.1/`
3. Should see eFinder Live View page

---

## Post-Installation Configuration

### Connect to Home WiFi

```bash
# SSH into Pi (via AP or serial)
ssh efinder@192.168.50.1
# Password: 12345678

# Switch to station mode
~/station.sh
# Follow prompts: enter SSID and password

# Or non-interactive:
~/station.sh "MyHomeWiFi" "mypassword"
```

### Connect OnStepX Mount (if applicable)

**Hardware:**
- Wire Pi GPIO14/15 to mount serial port (see ONSTEPX_CONNECTION_GUIDE.md)

**Software:**
```bash
# Edit config to enable serial mount
nano /home/efinder/Solver/eFinder.config

# Add or update:
[mount]
mode = SERIAL
serial_port = /dev/ttyAMA0
serial_baudrate = 9600
```

**Disable USB serial gadget** (frees up UART for mount):
```bash
sudo nano /boot/firmware/config.txt
# Comment out:
#dtoverlay=dwc2,dr_mode=peripheral
#enable_uart=1

# Add instead:
enable_uart=1

# Reboot
sudo reboot
```

### Test Features

**Live View:**
1. Browse to `http://192.168.50.1/`
2. Click "Start Live View"
3. Should see camera stream

**Focus Assist:**
1. Go to `http://192.168.50.1/focus.php`
2. Click "Start Focus Monitoring"
3. Adjust focus on telescope
4. Watch FWHM decrease, score increase

**Alignment Calibration:**
1. Go to `http://192.168.50.1/calibrate.php`
2. Click "Start New Calibration"
3. Follow wizard steps
4. Captures 3 samples, calculates offset
5. Saves to `eFinder.config`

---

## Troubleshooting

### Build Issues

**GitHub Actions fails:**
- Check workflow file syntax
- Verify PAT has `workflow` scope
- Check Actions logs for specific error

**Manual build fails at chroot:**
- Ensure `qemu-user-static` installed
- Check QEMU binary copied correctly
- Try `sudo update-binfmts --enable`

### Runtime Issues

**eFinder process not starting:**
```bash
# Check service status
sudo systemctl status efinder

# View logs
journalctl -u efinder -f

# Manual start for debugging
cd /home/efinder/Solver
python3 eFinder_cedar_v2.py
```

**Web interface shows errors:**
```bash
# Check Apache
sudo systemctl status apache2

# Check PHP errors
sudo tail -f /var/log/apache2/error.log

# Test PHP
php -v
php -r "echo 'OK';"
```

**Focus assist fails:**
```bash
# Test Python module
cd /home/efinder/Solver
python3 focus_assist.py
# Should show test output
```

**Mount serial not connecting:**
```bash
# Check serial port
ls -l /dev/ttyAMA0

# Test with minicom
sudo minicom -D /dev/ttyAMA0 -b 9600
# Type: :GVN#
# Should get OnStep version response
```

### Performance Issues

**Web pages slow:**
- Check if eFinder process consuming CPU (plate solving)
- Web UI should have zero impact when pages not open
- Try accessing status page: shows if eFinder running

**Plate solving slow:**
- Check Cedar database generated: `/home/efinder/Solver/databases/default_database.npz`
- View eFinder logs for solve times: `journalctl -u efinder -n 50`
- Typical solve: 200-500ms on Pi Zero 2W

---

## File Checklist

Before building, ensure you have all files:

**Core System:**
- [ ] `install-complete.sh` - Master installer
- [ ] `install-base.sh` - System packages
- [ ] `install-cedar.sh` - Cedar-solve compilation
- [ ] `install-efinder.sh` - eFinder deployment

**Python Modules:**
- [ ] `onstepx_serial.py` - Mount connection
- [ ] `focus_assist.py` - Focus analysis
- [ ] `alignment_calibration.py` - Calibration wizard

**Web Interface:**
- [ ] `index.php` - Live view
- [ ] `focus.php` - Focus assist page
- [ ] `calibrate.php` - Calibration wizard page
- [ ] `status.php` - Status dashboard
- [ ] `nav.php` - Navigation menu
- [ ] `efinder-common.js` - Common JavaScript
- [ ] `log.php` - Log viewer (existing)
- [ ] `stream.php` - MJPEG stream (existing, modified for 1000 frame limit)

**API Endpoints:**
- [ ] `api/state.php` - Read state file
- [ ] `api/status.php` - Formatted status
- [ ] `api/focus.php` - Focus metrics
- [ ] `api/calibrate.php` - Calibration actions

**Documentation:**
- [ ] `BUILD_SYSTEM_GUIDE.md`
- [ ] `ONSTEPX_CONNECTION_GUIDE.md`
- [ ] `IMPLEMENTATION_SUMMARY.md`
- [ ] `FEATURE_COMPARISON.md`

---

## Expected Result

After burning and booting the image:

1. **First boot:** Devices comes up in AP mode
2. **SSID:** `efinderXXXX` (last 4 of MAC address)
3. **Password:** `12345678` (or your custom password)
4. **Connect phone/tablet** to eFinder WiFi
5. **Browse to:** `http://192.168.50.1/`
6. **Should see:** eFinder web interface with navigation menu
7. **Services running:**
   - eFinder plate solving (systemd service)
   - Apache web server
   - Samba file share
   - SSH daemon

**Default credentials:**
- SSH: `efinder` / `12345678`
- Samba: `efinder` / `12345678`
- WiFi AP: `12345678`

**Next steps:**
- Connect OnStepX mount (if applicable)
- Run alignment calibration
- Test focus assist
- Point at sky and verify plate solving

---

## Performance Verification

The on-demand architecture ensures web interface has **zero overhead** when not accessed:

```bash
# While eFinder running but no web pages open:
top -b -n 1 | grep -E 'eFinder|apache|php'

# Should show:
# eFinder_cedar_v2.py: 15-25% CPU (plate solving)
# apache2: 0% CPU (idle, waiting)
# php: not running (no processes)

# Open live view in browser:
top -b -n 1 | grep -E 'eFinder|apache|php'

# Should show:
# eFinder_cedar_v2.py: 15-25% CPU (unchanged)
# apache2: 1-2% CPU (serving MJPEG)
# php: 0-1% CPU (reading state file)

# Close browser tab:
# apache2 drops back to 0% CPU
# php processes terminate
```

**This confirms true on-demand operation with no performance degradation.**

---

## Build Complete!

You now have a complete eFinder OS image with:
- ✓ Cedar-solve plate solving
- ✓ OnStepX mount support
- ✓ Focus assist
- ✓ Alignment calibration
- ✓ On-demand web interface
- ✓ WiFi AP/Station mode switching
- ✓ USB serial console

Burn to SD card and enjoy your eFinder!
