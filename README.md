# eFinder — tinySS

Plate-solving electronic finder scope for the Raspberry Pi Zero 2W.  
Connects to **SkySafari** over WiFi using the LX200 protocol on TCP port 4060.  
Uses an **IMX477 camera** (Raspberry Pi HQ Camera or Arducam IMX477) and the **Tetra3** star-pattern matching library for fast, reliable plate solving.

---

## Hardware Required

- Raspberry Pi Zero 2W
- Raspberry Pi HQ Camera or Arducam IMX477 board
- MicroSD card (16 GB or larger, Class 10 / A1 recommended)
- Micro-USB cable (data-capable, not charge-only) — for the USB data port
- Power supply via the PWR micro-USB port
- Optional: ADXL343 accelerometer on I2C for altitude readout

---

## Part 1 — Burn the SD Card

### 1.1 Download Raspberry Pi Imager

Download and install **Raspberry Pi Imager** from:  
https://www.raspberrypi.com/software/

### 1.2 Choose OS

- Click **Choose OS**
- Select **Raspberry Pi OS (other)**
- Select **Raspberry Pi OS Lite (64-bit)**  
  *(Bookworm. Do not use the Desktop version — it is not needed and wastes space.)*

### 1.3 Choose Storage

Insert your MicroSD card and select it.

### 1.4 Configure OS Settings

Click the **gear icon** (or press Ctrl+Shift+X) to open the advanced settings panel.  
Fill in the following — these must be set before burning:

| Setting | Value |
|---------|-------|
| Hostname | `efinder` |
| Username | `efinder` |
| Password | *(choose a strong password — you will use this to SSH in)* |
| WiFi SSID | *(your home WiFi network name)* |
| WiFi Password | *(your home WiFi password)* |
| WiFi country | *(your country code, e.g. US)* |
| Enable SSH | ✓ (use password authentication) |
| Locale / timezone | *(set to your timezone)* |

> **Why home WiFi?** The Pi needs internet access during installation to download packages. After installation it will switch to AP (hotspot) mode automatically. Your home WiFi credentials are only used once.

### 1.5 Write the Image

Click **Write** and wait for the process to complete. Eject the card safely when done.

---

## Part 2 — First Boot

### 2.1 Insert the Card and Power On

Insert the MicroSD card into the Pi Zero 2W.  
Connect power to the **PWR** micro-USB port (the outer port, labelled PWR IN).  
Wait approximately 60–90 seconds for first boot to complete.

### 2.2 Find the Pi on Your Network

**macOS / Linux** — open Terminal and connect. The `efinder@` prefix is required — it tells SSH to log in as the `efinder` user rather than your local laptop username:

```bash
ssh efinder@efinder.local
```

If that does not resolve, find the IP address from your router's device list and connect directly:

```bash
ssh efinder@<ip-address>
```

**Windows** — SSH is built into Windows 10 and 11. Open **PowerShell** or **Command Prompt** and run the same command:

```powershell
ssh efinder@efinder.local
```

If `efinder.local` does not resolve, find the IP from your router and use it directly. Alternatively install **PuTTY** (https://www.putty.org) for a graphical SSH client — enter hostname `efinder.local` or the IP address, port `22`, username `efinder`, and connect.

**Tip — avoid typing `efinder@` every time:** add an entry to your SSH config file so plain `ssh efinder.local` works automatically.

On macOS/Linux, create or edit `~/.ssh/config` and add:

```
Host efinder.local
    User efinder
```

On Windows the same file is at `C:\Users\<yourname>\.ssh\config`.

Log in with the password you set in the Imager.

> **If you see a "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED" error:** this happens after reflashing — the Pi has new SSH host keys but your laptop remembers the old ones. It is not a security problem in this context. See the Troubleshooting section for the fix.

---

## Part 3 — Install eFinder

All commands below are run on the Pi over SSH.

### 3.1 Install git and Clone the Repository

Git is not included in Raspberry Pi OS Lite and must be installed before cloning:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone --branch tinySS https://github.com/mconsidine/eFinder_cli.git
cd eFinder_cli
```

### 3.2 Run the Installer

```bash
sudo bash install.sh
```

The installer will work through the following steps automatically:

| Step | What happens |
|------|-------------|
| 1 | System packages updated |
| 2 | Required packages installed (picamera2, PIL, scipy, Samba, Apache, PHP) |
| 3 | Python virtual environment created at `~/venv-efinder` |
| 4 | This repository cloned to `~/eFinder_cli` |
| 5 | Working directories created, support files deployed |
| 6 | Tetra3 plate-solving library installed and star databases downloaded |
| 7 | Samba file share configured |
| 8 | Apache/PHP web server configured for OTA updates |
| 9 | `/boot/firmware/config.txt` updated for IMX477 camera and USB serial gadget |
| 10–12 | SSH, I2C, USB serial console enabled |
| 13 | `eFinder.py` deployed |
| 14–16 | systemd services installed for auto-start on boot |

> **Duration:** The Tetra3 database download is the longest step — allow 10–20 minutes depending on your connection speed. Do not interrupt the installer once it has started.

### 3.3 Reboot

When the installer finishes it will print a summary and ask:

```
Reboot now? [y/N]
```

Type `y` and press Enter. The Pi will reboot.

---

## Part 4 — After Reboot

After rebooting the Pi will **no longer connect to your home WiFi**. It now runs as a WiFi access point.

### 4.1 Connect to the eFinder WiFi Network

On your phone, tablet, or laptop:

- Open WiFi settings
- Connect to the network named **`efinder`** followed by 4 hex characters, e.g. `efinder3a2f`
- Password: **`12345678`**

The SSID and password are also saved on the Pi at:  
`/home/efinder/Solver/default_hotspot.txt`

### 4.2 Verify the eFinder is Running

From a device connected to the eFinder WiFi, open a terminal and SSH in:

```bash
ssh efinder@192.168.50.1
```

Check the service status:

```bash
sudo systemctl status efinder
```

You should see `active (running)`. To watch the live log:

```bash
journalctl -u efinder -f
```

A healthy startup looks like:

```
eFinder version 6.6
Coordinates ready
Accelerometer disabled
Loading Tetra3 database…
Tetra3 ready
Offset: (380.0, 480.0)
Starting solve loop…
Starting WiFi/LX200 server…
eFinder running — waiting for SkySafari connection on port 4060
```

### 4.3 Test the LX200 Interface

With the service running, confirm the LX200 server is responding by querying the version number from the Pi itself:

```bash
echo -n ':GV#' | nc 127.0.0.1 4060
```

You should get back `:GV6.6#` immediately. If nothing is returned the service is not listening on port 4060 — check `sudo systemctl status efinder`.

### 4.4 Test the Camera

Stop the service to release the camera, take a test frame, then restart:

```bash
sudo systemctl stop efinder
rpicam-still --width 960 --height 760 --shutter 200000 --gain 20 --awbgains 1,1 --nopreview -o /tmp/view.jpg
sudo systemctl start efinder
```

If `rpicam-still` succeeds without error the camera is correctly wired and the overlay is loaded. Pull the image to your laptop to inspect it:

```bash
# macOS
scp efinder@192.168.50.1:/tmp/view.jpg . && open view.jpg

# Linux
scp efinder@192.168.50.1:/tmp/view.jpg . && xdg-open view.jpg

# Windows PowerShell
scp efinder@192.168.50.1:/tmp/view.jpg .
```

Then open `view.jpg` from File Explorer.

---

## Part 5 — Connect SkySafari

### 5.1 Configure SkySafari

In SkySafari, go to **Settings → Telescope → Setup**:

| Setting | Value |
|---------|-------|
| Scope Type | Meade LX-200 GPS |
| Mount Type | Alt-Az (or match your mount) |
| IP Address | `192.168.50.1` |
| Port | `4060` |

### 5.2 Connect

Tap **Connect** in SkySafari. The eFinder log will show:

```
SkySafari connected from ('192.168.50.1', <port>)
```

SkySafari will send its date and time to the Pi on connection. The Pi sets its system clock from this — no internet or NTP is required in the field.

---

## Part 6 — Normal Use

Power on the Pi. Wait 30–60 seconds. Connect your phone to the eFinder WiFi. Connect SkySafari. The eFinder plate-solves continuously and reports the current position to SkySafari automatically.

No interaction with the Pi is needed during normal use.

---

## Web Interface

From any device connected to the eFinder WiFi, open a browser and go to:

| URL | What it shows |
|-----|--------------|
| `http://192.168.50.1/` | OTA update uploader |
| `http://192.168.50.1/log.php` | Live eFinder log (auto-refreshes every 5s) |
| `http://192.168.50.1/log.php?lines=100` | Last 100 log lines |
| `http://192.168.50.1/README.md` | This documentation |

The log page is the fastest way to check whether the eFinder is running correctly without needing SSH. A healthy log looks like:

```
eFinder version 6.6
Camera  : OK
Database: OK
Accel   : not fitted
Starting solve loop…
Starting WiFi/LX200 server…
eFinder running — waiting for SkySafari connection on port 4060
```

If the camera or database failed to load the log will show clearly which one and why.

---

## Part 7 — Focusing

The eFinder application must **not** be running while you focus, since it holds the camera exclusively. Stop it first:

```bash
sudo systemctl stop efinder
```

Restart it when done:

```bash
sudo systemctl start efinder
```

### Method 1 — Single Frame Capture (Recommended)

Take a still image using the same exposure and gain settings the app uses, then pull it to your laptop to inspect:

```bash
rpicam-still \
  --width 960 --height 760 \
  --shutter 200000 \
  --gain 20 \
  --awbgains 1,1 \
  --nopreview \
  -o /tmp/focus_test.jpg
```

Then on your laptop:

```bash
# macOS
scp efinder@192.168.50.1:/tmp/focus_test.jpg . && open focus_test.jpg

# Linux
scp efinder@192.168.50.1:/tmp/focus_test.jpg . && xdg-open focus_test.jpg
```

**Windows** — run in PowerShell:

```powershell
scp efinder@192.168.50.1:/tmp/focus_test.jpg .
```

Then open `focus_test.jpg` from File Explorer, or use a viewer like **IrfanView** that lets you zoom to 100% to judge star sharpness. If you have **WinSCP** installed you can browse and download files graphically instead.

Adjust focus, repeat until stars are tight pinpoints. The `--shutter` value is in microseconds — `200000` equals 0.2 seconds, matching the default `Exposure:0.2` in `eFinder.config`. `--awbgains 1,1` disables auto white balance, matching the app's behaviour.

To iterate quickly without retyping, use a one-liner loop on the Pi:

```bash
while true; do
  rpicam-still --width 960 --height 760 \
    --shutter 200000 --gain 20 --awbgains 1,1 \
    --nopreview -o /tmp/focus_test.jpg && \
  echo "Image captured — adjust focus and press Enter for next, Ctrl-C to stop"
  read
done
```

### Method 2 — Live MJPEG Stream to Laptop

For a real-time view while adjusting focus, stream video from the Pi:

```bash
rpicam-vid \
  --timeout 0 \
  --width 960 --height 760 \
  --shutter 200000 \
  --gain 20 \
  --codec mjpeg \
  --listen \
  -o tcp://0.0.0.0:8080
```

Then on your laptop open the stream in VLC (**Media → Open Network Stream**):

```
tcp/h264://192.168.50.1:8080
```

Or with ffplay (macOS/Linux):

```bash
ffplay tcp://192.168.50.1:8080
```

**Windows** — VLC for Windows works identically. Download from https://www.videolan.org if not already installed. ffplay is available as part of **ffmpeg for Windows** (https://ffmpeg.org/download.html) if you prefer the command line.

Press Ctrl-C on the Pi to stop streaming when done.

### Focus Targets

**Best:** Stars at night. Point at a bright star (magnitude 1–3), use `--shutter 50000 --gain 10` as a starting point to avoid saturation, and adjust until the star disc is a tight point.

**Good:** The Moon. Bright, high-contrast, genuinely at infinity. Adjust `--shutter` down to `1000`–`5000` to avoid overexposure.

**Acceptable for bench setup:** An artificial star — a pinhole (0.1–0.5 mm) over a torch at 10 metres or more. Closer than 10 m will not be at true infinity focus for a 25 mm focal length lens.

**Avoid:** Daytime terrestrial targets at less than ~500 m. They are close enough that infinity focus will be slightly off, and the eFinder operates exclusively on star fields.

### Verifying Focus with the App

Once focused, restart the app and check the solve quality in the log:

```bash
sudo systemctl start efinder
journalctl -u efinder -f
```

A well-focused image on a clear night should show **30–80 centroids** and a **peak pixel value** in the range 150–230. Too few centroids means underexposed or out of focus. Peak value consistently above 240 means overexposed — reduce `Exposure` in `eFinder.config`.

---

## Maintenance Access

### SSH over WiFi (primary)

When connected to the eFinder WiFi network, open Terminal (macOS/Linux) or PowerShell/Command Prompt (Windows):

```bash
ssh efinder@192.168.50.1
```

Windows users can also use **PuTTY** — enter IP `192.168.50.1`, port `22`.

### USB Serial Console (recovery / no WiFi)

Connect a data-capable USB cable to the **USB** port (the inner port, not PWR).

**macOS** — the device appears as `/dev/cu.usbmodem*`. Use **CoolTerm** or screen:

```bash
screen /dev/cu.usbmodem* 115200
```

**Linux** — the device appears as `/dev/ttyACM0`. Use screen or minicom:

```bash
screen /dev/ttyACM0 115200
```

**Windows** — the device appears as a **COM port** (e.g. `COM3`) in Device Manager under *Ports (COM & LPT)*. Use **CoolTerm** (https://freeware.the-meiers.org) or **PuTTY** — select Serial, enter the COM port number, speed 115200.

All platforms: connect at **115200 baud, 8N1**. This gives a login prompt directly — useful if the WiFi AP is not starting correctly.

---

### Switching Between AP Mode and Station (Home Network) Mode

By default the eFinder boots into AP mode. There are times when you need it back on your home network — to re-run the installer, download updates, or diagnose a problem from a computer that has no WiFi. This section covers the full round-trip.

#### Step 1 — Get a Console

If you cannot SSH in because the Pi is in AP mode and your computer has no WiFi, connect via the USB serial console (see above). Log in as `efinder`.

If you are already connected to the eFinder WiFi on another device, SSH in normally:

```bash
ssh efinder@192.168.50.1
```

#### Step 2 — Switch to Station Mode (Home Network)

A helper script is installed at `~/station.sh` for convenience. Run it from the serial console:

```bash
~/station.sh
```

Or run the two commands manually:

```bash
sudo nmcli connection modify preconfigured autoconnect yes
sudo nmcli connection up preconfigured
```

NetworkManager will bring up your home WiFi immediately. The AP connection drops at the same time — the Pi Zero 2W has a single radio and cannot run both simultaneously.

Confirm it worked:

```bash
nmcli connection show --active
ip addr show wlan0
```

You should see your home network listed as active and a home network IP address on `wlan0`. You can now SSH in from any computer on your home network using that IP or `efinder.local`:

```bash
ssh efinder@efinder.local
```

Or find the IP address from your router's device list if `efinder.local` does not resolve.

#### Step 3 — Do Whatever You Needed to Do

Re-run the installer, update packages, copy files, diagnose issues. The Pi now has full internet access.

If re-running the installer:

```bash
cd ~/eFinder_cli
sudo bash install.sh
```

The installer will automatically disable home WiFi autoconnect at the very end before asking to reboot, so you do not need to do Step 4 manually if you let the installer complete.

#### Step 4 — Return to AP Mode

When you are done, disable home WiFi autoconnect and reboot:

```bash
sudo nmcli connection modify preconfigured autoconnect no
sudo reboot now
```

After rebooting the eFinder comes back in AP mode as normal. Connect to the `efinder****` WiFi network and SSH to `192.168.50.1`.

#### Quick Reference

| Goal | Command |
|------|---------|
| Switch to home network (quick) | `~/station.sh` |
| Switch to home network manually | `sudo nmcli connection up preconfigured` |
| Make home network persist across reboots | `sudo nmcli connection modify preconfigured autoconnect yes` |
| Switch back to AP now | `sudo nmcli connection up efinder-ap` |
| Make AP the default again | `sudo nmcli connection modify preconfigured autoconnect no` |
| Check what is currently active | `nmcli connection show --active` |
| See all known connections | `nmcli connection show` |

> **Note:** Changing `autoconnect` alone does not immediately switch networks — it only affects what happens at the next reboot. Use `nmcli connection up <name>` to switch immediately.

---

### Samba File Share

**macOS** — in Finder press **Cmd+K** and enter:

```
smb://192.168.50.1/efindershare
```

**Linux** — open a file manager and connect to:

```
smb://192.168.50.1/efindershare
```

Or mount from the terminal:

```bash
sudo mount -t cifs //192.168.50.1/efindershare /mnt/efinder -o username=efinder
```

**Windows** — open **File Explorer**, click in the address bar and enter:

```
\\192.168.50.1\efindershare
```

Or map it as a network drive: right-click **This PC → Map network drive**, enter `\\192.168.50.1\efindershare`, and tick *Connect using different credentials*.

All platforms: Username `efinder` / Password `efinder`.

This gives read/write access to `/home/efinder` — useful for copying config files or captured images without SSH.

---

## OTA Updates

To update files on the Pi without SSH:

1. Create a zip archive of the files to update, preserving their full paths from `/`  
   e.g. `home/efinder/Solver/eFinder.py` inside the zip
2. Name the file `efinderUpdate.zip`
3. Copy it to `\\192.168.50.1\efindershare\uploads\` via Samba
4. Reboot the Pi

On next boot the update service runs before the main app, extracts the zip to `/`, and reboots again automatically. If the zip is malformed it is deleted and the Pi continues normally.

---

## Troubleshooting

**"WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED" when trying to SSH**

This happens every time you reflash the SD card. The Pi gets new SSH host keys after flashing but your laptop still has the old ones saved from a previous install. It is not a real security problem — it simply means the Pi looks different from what your laptop expected.

The fix is to remove the old key from your laptop's known hosts file.

**macOS / Linux:**
```bash
ssh-keygen -f "~/.ssh/known_hosts" -R "efinder.local"
```

If you also connect by IP address, remove that entry too:
```bash
ssh-keygen -f "~/.ssh/known_hosts" -R "192.168.50.1"
```

**Windows (PowerShell):**
```powershell
ssh-keygen -R "efinder.local"
ssh-keygen -R "192.168.50.1"
```

Or open `C:\Users\<yourname>\.ssh\known_hosts` in a text editor, delete the line containing `efinder.local` or `192.168.50.1`, and save.

After removing the old key, SSH in again normally and type `yes` when asked to confirm the new fingerprint:

```bash
ssh efinder@efinder.local
```

This will not happen again until the next reflash.

**"Permission denied (publickey)" or connecting as wrong user**

This happens when SSH tries to connect as your local laptop username instead of `efinder`. Always include the username explicitly:

```bash
ssh efinder@efinder.local
```

To avoid typing `efinder@` every time, add this to `~/.ssh/config` (macOS/Linux) or `C:\Users\<yourname>\.ssh\config` (Windows):

```
Host efinder.local
    User efinder
```

After that, plain `ssh efinder.local` connects as `efinder` automatically.

**eFinder service fails to start**

Check the log — either via SSH or directly in the browser at `http://192.168.50.1/log.php`:

```bash
journalctl -u efinder -b --no-pager
```

Common causes:
- Camera not detected — check `rpicam-hello --list-cameras`; verify the ribbon cable is seated; confirm `dtoverlay=imx477` is in `/boot/firmware/config.txt`
- Tetra3 database missing — check `~/venv-efinder/lib/python*/site-packages/tetra3/data/` contains `.npz` files

**SkySafari cannot connect**

- Confirm your device is on the eFinder WiFi, not your home network
- Confirm port is set to `4060` not `4061`
- Check `sudo systemctl status efinder` — the service must be running before SkySafari connects

**WiFi AP not appearing after reboot**

Check whether the profile exists and bring it up manually:

```bash
nmcli connection show
sudo nmcli connection up efinder-ap
```

If `efinder-ap` is not listed, the AP profile was never created — re-run `install.sh` with internet access.

**Need to SSH in but your computer has no WiFi**

Use the USB serial console (see Maintenance Access above) to log in, then switch to station mode so your home network is available:

```bash
sudo nmcli connection modify preconfigured autoconnect yes
sudo nmcli connection up preconfigured
```

Then SSH in from your home network. See the **Switching Between AP Mode and Station Mode** section for the full round-trip procedure.

**Restore home WiFi temporarily** (to re-run installer, download updates, or diagnose problems with internet access):

```bash
sudo nmcli connection modify preconfigured autoconnect yes
sudo nmcli connection up preconfigured
```

To return to AP-only mode when done:

```bash
sudo nmcli connection modify preconfigured autoconnect no
sudo reboot now
```

**Check camera overlay**

```bash
vcgencmd get_config dtoverlay
rpicam-hello --list-cameras
```

---

## Diagnostic Commands over TCP

Any TCP client (e.g. `nc`, a Python script, or a custom app) connected to port 4060 can send these diagnostic commands while SkySafari is not connected:

| Command | Response | Description |
|---------|----------|-------------|
| `:PS#` | `:PS1#` or `:PS0#` | Trigger a plate solve |
| `:GV#` | `:GV6.6#` | Get software version |
| `:GS#` | `:GS  42#` | Get star count from last solve |
| `:GK#` | `:GK 187#` | Get peak pixel value from last solve |
| `:Gt#` | `:Gt02.34#` | Get elapsed solve time (seconds) |
| `:GO#` | `:GO0.012,0.003#` | Get current pointing offset |
| `:SO#` | `:SO1#` | Reset offset to image centre |
| `:OF#` | `:OFAlbireo,HIP98110,...#` | Measure offset, return alignment star |
| `:GX#` | `:GX0.2#` | Auto-expose, return chosen exposure |
| `:SX0.3#` | `:SX1#` | Set exposure to 0.3 seconds |
| `:GA#` | `:GA45#` | Get scope altitude (requires accelerometer) |
| `:TS#` | `:TS1#` | Enable test mode (uses test.npy instead of camera) |
| `:TO#` | `:TO1#` | Disable test mode |
| `:IM1#` | `:IM1#` | Start saving debug images to `Solver/images/` |
| `:IM0#` | `:IM1#` | Stop saving debug images |

Example using netcat — from your laptop on the eFinder WiFi (macOS/Linux):

```bash
echo -n ':GV#' | nc 192.168.50.1 4060
```

Or from the Pi itself over SSH (uses loopback — works regardless of WiFi mode):

```bash
echo -n ':GV#' | nc 127.0.0.1 4060
```

**Windows** — use PowerShell's built-in TCP client:

```powershell
$tcp = New-Object System.Net.Sockets.TcpClient('192.168.50.1', 4060)
$stream = $tcp.GetStream()
$bytes = [System.Text.Encoding]::ASCII.GetBytes(':GV#')
$stream.Write($bytes, 0, $bytes.Length)
Start-Sleep -Milliseconds 200
$buf = New-Object byte[] 1024
$len = $stream.Read($buf, 0, 1024)
[System.Text.Encoding]::ASCII.GetString($buf, 0, $len)
$tcp.Close()
```

Or install **netcat for Windows** via winget: `winget install netcat` and use the same syntax as macOS/Linux.

---

## File Layout on the Pi

```
/home/efinder/
├── venv-efinder/          Python virtual environment
├── tetra3/                Tetra3 source
├── eFinder_cli/           Repository clone (tinySS branch)
├── uploads/               OTA update zip drop location
├── station.sh             Switch to home network (run from serial console)
└── Solver/
    ├── eFinder.py         Main application
    ├── eFinder.config     Saved exposure, gain, and offset settings
    ├── starnames.csv      HIP star name lookup for offset measurement
    ├── text.ttf           Font for debug image annotation
    ├── test.npy           Test image for test mode (northern hemisphere)
    ├── images/            Debug capture output (tmpfs — cleared on reboot)
    ├── default_hotspot.txt  AP SSID and password
    └── www/               Web UI files for OTA updater
        ├── log.php        Live log viewer (http://192.168.50.1/log.php)
        └── README.md      This documentation (http://192.168.50.1/README.md)
```

---

## License

Derived from original eFinder work Copyright (C) 2025 Keith Venables, licensed under the GNU General Public License v3.  
See https://github.com/AstroKeith/eFinder_cli for the original project.
