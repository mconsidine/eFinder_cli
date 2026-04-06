# eFinder Enhanced Edition

<div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
  <h2 style="margin: 0; color: white;">🔭 Advanced Plate-Solving Telescope Finder</h2>
  <p style="margin: 10px 0 0 0; opacity: 0.9;">Raspberry Pi Zero 2W • Cedar-Solve • OnStepX • WiFi</p>
</div>

## 📱 Quick Start

**Default Credentials:**
- WiFi SSID: `efinderXXXX` (last 4 of MAC)
- Password: `12345678`
- Web Interface: http://192.168.50.1/
- SSH: `ssh efinder@192.168.50.1`

**First Connection:**
1. Power on eFinder
2. Wait 60 seconds for boot
3. Connect phone to `efinderXXXX` WiFi
4. Open browser to `192.168.50.1`

---

## ✨ What's New

This enhanced edition adds:

### 🎯 Focus Assist
Real-time focus quality metrics:
- **FWHM** - Star sharpness (lower = better)
- **HFD** - Half-flux diameter (robust to noise)
- **Focus Score** - Overall quality (0-100)
- **Trend Analysis** - Improving/degrading/stable

**Access:** http://192.168.50.1/focus.php

### 📐 Alignment Calibration
Interactive wizard to measure optical axis offset:
- Capture 2-3 sky samples
- Automatic offset calculation
- Saves to configuration
- Improves pointing accuracy

**Access:** http://192.168.50.1/calibrate.php

### 🔗 OnStepX Mount Support
Direct serial connection to OnStepX mounts:
- **FYSETC S6** - GPIO serial
- **MLAstro SAL-33** - USB or GPIO
- **Juwei-17** - OnStep upgrade required

Enables GoTo, sync, and auto-track features.

### 📊 Status Dashboard
Live system monitoring:
- Mount position (RA/Dec/Alt/Az)
- Plate solving statistics
- Focus metrics
- Network info
- System resources

**Access:** http://192.168.50.1/status.php

### ⚡ Performance
**On-demand web interface:**
- Zero overhead when pages not open
- 0% CPU when idle
- Plate solving never affected
- Live view limited to 1000 frames per session

---

## 🌐 Web Interface

<div style="background: #f5f5f5; padding: 15px; border-radius: 6px; margin: 15px 0;">

### Live View
Real-time MJPEG stream from camera
- On-demand streaming
- 1000 frame limit per session
- Current RA/Dec display
- Solve status indicator

### Focus Assist
Interactive focus optimization
- Live FWHM calculation
- HFD measurement
- SNR tracking
- Focus score trending

### Calibration Wizard
Step-by-step alignment setup
- 3-sample average
- Offset calculation
- Auto-save to config
- Variance reporting

### Status Dashboard
Complete system overview
- Position telemetry
- Solve statistics
- Mount connection
- System health

### Logs
Real-time log viewer
- Plate solve events
- Mount commands
- Errors and warnings
- System messages

</div>

---

## 🛠️ Setup & Configuration

### WiFi Modes

**AP Mode (Default):**
```bash
# Create WiFi hotspot
# SSID: efinderXXXX
# IP: 192.168.50.1
# No internet access
```

**Station Mode (Home WiFi):**
```bash
# SSH into eFinder
ssh efinder@192.168.50.1

# Interactive (scans networks)
~/station.sh

# Or specify SSID/password
~/station.sh "MyWiFi" "password123"

# Return to AP mode
~/ap.sh
```

### Mount Connection

**WiFi (SkySafari):**
- Protocol: Meade LX200 Classic
- Host: 192.168.50.1
- Port: 4060

**Serial (OnStepX):**
1. Wire GPIO pins to mount (see docs)
2. Edit `/home/efinder/Solver/eFinder.config`
3. Set `mode = SERIAL`
4. Reboot

### Focus Calibration

1. Navigate to **Focus Assist**
2. Click "Start Focus Monitoring"
3. Adjust telescope focus knob
4. Watch FWHM decrease
5. Target: FWHM < 3.0, Score > 80

### Alignment Calibration

1. Navigate to **Calibration**
2. Start wizard
3. Sample 1: Star in **East** (low altitude)
4. Center in main scope eyepiece
5. Capture sample
6. Sample 2: Star in **South** (high altitude)
7. Capture sample
8. Sample 3: Star in **West** (medium altitude)
9. Calculate and save offset

---

## 📖 Documentation

### Included Guides

| Document | Purpose |
|----------|---------|
| **BUILD_COMPLETE_IMAGE.md** | Create bootable OS image |
| **ONSTEPX_CONNECTION_GUIDE.md** | Wire mount serial connection |
| **IMPLEMENTATION_SUMMARY.md** | Feature implementation details |
| **FEATURE_COMPARISON.md** | vs AstroKeith eFinder |

Access via Help menu or GitHub repository.

### Hardware Requirements

**Required:**
- Raspberry Pi Zero 2W
- IMX477 camera (HQ Camera or Arducam)
- 25mm f/1.2 lens (or similar)
- 16GB+ microSD card
- USB power bank (5V 2A+)

**Optional:**
- OnStepX mount (for serial control)
- USB serial cable (for console access)
- GPS module (if operating standalone)

### Software Stack

- **OS:** Raspberry Pi OS Lite (Bookworm 64-bit)
- **Plate Solver:** Cedar-Solve (Rust + Python)
- **Web Server:** Apache 2.4 + PHP 8.2
- **File Sharing:** Samba
- **Protocol:** LX200 (WiFi or Serial)
- **Network:** NetworkManager (AP/Station modes)

---

## 🔧 Troubleshooting

### Common Issues

**Web interface not loading:**
```bash
# Check Apache status
sudo systemctl status apache2

# Restart Apache
sudo systemctl restart apache2
```

**eFinder not solving:**
```bash
# Check eFinder service
sudo systemctl status efinder

# View logs
journalctl -u efinder -f

# Check database exists
ls -l /home/efinder/Solver/databases/
```

**Live view not working:**
- Refresh page to start new session
- Check camera connection
- View logs for errors

**Focus assist shows no data:**
- Point at stars (not daylight)
- Ensure camera is focused
- Check exposure settings

**Mount not connecting (serial):**
```bash
# Check serial port exists
ls -l /dev/ttyAMA0

# Test with minicom
sudo minicom -D /dev/ttyAMA0 -b 9600
# Type: :GVN#
# Should get version response
```

### Get Help

- **Logs:** http://192.168.50.1/log.php
- **Status:** http://192.168.50.1/status.php
- **GitHub:** https://github.com/mconsidine/eFinder_cli
- **Issues:** Create issue on GitHub

---

## 📱 Mobile Tips

### Best Practices

**Display:**
- Use landscape mode for tables
- Pinch to zoom on charts
- Pull down to refresh status

**Connection:**
- Save WiFi password in phone
- Bookmark http://192.168.50.1/
- Use airplane mode + WiFi for dark sites

**Battery:**
- Dim phone screen
- Close other apps
- Disable cellular (if no signal)

### Recommended Apps

**SkySafari:**
- Telescope: Meade LX200 Classic
- Mount Type: Equatorial/Alt-Az
- Host: 192.168.50.1
- Port: 4060

**SSH Client (optional):**
- Terminus (iOS)
- JuiceSSH (Android)

---

## 🔐 Security

### Default Passwords

| Service | Username | Password |
|---------|----------|----------|
| SSH | efinder | 12345678 |
| WiFi AP | - | 12345678 |
| Samba | efinder | 12345678 |

**⚠️ Change after first boot:**

```bash
# Change user password
passwd

# Change Samba password
sudo smbpasswd efinder

# WiFi AP password requires recreating
# the NetworkManager connection
```

### Network Security

- AP mode: Isolated network (no internet)
- Station mode: Standard WiFi security
- No ports open to internet
- SSH password auth (change default!)

---

## 📜 License

Same as original eFinder_cli project (check repository).

## 🙏 Credits

**Original eFinder:** AstroKeith  
**Cedar-Solve:** smroid  
**OnStepX:** Howard Dutton  
**Enhanced Edition:** mconsidine

## 🔗 Links

- **Repository:** https://github.com/mconsidine/eFinder_cli
- **OnStepX:** https://onstep.groups.io
- **Cedar-Solve:** https://github.com/smroid/cedar-solve
- **eFinder Forum:** https://groups.io/g/eFinder

---

<div style="background: #e3f2fd; padding: 15px; border-left: 4px solid #2196f3; margin: 20px 0;">
  <strong>💡 Pro Tip:</strong> Run alignment calibration at the start of each session for best pointing accuracy. Takes 5 minutes, dramatically improves GoTo performance.
</div>

<div style="background: #fff3e0; padding: 15px; border-left: 4px solid #ff9800; margin: 20px 0;">
  <strong>⚠️ Important:</strong> Live view is limited to 1000 frames per session to prevent resource exhaustion. Refresh the page to start a new session.
</div>

<div style="background: #e8f5e9; padding: 15px; border-left: 4px solid #4caf50; margin: 20px 0;">
  <strong>✨ Feature Request?</strong> Open an issue on GitHub or submit a pull request. Contributions welcome!
</div>

---

**Version:** Enhanced Edition (Cedar + OnStepX)  
**Last Updated:** 2026-04-06  
**Status:** Production Ready

<div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 2px solid #e0e0e0;">
  <p style="color: #666; font-size: 0.9em;">
    Clear skies! 🌠
  </p>
</div>
