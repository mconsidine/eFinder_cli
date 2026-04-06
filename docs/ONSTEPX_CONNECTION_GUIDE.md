# Physical Connection Guide: Pi Zero 2W to OnStepX Mounts

## Overview

This guide covers the physical serial UART connection between your Raspberry Pi Zero 2W eFinder and OnStepX-based telescope mounts. OnStepX speaks LX200 protocol over serial just like your current WiFi implementation, so integration is straightforward.

---

## Why Add Serial Connection?

**Current:** eFinder WiFi → SkySafari → WiFi → Mount  
**With serial:** eFinder serial → Mount (direct)

**Advantages:**
- **Direct mount control** - Send spiral search, parking, focus adjust commands
- **Lower latency** - No WiFi round-trip
- **One less wireless link** - More reliable in RF-noisy environments
- **Auto-track mode** - Continuous solve → correct pointing without SkySafari
- **Dual mode** - Keep WiFi/SkySafari as fallback

---

## Pi Zero 2W Serial Ports

The Pi Zero 2W has **one hardware UART** accessible on GPIO pins:

```
GPIO14 (Pin 8)  = TXD (UART0 transmit) → connects to mount RX
GPIO15 (Pin 10) = RXD (UART0 receive)  → connects to mount TX
GND    (Pin 6)  = Ground → connects to mount GND
```

**Pin numbering:** Physical pin numbers (not GPIO numbers)

**Voltage:** 3.3V logic levels (safe for most OnStepX boards)

**Current config conflict:** Your USB serial gadget (`/dev/ttyGS0`) uses the same UART0. You'll need to:
1. Disable USB serial in `config.txt`, OR
2. Use software serial for mount (slower but avoids conflict)

---

## Connection Option 1: Hardware UART (Recommended)

**Best for:** Production use, lowest latency, most reliable

**Trade-off:** Lose USB serial console (use WiFi SSH instead)

### Physical Wiring

```
Pi Zero 2W                OnStepX Board
─────────────────────────────────────────
Pin 8  (GPIO14 TXD) ────→ Serial RX
Pin 10 (GPIO15 RXD) ←──── Serial TX
Pin 6  (GND)        ────→ GND
```

**Cable:** 3-wire ribbon or individual DuPont jumpers

**Length:** Keep under 3 feet (1 meter) for reliability

### Software Configuration

1. **Disable USB serial gadget** in `/boot/firmware/config.txt`:
   ```bash
   # Comment out these lines:
   #dtoverlay=dwc2,dr_mode=peripheral
   #enable_uart=1
   ```

2. **Disable serial console** in `/boot/firmware/cmdline.txt`:
   ```bash
   # Remove: console=serial0,115200
   # Keep the rest of the line intact
   ```

3. **Enable UART** in `/boot/firmware/config.txt`:
   ```bash
   enable_uart=1
   ```

4. **Reboot:** `sudo reboot`

5. **Verify:** `/dev/ttyAMA0` (or `/dev/serial0`) should exist

---

## Connection Option 2: Software Serial (Fallback)

**Best for:** Keeping USB serial console while testing

**Trade-off:** Slower, less reliable, more CPU usage

### Physical Wiring

Use **different GPIO pins** (not GPIO14/15):

```
Pi Zero 2W                OnStepX Board
─────────────────────────────────────────
Pin 11 (GPIO17) ────────→ Serial RX
Pin 13 (GPIO27) ←──────── Serial TX
Pin 6  (GND)    ────────→ GND
```

### Software Configuration

Install software serial library:
```bash
sudo apt-get install python3-pigpio
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

Use `pigpio` for bit-banged serial in Python (implementation shown later).

---

## Mount-Specific Connection Details

### 1. FYSETC S6 Board

**Board location:** Inside mount control box

**Serial port options:**

| Port | TX Pin | RX Pin | Location | Baudrate | Notes |
|------|--------|--------|----------|----------|-------|
| **Serial1** (recommended) | PB6 | PB7 | UART header near WiFi | 9600 | Primary command channel |
| Serial2 | PA2 | PA3 | Y+ and Z+ endstops | 9600 | Reserved for GPS |
| Serial3 | PC10 | PC11 | Available | 9600 | Alternative |

**Physical connector:** 4-pin JST-XH or DuPont header labeled "UART"

**Pinout (looking at board):**
```
┌─────────────────────────┐
│ GND  TX  RX  +5V        │  ← UART header
└─────────────────────────┘
```

**Connection:**
```
Pi Pin 8 (TXD)  →  UART RX (PB7)
Pi Pin 10 (RXD) ←  UART TX (PB6)
Pi Pin 6 (GND)  →  GND
```

**Leave +5V disconnected** - Pi is powered separately

**OnStepX Config.h settings:**
```c
#define SERIAL_B_BAUD_DEFAULT 9600  // Serial1 on PB6/PB7
```

**Access:** Remove mount control box cover, locate UART header near WiFi module

---

### 2. MLAstro SAL-33

**Board:** Custom OnStepX controller based on ESP32

**Serial port:** USB-C connector (CP2102 USB-to-serial bridge)

**Connection method:** Two options

#### Option A: USB Connection (Easiest)

**No GPIO wiring needed** - use existing USB cable

```
Pi Zero 2W USB port ──(cable)──→ SAL-33 USB-C port
```

**Device:** `/dev/ttyACM0` or `/dev/ttyUSB0` (check `dmesg | grep tty`)

**Baudrate:** 9600 (default) or 115200 (configurable)

**Power:** SAL-33 must be powered independently (12V supply)

**Pros:** 
- No soldering/wiring
- Galvanic isolation via USB
- Can use existing USB cable

**Cons:**
- Requires USB hub if camera also on USB
- Another cable to manage

#### Option B: Direct Serial (Advanced)

**Requires opening SAL-33 controller box**

The SAL-33 uses an ESP32-based controller. Serial pins available:

| Pin | Function | Location |
|-----|----------|----------|
| GPIO16 | RXD2 | Aux header |
| GPIO17 | TXD2 | Aux header |

**Connection:**
```
Pi Pin 8 (TXD)  →  GPIO16 (RXD2)
Pi Pin 10 (RXD) ←  GPIO17 (TXD2)
Pi Pin 6 (GND)  →  GND
```

**Recommendation:** Use Option A (USB) unless you're comfortable modifying the controller

---

### 3. Juwei-17 (with custom OnStep controller)

**Original controller:** Chinese stock board (not LX200 compatible)

**Upgrade path:** Replace with custom OnStep-JUWEI-17 board (ESP32-based)

**If using stock controller:** Cannot connect eFinder directly - use WiFi to SkySafari instead

**If using OnStep-JUWEI-17 upgrade:**

**Board:** ESP32-Mini based (similar to SAL-33)

**Serial port options:**

| Port | Pins | Location | Default Use |
|------|------|----------|-------------|
| Serial0 | GPIO1/GPIO3 | USB bridge | PC connection |
| Serial1 | GPIO9/GPIO10 | Internal | Motor drivers |
| Serial2 | GPIO16/GPIO17 | Aux header | **Available for eFinder** |

**Physical connector:** 4-pin header on AUX/expansion area

**Connection:**
```
Pi Pin 8 (TXD)  →  GPIO16 (RXD2)
Pi Pin 10 (RXD) ←  GPIO17 (TXD2)
Pi Pin 6 (GND)  →  GND
```

**OnStepX Config.h:**
```c
#define SERIAL_C Serial2
#define SERIAL_C_BAUD_DEFAULT 9600
```

**Access:** Remove mount control panel, locate AUX header

---

## General Wiring Best Practices

### Cable Selection

**Short runs (<1ft):** DuPont jumper wires (female-female)
```
┌─────────┐         ┌─────────┐
│ Pi GPIO │═════════│ OnStep  │
└─────────┘ 3-wire  └─────────┘
            jumpers
```

**Medium runs (1-3ft):** 28AWG stranded ribbon cable with crimped connectors
```
┌─────────┐  ╔═══════════════╗  ┌─────────┐
│ Pi GPIO │══║ 3-wire ribbon ║══│ OnStep  │
└─────────┘  ╚═══════════════╝  └─────────┘
```

**Long runs (>3ft):** Not recommended - signal degradation

### Strain Relief

Mount eFinder and controller box close together. If they move independently (e.g., eFinder on scope, controller on tripod):

1. **Service loop** - leave slack for movement
2. **Cable ties** - secure at both ends but allow flex in middle
3. **Spiral wrap** - bundle with power cables

### Electrical Noise

OnStepX motor drivers generate PWM noise. To minimize interference:

1. **Twisted pair** - twist TX/RX wires together
2. **Separation** - route serial cable away from motor wires
3. **Shielded cable** - use if noise issues persist (ground shield at mount end only)

### Debugging Connection Issues

**Test serial port on Pi:**
```bash
# Loopback test - connect TX to RX with jumper
echo "test" > /dev/ttyAMA0
cat /dev/ttyAMA0
# Should echo "test" back
```

**Test OnStepX connection:**
```bash
# Install minicom
sudo apt-get install minicom

# Connect to mount
sudo minicom -D /dev/ttyAMA0 -b 9600

# Send LX200 test command
:GVN#
# Should reply with OnStep version string

# Exit: Ctrl-A, then X
```

**Common issues:**

| Problem | Cause | Fix |
|---------|-------|-----|
| No response | Wrong baudrate | Try 115200, 19200, 9600 |
| Garbage characters | TX/RX swapped | Swap wires |
| Intermittent | Loose connection | Check crimps, solder if needed |
| Works initially, fails later | Noise interference | Use twisted pair, shielded cable |

---

## Dual-Mode Configuration

**Goal:** eFinder works with serial mount OR WiFi SkySafari

### Detection Logic

```python
# In eFinder_cedar_v2.py startup
import os

if os.path.exists('/dev/ttyAMA0'):
    # Serial mount detected
    mount_mode = "SERIAL"
    mount_conn = serial.Serial('/dev/ttyAMA0', 9600)
    print("Mount: OnStepX via serial")
else:
    # No serial mount, use WiFi
    mount_mode = "WIFI"
    mount_conn = socket.socket()
    mount_conn.bind(('0.0.0.0', 4060))
    print("Mount: SkySafari via WiFi (LX200 server)")
```

### Config File Option

Add to `/home/efinder/Solver/eFinder.config`:

```ini
[mount]
# Options: AUTO, SERIAL, WIFI
mode = AUTO
serial_port = /dev/ttyAMA0
serial_baudrate = 9600
wifi_port = 4060
```

### User Selection

Add to web interface (`/index.php`):

```html
<h3>Mount Connection</h3>
<label>
  <input type="radio" name="mount_mode" value="serial" checked>
  Direct serial (OnStepX)
</label>
<label>
  <input type="radio" name="mount_mode" value="wifi">
  WiFi LX200 (SkySafari)
</label>
```

---

## Power Considerations

### Scenario 1: Independent Power

**eFinder:** USB power bank  
**Mount:** 12V battery

**Connection:** Serial only (3 wires)

**Advantage:** Galvanic isolation, no ground loops

### Scenario 2: Shared 12V Supply

**Both powered from mount's 12V battery**

**eFinder:** 12V → 5V buck converter → Pi Zero USB

**Connection:** Serial + shared ground

**Caution:** Ensure proper grounding, watch for ground loops

**Recommendation:** Use USB isolator if noise issues occur

---

## Testing Checklist

Before first light with serial connection:

- [ ] Serial port appears: `ls -l /dev/ttyAMA0`
- [ ] Baudrate correct: `stty -F /dev/ttyAMA0 9600`
- [ ] Loopback test passes (TX→RX jumper)
- [ ] OnStepX responds to `:GVN#` command
- [ ] eFinder detects mount on startup
- [ ] Plate solve updates mount coordinates
- [ ] Mount executes GoTo commands
- [ ] WiFi fallback works (disconnect serial)

---

## Summary Recommendations

| Mount | Connection Method | Complexity | Notes |
|-------|-------------------|------------|-------|
| **FYSETC S6** | Hardware UART → Serial1 (PB6/PB7) | Medium | Access UART header inside control box |
| **MLAstro SAL-33** | USB (Pi → SAL-33 USB-C) | Easy | No wiring, plug and play |
| **MLAstro SAL-33** | Hardware UART → GPIO16/17 | Hard | Requires opening controller |
| **Juwei-17 (stock)** | Not supported | N/A | Use WiFi/SkySafari instead |
| **Juwei-17 (OnStep)** | Hardware UART → GPIO16/17 | Medium | Requires OnStep upgrade first |

**Recommended approach:** Start with USB connection (SAL-33) or hardware UART (FYSETC S6). Add software serial fallback only if needed for debugging.

**Next steps:**
1. Read the software implementation guide: `ONSTEPX_IMPLEMENTATION.md`
2. Install and test without eFinder integration first
3. Add eFinder serial detection and LX200 relay
4. Test auto-track and alignment calibration features
