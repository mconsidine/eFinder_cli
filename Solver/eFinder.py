#!/usr/bin/python3

# eFinder — electronic finder scope, plate-solving over LX200/WiFi for SkySafari
# Derived from original work Copyright (C) 2025 Keith Venables (GPL v3)
# Simplified: direct picamera2, no Nexus, no GPIO, no LED, no WiFi switching

import os
import sys
import math
import socket
import time
import csv
from datetime import datetime
from threading import Thread
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from picamera2 import Picamera2
import tetra3

# ---------------------------------------------------------------------------
# Paths and startup
# ---------------------------------------------------------------------------
home_path = str(Path.home())
version   = "6.6"

# =============================================================================
# CONFIGURATION
# =============================================================================

# Set to True if an ADXL343 accelerometer is wired to the I2C bus.
# When False no accelerometer import is attempted and :GA always returns '-2'.
USE_ACCELEROMETER = False

# =============================================================================

# If invoked with an argument, kill any already-running instance first.
# (Allows manual restart from SSH without rebooting.)
if len(sys.argv) > 1:
    print('Killing running version')
    os.system('pkill -9 -f eFinder.py')

# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------
param = {}
config_path = os.path.join(home_path, "Solver/eFinder.config")
if os.path.exists(config_path):
    with open(config_path) as h:
        for line in h:
            line = line.strip("\n").split(":")
            if len(line) == 2:
                param[line[0]] = str(line[1])

def save_param():
    with open(config_path, "w") as h:
        for key, value in param.items():
            h.write("%s:%s\n" % (key, value))

# ---------------------------------------------------------------------------
# Camera  (IMX477 via picamera2, YUV420, Y-channel only)
# ---------------------------------------------------------------------------
class Camera:
    def __init__(self):
        self.picam2 = Picamera2()
        cfg = self.picam2.create_still_configuration(
            main={"size": (960, 760), "format": "YUV420"},
            sensor={"output_size": (2028, 1520)},
            buffer_count=2,
        )
        self.picam2.configure(cfg)

    def set(self, exposure_time, gain):
        exp = int(float(exposure_time) * 1_000_000)
        gn  = int(float(gain))
        self.picam2.stop()
        self.picam2.set_controls({
            "AeEnable":     False,
            "AwbEnable":    False,
            "ExposureTime": exp,
            "AnalogueGain": gn,
        })
        self.picam2.start()

    def capture(self, test=False):
        """Return Y-channel numpy array (760×960 uint8).
        If test=True and a test image exists on disk, use it instead of
        the live camera — useful for debugging over SSH without a sky view."""
        test_path = os.path.join(home_path, "Solver/test.npy")
        if test and os.path.exists(test_path):
            return np.load(test_path)
        array = np.array(self.picam2.capture_array())
        return array[0:760, 0:960]   # Y plane from YUV420

# ---------------------------------------------------------------------------
# Coordinates — inlined from Coordinates_wifi_2.py
# Newcomb first-order precession: accurate to ~1 arcminute, sufficient for
# a finder scope.  No external dependencies beyond math / datetime / os.
# ---------------------------------------------------------------------------
class Coordinates:
    def __init__(self):
        self._update_precession_constants()
        print('Coordinates ready')

    def _update_precession_constants(self):
        """Recalculate precession constants from current date."""
        now  = datetime.now()
        decY = now.year + int(now.strftime('%j')) / 365.25
        self.t = decY - 2000          # years since J2000
        self.T = self.t / 100
        self.m  = 3.07496 + 0.00186 * self.T
        self.n2 = 20.0431 - 0.0085  * self.T
        self.n1 = 1.33621 - 0.00057 * self.T

    def dateSet(self, timeOffset, timeStr, dateStr):
        """Receive date/time from SkySafari, set system clock, refresh constants."""
        days = 0
        sg   = float(timeOffset)          # hours to add to local time → UTC
        hours, minutes, seconds = timeStr.split(':')
        hours = int(hours) + sg
        if hours >= 24:
            hours = str(int(hours - 24))
            days  = 1
        elif hours < 0:
            hours = str(int(hours + 24))
            days  = -1
        else:
            hours = str(int(hours))
        timeStr = hours + ':' + minutes + ':' + seconds
        month, day, year = dateStr.split('/')
        day     = str(int(day) + days)
        dateStr = month + '/' + day + '/20' + year
        dt_str  = dateStr + ' ' + timeStr      # format: %m/%d/%Y %H:%M:%S
        print('Calculated UTC', dt_str)
        os.system('sudo date -u --set "%s"' % dt_str + '.000Z')
        self._update_precession_constants()

    def precess(self, r, d):
        """J2000 RA & Dec (decimal degrees) → JNow (decimal degrees)."""
        dR = self.m + self.n1 * math.sin(math.radians(r)) * math.tan(math.radians(d))
        dD = self.n2 * math.cos(math.radians(r))
        r  = r + dR / 240 * self.t
        d  = d + dD / 3600 * self.t
        return r, d

    def hh2dms(self, dd):
        """Decimal hours → 'HH:MM:SS' string (no sign, for LX200 RA)."""
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%02d:%02d:%02d' % (degrees, minutes, seconds)

    def dd2aligndms(self, dd):
        """Decimal degrees → '±DD*MM:SS' string (LX200 Dec format)."""
        sign             = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d*%02d:%02d' % (sign, degrees, minutes, seconds)

    def dd2dms(self, dd):
        """Decimal degrees → '±DD:MM:SS' string."""
        sign             = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d:%02d:%02d' % (sign, degrees, minutes, seconds)

coordinates = Coordinates()

# ---------------------------------------------------------------------------
# Accelerometer (optional — controlled by USE_ACCELEROMETER flag above)
# ---------------------------------------------------------------------------
altAngle = False
if USE_ACCELEROMETER:
    try:
        import board
        import adafruit_adxl34x
        i2c   = board.I2C()
        angle = adafruit_adxl34x.ADXL343(i2c)
        altAngle = True
        print('Accelerometer found')
    except Exception:
        print('Accelerometer enabled in config but not found on I2C bus')
        altAngle = False
else:
    print('Accelerometer disabled')

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
radec        = '%6.4f %+6.4f' % (0, 0)
solved_radec = (0.0, 0.0)
solve        = False
testMode     = False
stars        = peak = '0'
eTime        = '00.00'
firstStar    = None
solution     = None
capArray     = np.zeros((760, 960), dtype=np.uint8)
offset_flag  = False
offset_str   = "0,0"
keep         = False
frame        = 0

expInc = 0.1   # exposure increment per manual step (seconds)
gainInc = 5    # gain increment per manual step

fnt = ImageFont.truetype(os.path.join(home_path, "Solver/text.ttf"), 16)

# Camera field-of-view constants  (width_px, height_px, arcsec/px, fov_deg)
cam = (960, 760, 50.8, 13.5)

# ---------------------------------------------------------------------------
# Camera and Tetra3 initialisation
# Load database first — it takes minutes with a large file.
# Initialising the camera before the database load causes the V4L2 driver
# to time out waiting for captures that never come during the load period.
# ---------------------------------------------------------------------------
print('Loading Tetra3 database…')
try:
    t3 = tetra3.Tetra3('t3_fov14_mag8')
    databaseReady = True
    print('Tetra3 ready')
except FileNotFoundError:
    print('ERROR: Tetra3 database t3_fov14_mag8.npz not found.')
    print('       Run install.sh with internet access to download it.')
    t3 = None
    databaseReady = False
except Exception as e:
    print('ERROR: Tetra3 database load failed:', e)
    t3 = None
    databaseReady = False

try:
    camera = Camera()
    camera.set(float(param.get("Exposure", "0.1")), param.get("Gain", "10"))
    cameraReady = True
    print('Camera ready')
except Exception as e:
    print('ERROR: Camera initialisation failed:', e)
    print('       Check camera cable and dtoverlay=imx477 in /boot/firmware/config.txt')
    print('       Solve loop will not run without a camera.')
    camera = None
    cameraReady = False

# Restore saved offset
pix_x, pix_y = (
    float(param.get("d_x", "0")) / 60,
    float(param.get("d_y", "0")) / 60,
)
offset_str = '%1.3f,%1.3f' % (pix_x, pix_y)

def dxdy2pixel(dx, dy):
    pix_x = dx * 3600 / cam[2] + cam[0] / 2
    pix_y = cam[1] / 2 - dy * 3600 / cam[2]
    return pix_x, pix_y

def pixel2dxdy(pix_x, pix_y):
    deg_x = (float(pix_x) - cam[0] / 2) * cam[2] / 3600
    deg_y = (cam[1] / 2 - float(pix_y)) * cam[2] / 3600
    return deg_x, deg_y

_ox, _oy = dxdy2pixel(
    float(param.get("d_x", "0")) / 60,
    float(param.get("d_y", "0")) / 60,
)
offset = (_oy, _ox)
print('Offset:', offset)

# ---------------------------------------------------------------------------
# Image capture
# ---------------------------------------------------------------------------
def capture():
    global capArray
    capArray = camera.capture(test=testMode)
    return capArray

# ---------------------------------------------------------------------------
# Plate solving
# ---------------------------------------------------------------------------
def solveImage(img):
    global offset_flag, solve, eTime, firstStar, solution, stars, peak, radec, solved_radec
    start_time = time.time()
    print("Started solving")

    # img is already uint8 from the camera — use directly, no copy needed
    np_image  = img if img.dtype == np.uint8 else img.astype(np.uint8)
    # downsample=2 quarters the pixel count, ~4x faster centroid detection
    # with negligible accuracy loss for the star sizes at this focal length
    centroids = tetra3.get_centroids_from_image(np_image, downsample=2)
    print('Centroids:', len(centroids), '  Peak:', np.max(np_image))

    if len(centroids) < 15:
        print("Bad image — only %d centroids" % len(centroids))
        solve = False
        if keep:
            saveImage(img, "Bad image - %d stars    Exp=%ss  Gain=%s" % (
                len(centroids), param['Exposure'], param['Gain']))
        return

    stars = '%4d' % len(centroids)
    peak  = '%3d' % np.max(np_image)

    solution = t3.solve_from_centroids(
        centroids,
        (760, 960),
        fov_estimate=cam[3],
        fov_max_error=1,
        target_pixel=offset,
        return_matches=True,
    )

    eTime = ('%2.2f' % (time.time() - start_time)).zfill(5)

    if solution['RA'] is None:
        print("Not solved — %s stars" % stars)
        solve = False
        if keep:
            saveImage(img, "Not Solved - %s stars    Exp=%ss  Gain=%s" % (
                stars, param['Exposure'], param['Gain']))
        return

    firstStar = centroids[0]
    ra  = solution['RA_target']
    dec = solution['Dec_target']
    print('J2000', coordinates.hh2dms(ra / 15), coordinates.dd2aligndms(dec))
    ra, dec = coordinates.precess(ra, dec)

    if keep:
        saveImage(img, "Peak=%d  Stars=%d  Exp=%ss  Gain=%s" % (
            np.max(np_image), int(centroids.size),
            param['Exposure'], param['Gain']))

    radec        = '%6.4f %+6.4f' % (ra, dec)
    solved_radec = ra, dec
    print('JNow', coordinates.hh2dms(solved_radec[0] / 15),
          coordinates.dd2aligndms(solved_radec[1]))
    solve = True

# ---------------------------------------------------------------------------
# Image saving (debug / alignment frames)
# ---------------------------------------------------------------------------
def saveImage(array, txt):
    global frame, keep
    frame += 1
    img  = Image.fromarray(array)
    img2 = ImageEnhance.Contrast(img).enhance(5)
    img2 = img2.rotate(angle=180)
    d    = ImageDraw.Draw(img2)
    d.text((70, 5), txt + "      Frame %d" % frame, font=fnt, fill='white')
    img2 = ImageOps.expand(img2, border=5, fill='red')
    img2.save(os.path.join(home_path, 'Solver/images/capture.jpg'))
    if frame > 100:
        keep  = False
        frame = 0

# ---------------------------------------------------------------------------
# Continuous solve loop (runs in its own thread)
# ---------------------------------------------------------------------------
def loop_solve():
    if not cameraReady:
        print('Solve loop not started — no camera.')
        return
    if not databaseReady:
        print('Solve loop not started — database not loaded.')
        return
    while True:
        if not offset_flag:
            capture()
            solveImage(capArray)
            print('****************')
        else:
            time.sleep(0.05)   # avoid busy-spin while offset measurement runs

# ---------------------------------------------------------------------------
# Exposure / gain helpers
# ---------------------------------------------------------------------------
def selectExp(e, g):
    camera.set(e, g)
    param['Exposure'] = str(e)
    param['Gain']     = str(g)
    save_param()

def adjExp(i):
    param['Exposure'] = '%.1f' % max(0.1, float(param['Exposure']) + i * expInc)
    save_param()
    camera.set(float(param['Exposure']), param['Gain'])
    return str(param['Exposure'])

def adjGain(i):
    g = float(param['Gain']) + i * gainInc
    g = max(0, min(50, g))
    param['Gain'] = '%.1f' % g
    camera.set(float(param['Exposure']), param['Gain'])
    save_param()
    return param['Gain']

def setExp(a):
    param['Exposure'] = float(a)
    save_param()
    camera.set(float(a), param['Gain'])
    return '1'

def getAutoExp():
    if not cameraReady:
        return str(param.get('Exposure', '0.1'))
    expAuto = float(param['Exposure'])
    camera.set(expAuto, param['Gain'])
    np_image = capture()
    while True:
        pk        = np.max(np_image)
        centroids = tetra3.get_centroids_from_image(np_image, downsample=1)
        print('%4d stars  %3d peak' % (len(centroids), pk))
        if len(centroids) < 20:
            expAuto = expAuto * 2
            camera.set(expAuto, param['Gain'])
            np_image = capture()
        elif len(centroids) > 50 and pk > 250:
            expAuto = int((expAuto / 2) * 10) / 10
            camera.set(expAuto, param['Gain'])
            np_image = capture()
        else:
            break
    return str(expAuto)

# ---------------------------------------------------------------------------
# Offset measurement
# ---------------------------------------------------------------------------
def measure_offset():
    global offset_str, offset_flag, offset, param
    if not cameraReady or not databaseReady:
        return 'fail'
    offset_flag = True
    print("Started capture for offset")
    solveImage(capture())
    if not solve:
        offset_flag = False
        return "fail"
    tempExp = float(param['Exposure'])
    while float(peak) > 255:
        tempExp *= 0.75
        camera.set(tempExp, param['Gain'])
        solveImage(capture())
    if not solve:
        offset_flag = False
        return "fail"
    scope_x = firstStar[1]
    scope_y = firstStar[0]
    offset  = firstStar
    d_x, d_y = pixel2dxdy(scope_x, scope_y)
    param['d_x'] = '{: .2f}'.format(float(60 * d_x))
    param['d_y'] = '{: .2f}'.format(float(60 * d_y))
    save_param()
    offset_str = '%1.3f,%1.3f' % (d_x, d_y)
    hipId = str(solution['matched_catID'][0])
    name  = secondname = ""
    with open(os.path.join(home_path, 'Solver/starnames.csv')) as csvfile:
        for row in csv.reader(csvfile):
            if str(row[1]) == str(solution['matched_catID'][0]):
                hipId      = row[1]
                name       = row[0].strip()
                secondname = (" (" + row[2].strip() + ")") if row[2].strip() else ""
                break
    print(name + ', HIP ' + hipId)
    offset_flag = False
    return name + secondname + ',HIP' + hipId + ',' + offset_str

def go_solve():
    if not cameraReady or not databaseReady:
        return '0'
    solveImage(capture())
    return '1' if solve else '0'

def reset_offset():
    global offset, offset_str
    param['d_x'] = 0
    param['d_y'] = 0
    offset     = (cam[1] / 2, cam[0] / 2)
    offset_str = '%1.3f,%1.3f' % (0.0, 0.0)
    save_param()
    return '1'

# ---------------------------------------------------------------------------
# Altitude from accelerometer
# ---------------------------------------------------------------------------
def getScopeAlt():
    if not altAngle:
        return '-2'
    try:
        x, y, z = angle.acceleration
        if z > 0:
            return '-1'        # below horizon
        if x > 0:
            return '99'        # past zenith
        alt = -180 / math.pi * math.asin(z / 10)
        return '%2d' % alt
    except Exception:
        return '-2'

# ---------------------------------------------------------------------------
# Image saving toggle
# ---------------------------------------------------------------------------
def startImage(j):
    global keep, frame
    if j == '1':
        print('Started saving images')
        keep  = True
        frame = 0
    else:
        print('Stopped saving images')
        keep = False
    return '1'

def flipTestMode(mode):
    global testMode
    testMode = mode
    return '1'

# ---------------------------------------------------------------------------
# LX200 WiFi server  (SkySafari connects here on port 4060)
# ---------------------------------------------------------------------------
def serveWifi():
    global solved_radec, keep, frame
    print('Starting WiFi/LX200 server on port 4060')
    host    = ''
    port    = 4060
    size    = 1024
    s       = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(50)
    raStr = decStr = ""
    timeOffset = '0'
    timeStr    = '23:00:00'

    while True:
        try:
            client, address = s.accept()
            print('SkySafari connected from', address)
            while True:
                data = client.recv(size)
                if not data:
                    break
                pkt = data.decode("utf-8", "ignore")
                time.sleep(0.02)
                raPacket  = coordinates.hh2dms(solved_radec[0] / 15) + '#'
                decPacket = coordinates.dd2aligndms(solved_radec[1]) + '#'
                for x in pkt.split('#'):
                    if not x:
                        continue
                    cmd = x[1:3]
                    if   x == ':GR':
                        client.send(raPacket.encode('ascii'))
                    elif x == ':GD':
                        client.send(decPacket.encode('ascii'))
                    elif cmd == 'St':
                        client.send(b'1')
                        lat = x[3:].split('*')
                        # Latitude as decimal degrees North +ve
                        Lat = int(lat[0]) + int(lat[1]) / 60
                    elif cmd == 'Sg':
                        client.send(b'1')
                        lon = x[3:].split('*')
                        # Longitude as decimal degrees West +ve
                        Long = int(lon[0]) + int(lon[1]) / 60
                    elif cmd == 'SG':
                        client.send(b'1')
                        timeOffset = x[3:]
                    elif cmd == 'SL':
                        client.send(b'1')
                        timeStr = x[3:]
                    elif cmd == 'SC':
                        client.send(b'Updating Planetary Data#                              #')
                        print('dateSet', timeOffset, timeStr, x[3:])
                        coordinates.dateSet(timeOffset, timeStr, x[3:])
                    elif cmd == 'RG':   # minimum exposure/gain
                        selectExp(0.1, 10)
                    elif cmd == 'RC':   # medium exposure/gain
                        selectExp(0.1, 20)
                    elif cmd == 'RM':   # high exposure/gain
                        selectExp(0.2, 20)
                    elif cmd == 'RS':   # very high exposure/gain
                        selectExp(0.5, 30)
                    elif cmd == 'Sr':   # target RA
                        raStr = x[3:]
                        client.send(b'1')
                    elif cmd == 'Sd':   # target Dec
                        decStr = x[3:]
                        client.send(b'1')
                    elif cmd == 'MS':   # goto (not implemented — acknowledge only)
                        client.send(b'0')
                    elif cmd == 'Ms':
                        adjExp(-1)
                    elif cmd == 'Mn':
                        adjExp(1)
                    elif cmd == 'Mw':
                        keep  = False
                        frame = 0
                    elif cmd == 'Me':
                        print('Started saving images')
                        keep = True
                    elif cmd == 'CM':   # measure offset
                        client.send(b'0')
                        measure_offset()
                        ra  = raStr.split(':')
                        targetRa = int(ra[0]) + int(ra[1]) / 60 + int(ra[2]) / 3600
                        dec = decStr.split('*')
                        decdec = dec[1].split(':')
                        targetDec = int(dec[0]) + math.copysign(
                            int(decdec[0]) / 60 + int(decdec[1]) / 3600,
                            float(dec[0]))
                        print('Align target:', targetRa, targetDec)
                    elif x and x[-1] == 'Q':
                        print('Stop saving images')
                        keep = False
                    # ----------------------------------------------------------
                    # Diagnostic / tuning commands (formerly Nexus-only).
                    # These are not sent by SkySafari but are available to any
                    # TCP client on port 4060 — useful for setup and debugging.
                    # ----------------------------------------------------------
                    elif cmd == 'PS':   # on-demand plate solve
                        client.send((':PS' + go_solve() + '#').encode('ascii'))
                    elif cmd == 'OF':   # measure offset, return star name
                        client.send((':OF' + measure_offset() + '#').encode('ascii'))
                    elif cmd == 'GV':   # get version
                        client.send((':GV' + version + '#').encode('ascii'))
                    elif cmd == 'GO':   # get current offset string
                        client.send((':GO' + offset_str + '#').encode('ascii'))
                    elif cmd == 'SO':   # reset offset to image centre
                        client.send((':SO' + reset_offset() + '#').encode('ascii'))
                    elif cmd == 'GS':   # get star count from last solve
                        client.send((':GS' + str(stars) + '#').encode('ascii'))
                    elif cmd == 'GK':   # get peak pixel value from last solve
                        client.send((':GK' + str(peak) + '#').encode('ascii'))
                    elif cmd == 'Gt':   # get elapsed solve time
                        client.send((':Gt' + eTime + '#').encode('ascii'))
                    elif cmd == 'SE':   # adjust exposure (+1 or -1 step)
                        client.send((':SE' + adjExp(float(x[3:5])) + '#').encode('ascii'))
                    elif cmd == 'SG':   # adjust gain (+1 or -1 step)
                        # Note: SG is also used by LX200 for UTC offset — that
                        # variant arrives as ':SG<offset>' with a sign character
                        # at position 3, so distinguish by content length.
                        if len(x) <= 5:
                            client.send((':SG' + adjGain(float(x[3:5])) + '#').encode('ascii'))
                        else:
                            # LX200 UTC offset form — already handled above as 'SG'
                            pass
                    elif cmd == 'SX':   # set absolute exposure value
                        client.send((':SX' + setExp(x.strip('#')[3:]) + '#').encode('ascii'))
                    elif cmd == 'GX':   # auto-expose
                        client.send((':GX' + getAutoExp() + '#').encode('ascii'))
                    elif cmd == 'GA':   # get scope altitude from accelerometer
                        client.send((':GA' + getScopeAlt() + '#').encode('ascii'))
                    elif cmd == 'IM':   # start/stop image saving
                        client.send((':IM' + startImage(x.strip('#')[3:4]) + '#').encode('ascii'))
                    elif cmd == 'TS':   # enable test mode
                        client.send((':TS' + flipTestMode(True) + '#').encode('ascii'))
                    elif cmd == 'TO':   # disable test mode
                        client.send((':TO' + flipTestMode(False) + '#').encode('ascii'))
            print('SkySafari disconnected')
        except Exception as e:
            print('WiFi server error:', e)
            print('Restarting WiFi server socket…')
            try:
                s.close()
            except Exception:
                pass
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.listen(50)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print('eFinder version', version)
print('Camera  :', 'OK' if cameraReady    else 'NOT AVAILABLE — solve loop disabled')
print('Database:', 'OK' if databaseReady  else 'NOT FOUND — solve loop disabled')
print('Accel   :', 'OK' if altAngle       else 'not fitted')
print('')
print('Starting solve loop…')
solveloop = Thread(target=loop_solve, daemon=True)
solveloop.start()
time.sleep(0.5)

print('Starting WiFi/LX200 server…')
wifiloop = Thread(target=serveWifi, daemon=True)
wifiloop.start()
time.sleep(0.5)

print('eFinder running — waiting for SkySafari connection on port 4060')

# Main thread: nothing left to do — keep alive so daemon threads stay up
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print('eFinder stopped.')
