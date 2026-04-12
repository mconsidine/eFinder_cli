#!/usr/bin/python3

# eFinder — electronic finder scope, plate-solving over LX200/WiFi for SkySafari
# Derived from original work Copyright (C) 2025 Keith Venables (GPL v3)
# Simplified: direct picamera2, no Nexus, no GPIO, no LED, no WiFi switching
#
# Cedar edition v2:
#   - Fully offline — no internet required at any boot.
#   - Star detection: cedar-detect (Rust gRPC microservice, pre-built in image)
#   - Plate solving: cedar-solve (pre-installed in image venv)
#   - Database: t3_fov14_mag8.npz pre-generated in image
#   - gRPC stubs: pre-compiled into ~/Solver/ in image
#
# The cedar-detect-server systemd unit starts before this script.
# It listens on localhost:50051.
#
# Mount integration (optional):
#   Scenario A — no mount:
#     Pi runs LX200 server on port 4060; SkySafari connects to Pi directly.
#   Scenario B — OnStepX/FYSETC E4 mount via WiFi:
#     Pi connects to mount on port 9999 and syncs after each solve.
#     SkySafari connects to mount on port 9998.
#     Pi's port-4060 LX200 server stays running as fallback.
#   Scenario C — other mount via serial:
#     Pi connects to /dev/ttyAMA0 (or configured port) and syncs after each solve.
#     SkySafari continues to connect to Pi on port 4060.
#
#   To enable mount integration add to ~/Solver/eFinder.config:
#     mount_mode:wifi        (wifi | serial | none)
#     mount_host:192.168.0.1 (wifi only — IP of OnStepX controller)
#     mount_port:9999        (wifi only — port on OnStepX, default 9999)
#     mount_serial:/dev/ttyAMA0  (serial only)
#     mount_baud:9600            (serial only)

import os
import sys
import math
import socket
import serial as pyserial
import time
import csv
from datetime import datetime
from threading import Thread, Lock
from pathlib import Path

import numpy as np
import grpc
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from picamera2 import Picamera2
import tetra3  # cedar-solve installs as the 'tetra3' module

# ---------------------------------------------------------------------------
# Paths and startup
# ---------------------------------------------------------------------------
home_path = str(Path.home())
version   = "6.6-cedar-v2"

# ---------------------------------------------------------------------------
# Feature flags
# Set USE_ACCELEROMETER = True only if an ADXL343/345 is physically wired
# to the I2C bus. When False the adafruit-circuitpython-adxl34x package
# and all of its dependencies (adafruit-blinka, platformdetect, etc.) are
# not imported, saving ~10 pip wheels and significant runtime memory.
# getScopeAlt() returns "-2" (unknown) when the flag is False.
# ---------------------------------------------------------------------------
USE_ACCELEROMETER = False

# Solver/ contains the pre-compiled gRPC stubs and the star database.
solver_path = os.path.join(home_path, "Solver")
if solver_path not in sys.path:
    sys.path.insert(0, solver_path)

import cedar_detect_pb2
import cedar_detect_pb2_grpc

if len(sys.argv) > 1:
    print('Killing running version')
    os.system('pkill -9 -f eFinder_cedar_v2.py')

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
# Cedar-detect gRPC client
# ---------------------------------------------------------------------------
CEDAR_DETECT_ADDR = "localhost:50051"

def _make_detect_channel():
    return grpc.insecure_channel(CEDAR_DETECT_ADDR)

_detect_channel  = _make_detect_channel()
_detect_stub     = cedar_detect_pb2_grpc.CedarDetectStub(_detect_channel)

def get_centroids_cedar(np_image: np.ndarray) -> np.ndarray:
    """Call cedar-detect gRPC server; return (N,2) array of (row,col) centroids.

    cedar-detect 0.8.0 API:
      Request:  CentroidsRequest
                  input_image: Image(width, height, image_data)
                  sigma, detect_hot_pixels (optional tuning)
      Method:   ExtractCentroids
      Response: CentroidsResult
                  star_candidates[]: StarCentroid
                    centroid_position: ImageCoord(x=col, y=row)
                    brightness, num_saturated
                  noise_estimate, peak_star_pixel
    """
    global _detect_channel, _detect_stub

    assert np_image.dtype == np.uint8
    h, w = np_image.shape

    image = cedar_detect_pb2.Image(
        width=w,
        height=h,
        image_data=np_image.tobytes(),
    )
    request = cedar_detect_pb2.CentroidsRequest(
        input_image=image,
        sigma=8.0,
        detect_hot_pixels=True,
    )

    try:
        response = _detect_stub.ExtractCentroids(request, timeout=10.0)
    except grpc.RpcError as e:
        print("cedar-detect gRPC error:", e.code(), e.details())
        print("Attempting to reconnect cedar-detect channel...")
        try:
            _detect_channel.close()
        except Exception:
            pass
        _detect_channel = _make_detect_channel()
        _detect_stub    = cedar_detect_pb2_grpc.CedarDetectStub(_detect_channel)
        return np.empty((0, 2), dtype=np.float64)

    # cedar-detect returns centroid_position.{x=col, y=row};
    # tetra3 expects (row, col) order, brightest-first.
    centroids = np.array(
        [(s.centroid_position.y, s.centroid_position.x)
         for s in response.star_candidates],
        dtype=np.float64,
    )
    return centroids

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
        test_path = os.path.join(home_path, "Solver/test.npy")
        if test and os.path.exists(test_path):
            return np.load(test_path)
        array = np.array(self.picam2.capture_array())
        return array[0:760, 0:960]

# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------
class Coordinates:
    def __init__(self):
        self._update_precession_constants()
        print('Coordinates ready')

    def _update_precession_constants(self):
        now  = datetime.now()
        decY = now.year + int(now.strftime('%j')) / 365.25
        self.t = decY - 2000
        self.T = self.t / 100
        self.m  = 3.07496 + 0.00186 * self.T
        self.n2 = 20.0431 - 0.0085  * self.T
        self.n1 = 1.33621 - 0.00057 * self.T

    def dateSet(self, timeOffset, timeStr, dateStr):
        days = 0
        sg   = float(timeOffset)
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
        dt_str  = dateStr + ' ' + timeStr
        print('Calculated UTC', dt_str)
        os.system('sudo date -u --set "%s"' % dt_str + '.000Z')
        self._update_precession_constants()

    def precess(self, r, d):
        dR = self.m + self.n1 * math.sin(math.radians(r)) * math.tan(math.radians(d))
        dD = self.n2 * math.cos(math.radians(r))
        r  = r + dR / 240 * self.t
        d  = d + dD / 3600 * self.t
        return r, d

    def hh2dms(self, dd):
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%02d:%02d:%02d' % (degrees, minutes, seconds)

    def dd2aligndms(self, dd):
        sign             = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d*%02d:%02d' % (sign, degrees, minutes, seconds)

    def dd2dms(self, dd):
        sign             = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d:%02d:%02d' % (sign, degrees, minutes, seconds)

coordinates = Coordinates()

# ---------------------------------------------------------------------------
# Accelerometer (optional ADXL343 on I2C1 — pins 3/SDA and 5/SCL)
#
# USE_ACCELEROMETER = False at startup — no hardware assumed present.
# Can be enabled at runtime via the web status page toggle button which
# calls enable_accelerometer() / disable_accelerometer() below.
# The packages (adafruit-blinka, adafruit-circuitpython-adxl34x) are
# pre-installed in the image so no rebuild is needed to use this feature.
# ---------------------------------------------------------------------------
altAngle = False
angle    = None

def enable_accelerometer():
    """Attempt to initialise the ADXL343 on I2C1. Returns True on success."""
    global altAngle, angle
    try:
        import board
        import adafruit_adxl34x
        i2c   = board.I2C()
        angle = adafruit_adxl34x.ADXL343(i2c)
        altAngle = True
        print('Accelerometer enabled')
        return True
    except Exception as e:
        print('Accelerometer init failed:', e)
        altAngle = False
        angle    = None
        return False

def disable_accelerometer():
    """Disable accelerometer — getScopeAlt() returns -2 (unknown)."""
    global altAngle, angle
    altAngle = False
    angle    = None
    print('Accelerometer disabled')

if USE_ACCELEROMETER:
    enable_accelerometer()
else:
    print('Accelerometer disabled (USE_ACCELEROMETER = False)')

# ---------------------------------------------------------------------------
# Mount connection (optional)
#
# Reads mount_mode from eFinder.config:
#   none   — no mount, Pi serves SkySafari directly on port 4060 (default)
#   wifi   — OnStepX over TCP (FYSETC E4 or similar)
#            Pi → mount_host:mount_port (default 9999)
#            SkySafari → mount on port 9998
#   serial — any LX200-compatible mount over serial
#            Pi → mount_serial at mount_baud (default /dev/ttyAMA0 @ 9600)
#            SkySafari → Pi on port 4060 as today
#
# In all cases the Pi's port-4060 LX200 server keeps running as fallback.
# Mount sync is fire-and-forget — a failure never blocks the solve loop.
# ---------------------------------------------------------------------------
MOUNT_MODE   = param.get('mount_mode', 'none').lower().strip()
MOUNT_HOST   = param.get('mount_host', '192.168.0.1').strip()
MOUNT_PORT   = int(param.get('mount_port', '9999'))
MOUNT_SERIAL = param.get('mount_serial', '/dev/ttyAMA0').strip()
MOUNT_BAUD   = int(param.get('mount_baud', '9600'))

_mount_lock      = Lock()   # serialises all LX200 commands to the mount
_mount_wifi_sock = None     # TCP socket (wifi mode)
_mount_serial    = None     # serial.Serial object (serial mode)


def _format_lx200_ra(ra_deg):
    """Convert RA in degrees to LX200 HH:MM:SS string."""
    ra_h   = (ra_deg / 15.0) % 24.0
    hh     = int(ra_h)
    mm     = int((ra_h - hh) * 60)
    ss     = int(((ra_h - hh) * 60 - mm) * 60)
    return '%02d:%02d:%02d' % (hh, mm, ss)


def _format_lx200_dec(dec_deg):
    """Convert Dec in degrees to LX200 ±DD*MM:SS string."""
    sign   = '+' if dec_deg >= 0 else '-'
    d      = abs(dec_deg)
    dd     = int(d)
    mm     = int((d - dd) * 60)
    ss     = int(((d - dd) * 60 - mm) * 60)
    return '%s%02d*%02d:%02d' % (sign, dd, mm, ss)


def _lx200_send_wifi(sock, cmd, expect_response=True):
    """Send one LX200 command over TCP and return the response (or '')."""
    try:
        sock.sendall(cmd.encode('ascii'))
        if expect_response:
            return sock.recv(64).decode('ascii', errors='ignore')
    except Exception:
        pass
    return ''


def _lx200_send_serial(ser, cmd):
    """Send one LX200 command over serial and return the response (or '')."""
    try:
        ser.reset_input_buffer()
        ser.write(cmd.encode('ascii'))
        response = b''
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if ser.in_waiting:
                ch = ser.read(1)
                response += ch
                if ch in (b'#', b'0', b'1'):
                    break
        return response.decode('ascii', errors='ignore').rstrip('#')
    except Exception:
        return ''


def _try_connect_mount():
    """Attempt to open the mount connection. Returns True on success."""
    global _mount_wifi_sock, _mount_serial

    if MOUNT_MODE == 'none':
        return False

    if MOUNT_MODE == 'wifi':
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect((MOUNT_HOST, MOUNT_PORT))
            s.settimeout(1.0)
            # Quick sanity-check — ask for firmware version
            s.sendall(b':GVN#')
            ver = s.recv(64).decode('ascii', errors='ignore')
            _mount_wifi_sock = s
            print('Mount (WiFi) connected: %s:%d  firmware=%s' % (
                MOUNT_HOST, MOUNT_PORT, ver.strip('#')))
            return True
        except Exception as e:
            print('Mount (WiFi) not reachable: %s — running without mount sync' % e)
            _mount_wifi_sock = None
            return False

    if MOUNT_MODE == 'serial':
        try:
            ser = pyserial.Serial(
                port=MOUNT_SERIAL, baudrate=MOUNT_BAUD,
                timeout=1.0, write_timeout=1.0)
            ser.reset_input_buffer()
            ser.write(b':GVN#')
            time.sleep(0.2)
            ver = ser.read(ser.in_waiting or 1).decode('ascii', errors='ignore')
            _mount_serial = ser
            print('Mount (serial) connected: %s @ %d  firmware=%s' % (
                MOUNT_SERIAL, MOUNT_BAUD, ver.strip('#')))
            return True
        except Exception as e:
            print('Mount (serial) not available: %s — running without mount sync' % e)
            _mount_serial = None
            return False

    print('Unknown mount_mode "%s" — running without mount sync' % MOUNT_MODE)
    return False


def _mount_connected():
    if MOUNT_MODE == 'wifi':
        return _mount_wifi_sock is not None
    if MOUNT_MODE == 'serial':
        return _mount_serial is not None
    return False


def push_to_mount(ra_deg, dec_deg):
    """
    Sync the mount to the plate-solved position.  Fire-and-forget — any
    failure is logged but never propagates to the solve loop.

    LX200 sync sequence:
      :SrHH:MM:SS#   — set target RA
      :Sd±DD*MM:SS#  — set target Dec
      :CM#           — sync (Calibrate Mount)

    The mount updates its internal pointing model to treat the current
    position as (ra_deg, dec_deg).  The telescope does not move.
    """
    global _mount_wifi_sock, _mount_serial

    if not _mount_connected():
        return

    ra_str  = _format_lx200_ra(ra_deg)
    dec_str = _format_lx200_dec(dec_deg)

    with _mount_lock:
        try:
            if MOUNT_MODE == 'wifi':
                _lx200_send_wifi(_mount_wifi_sock, ':Sr%s#' % ra_str)
                _lx200_send_wifi(_mount_wifi_sock, ':Sd%s#' % dec_str)
                _lx200_send_wifi(_mount_wifi_sock, ':CM#')
                print('Mount synced (WiFi): RA=%s Dec=%s' % (ra_str, dec_str))

            elif MOUNT_MODE == 'serial':
                _lx200_send_serial(_mount_serial, ':Sr%s#' % ra_str)
                _lx200_send_serial(_mount_serial, ':Sd%s#' % dec_str)
                _lx200_send_serial(_mount_serial, ':CM#')
                print('Mount synced (serial): RA=%s Dec=%s' % (ra_str, dec_str))

        except Exception as e:
            print('Mount sync failed: %s — attempting reconnect' % e)
            # Close and attempt reconnect for next solve
            try:
                if MOUNT_MODE == 'wifi' and _mount_wifi_sock:
                    _mount_wifi_sock.close()
                elif MOUNT_MODE == 'serial' and _mount_serial:
                    _mount_serial.close()
            except Exception:
                pass
            _mount_wifi_sock = None
            _mount_serial    = None
            # Reconnect in background so the solve loop is not delayed
            Thread(target=_try_connect_mount, daemon=True).start()


# Attempt initial mount connection at startup
if MOUNT_MODE != 'none':
    _try_connect_mount()

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
radec        = '%6.4f %+6.4f' % (0, 0)
solved_radec = (0.0, 0.0)
solved_roll  = 0.0
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

expInc  = 0.1
gainInc = 5

fnt = ImageFont.truetype(os.path.join(home_path, "Solver/text.ttf"), 16)
cam = (960, 760, 50.8, 13.5)

# ---------------------------------------------------------------------------
# FOV calibration
#
# cam[3] = 13.5 degrees is the design estimate for the IMX477 + lens.
# After enough successful solves the actual FOV is averaged and saved to
# eFinder.config as 'fov_measured'.  Subsequent startups use this value
# which also allows fov_max_error to be tightened for faster solving.
# ---------------------------------------------------------------------------
_fov_samples    = []          # rolling buffer of per-solve FOV measurements
_FOV_SAMPLE_MIN = 5           # solves needed before trusting the average
_FOV_SAMPLE_MAX = 20          # keep last N samples (discards oldest)

# Load previously measured FOV from config if available
_fov_measured = float(param.get('fov_measured', '0'))
if _fov_measured > 0:
    print('Using measured FOV from config: %.3f degrees' % _fov_measured)
else:
    _fov_measured = 0.0  # 0 means uncalibrated — use estimate

# ---------------------------------------------------------------------------
# Camera and cedar-solve initialisation
# ---------------------------------------------------------------------------
camera = Camera()
camera.set(float(param.get("Exposure", "0.1")), param.get("Gain", "10"))

print('Loading cedar-solve database...')
t3 = tetra3.Tetra3('t3_fov14_mag8')
print('cedar-solve ready')

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
# Maximum centroids passed to tetra3. Cedar-detect returns stars
# brightness-sorted so we keep only the brightest N. Tetra3's
# combination count grows factorially — capping at 30 gives a
# ~50-80% solve time reduction with no loss of reliability.
MAX_CENTROIDS = 30

def solveImage(img):
    global offset_flag, solve, eTime, firstStar, solution, stars, peak, radec, solved_radec
    start_time = time.time()
    print("Started solving")

    np_image = img if img.dtype == np.uint8 else img.astype(np.uint8)
    centroids = get_centroids_cedar(np_image)
    img_peak  = int(np.max(np_image))
    print('Centroids (cedar):', len(centroids), '  Peak:', img_peak)

    if len(centroids) < 15:
        print("Bad image — only %d centroids" % len(centroids))
        solve = False
        if keep:
            saveImage(img, "Bad image - %d stars    Exp=%ss  Gain=%s" % (
                len(centroids), param['Exposure'], param['Gain']))
        return

    # Cap centroids — already brightness-sorted by cedar-detect.
    if len(centroids) > MAX_CENTROIDS:
        centroids = centroids[:MAX_CENTROIDS]

    stars = '%4d' % len(centroids)
    peak  = '%3d' % img_peak

    # Use prior solve as a position hint when available.
    # A seeded solve searches only a small sky patch rather than
    # the whole sky — typically 5-10x faster than a blind solve.
    # If the seeded solve fails we fall back to a blind solve so
    # large slews or first-light always recover automatically.
    _fov_est, _fov_err = get_fov_estimate()
    solve_kwargs = dict(
        fov_estimate=_fov_est,
        fov_max_error=_fov_err,
        target_pixel=offset,
        return_matches=True,
    )
    if solve and solved_radec != (0.0, 0.0):
        solve_kwargs['ra_dec_center'] = (solved_radec[0], solved_radec[1])
        solve_kwargs['search_radius'] = 8.0  # degrees — wider than FOV

    solution = t3.solve_from_centroids(
        centroids,
        (760, 960),
        **solve_kwargs,
    )

    # If seeded solve failed, retry blind before giving up.
    if solution['RA'] is None and 'ra_dec_center' in solve_kwargs:
        print("Seeded solve failed — retrying blind")
        blind_kwargs = {k: v for k, v in solve_kwargs.items()
                        if k not in ('ra_dec_center', 'search_radius')}
        solution = t3.solve_from_centroids(
            centroids,
            (760, 960),
            **blind_kwargs,
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
    roll = solution.get('Roll', 0.0)
    print('J2000', coordinates.hh2dms(ra / 15), coordinates.dd2aligndms(dec),
          'Roll %.1f' % roll)
    ra, dec = coordinates.precess(ra, dec)

    # Accumulate FOV measurement from this solve
    _update_fov_calibration(solution.get('FOV'))

    if keep:
        saveImage(img, "Peak=%d  Stars=%d  Exp=%ss  Gain=%s" % (
            img_peak, len(centroids), param['Exposure'], param['Gain']))

    radec        = '%6.4f %+6.4f' % (ra, dec)
    solved_radec = ra, dec
    solved_roll  = roll
    print('JNow', coordinates.hh2dms(solved_radec[0] / 15),
          coordinates.dd2aligndms(solved_radec[1]))
    solve = True
    _write_state()

    # Push solved position to mount immediately after each successful solve.
    # Fire-and-forget — runs in a daemon thread so the solve loop is not
    # delayed if the mount is slow to respond or temporarily unreachable.
    if _mount_connected():
        Thread(target=push_to_mount,
               args=(solved_radec[0], solved_radec[1]),
               daemon=True).start()

# ---------------------------------------------------------------------------
# FOV calibration — accumulate measured FOV from each solve
# ---------------------------------------------------------------------------
def _update_fov_calibration(fov_deg):
    """Add a FOV measurement, update running average, save when stable."""
    global _fov_samples, _fov_measured
    if fov_deg is None or fov_deg <= 0:
        return
    _fov_samples.append(fov_deg)
    if len(_fov_samples) > _FOV_SAMPLE_MAX:
        _fov_samples.pop(0)
    if len(_fov_samples) < _FOV_SAMPLE_MIN:
        return
    avg = sum(_fov_samples) / len(_fov_samples)
    # Only save if meaningfully different from stored value (avoids constant writes)
    if abs(avg - _fov_measured) > 0.05:
        _fov_measured = avg
        param['fov_measured'] = '%.4f' % avg
        save_param()
        print('FOV calibrated: %.3f degrees (avg of %d solves)' % (avg, len(_fov_samples)))

def get_fov_estimate():
    """Return best available FOV estimate and appropriate max_error tolerance."""
    if _fov_measured > 0 and len(_fov_samples) >= _FOV_SAMPLE_MIN:
        return _fov_measured, 0.3   # tight tolerance once calibrated
    return cam[3], 1.0              # loose tolerance while uncalibrated

# ---------------------------------------------------------------------------
# State file — written after every successful solve so the web interface
# can display current status without polling the Python process directly.
# Written to /dev/shm (RAM) to avoid SD card wear.
# ---------------------------------------------------------------------------
import json as _json

def _write_state():
    """Write current solver state to /dev/shm/efinder_state.json."""
    try:
        # CPU temperature
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as _f:
                cpu_temp = int(_f.read()) / 1000.0
        except Exception:
            cpu_temp = 0.0

        # Memory usage (RSS of this process in MB)
        try:
            with open('/proc/self/status') as _f:
                mem_kb = next(l for l in _f if l.startswith('VmRSS:'))
            memory_mb = int(mem_kb.split()[1]) // 1024
        except Exception:
            memory_mb = 0

        # WiFi mode and IP
        try:
            import subprocess as _sp
            _ip = _sp.check_output(['hostname', '-I'],
                                   text=True, timeout=2).split()[0]
        except Exception:
            _ip = ''

        state = {
            'ra':              solved_radec[0] / 15.0,  # hours
            'dec':             solved_radec[1],
            'solve_status':    'Solved' if solve else 'No solve',
            'solve_timestamp': int(time.time()),
            'stars':           stars,
            'peak':            peak,
            'exposure':        param.get('Exposure', '?'),
            'gain':            param.get('Gain', '?'),
            'solve_time':      eTime,
            'solve_duration':  int(float(eTime) * 1000) if eTime else 0,
            'mount_mode':      MOUNT_MODE,
            'mount_connected': _mount_connected(),
            'version':         version,
            'fov_measured':    round(_fov_measured, 3) if _fov_measured > 0 else None,
            'fov_samples':     len(_fov_samples),
            'roll':            round(solved_roll, 2),
            'rmse_arcsec':     round(float(solution['RMSE']), 2) if solution and solution.get('RMSE') else None,
            'cpu_temp':        round(cpu_temp, 1),
            'memory_usage':    memory_mb,
            'ip_address':      _ip,
            'accelerometer':   altAngle,
        }
        with open('/dev/shm/efinder_state.json', 'w') as f:
            _json.dump(state, f)
    except Exception as e:
        print('State write failed:', e)

# ---------------------------------------------------------------------------
# Live view image — always written so stream.php has a current frame
# regardless of whether image saving (keep) is active.
# ---------------------------------------------------------------------------
def _write_live_image(array):
    """Write current capture to images/capture.jpg for live view."""
    try:
        os.makedirs(os.path.join(home_path, 'Solver/images'), exist_ok=True)
        img  = Image.fromarray(array)
        img2 = ImageEnhance.Contrast(img).enhance(5)
        img2 = img2.rotate(angle=180)
        if solve and solution is not None:
            d = ImageDraw.Draw(img2)
            d.text((5, 5), 'RA %s  Dec %s  Stars %s  %.2fs' % (
                coordinates.hh2dms(solved_radec[0] / 15),
                coordinates.dd2aligndms(solved_radec[1]),
                stars, float(eTime)), font=fnt, fill='white')
        # Write to RAM (/dev/shm) to avoid SD card wear and latency.
        # stream.php reads from this path.
        img2.save('/dev/shm/efinder_live.jpg')
    except Exception as e:
        print('Live image write failed:', e)

# ---------------------------------------------------------------------------
# Image saving
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
# Continuous solve loop
# ---------------------------------------------------------------------------
def loop_solve():
    while True:
        if not offset_flag:
            capture()
            solveImage(capArray)
            _write_live_image(capArray)
            print('****************')
        else:
            time.sleep(0.05)

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
    expAuto = float(param['Exposure'])
    camera.set(expAuto, param['Gain'])
    np_image = capture()
    max_iter = 20
    for _ in range(max_iter):
        pk        = int(np.max(np_image))
        centroids = get_centroids_cedar(np_image)
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
            return '-1'
        if x > 0:
            return '99'
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
# LX200 WiFi server (SkySafari interface — always runs on port 4060)
#
# In Scenario A (no mount) this is the primary interface.
# In Scenario B (OnStepX WiFi) SkySafari connects to the mount directly on
#   port 9998; this server stays running as a fallback.
# In Scenario C (serial mount) SkySafari connects here as today.
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
                        Lat = int(lat[0]) + int(lat[1]) / 60
                    elif cmd == 'Sg':
                        client.send(b'1')
                        lon = x[3:].split('*')
                        Long = int(lon[0]) + int(lon[1]) / 60
                    elif cmd == 'SG':
                        if len(x) > 5:
                            client.send(b'1')
                            timeOffset = x[3:]
                        else:
                            client.send((':SG' + adjGain(float(x[3:5])) + '#').encode('ascii'))
                    elif cmd == 'SL':
                        client.send(b'1')
                        timeStr = x[3:]
                    elif cmd == 'SC':
                        client.send(b'Updating Planetary Data#                              #')
                        print('dateSet', timeOffset, timeStr, x[3:])
                        coordinates.dateSet(timeOffset, timeStr, x[3:])
                    elif cmd == 'RG':
                        selectExp(0.1, 10)
                    elif cmd == 'RC':
                        selectExp(0.1, 20)
                    elif cmd == 'RM':
                        selectExp(0.2, 20)
                    elif cmd == 'RS':
                        selectExp(0.5, 30)
                    elif cmd == 'Sr':
                        raStr = x[3:]
                        client.send(b'1')
                    elif cmd == 'Sd':
                        decStr = x[3:]
                        client.send(b'1')
                    elif cmd == 'MS':
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
                    elif cmd == 'CM':
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
                    elif cmd == 'PS':
                        client.send((':PS' + go_solve() + '#').encode('ascii'))
                    elif cmd == 'OF':
                        client.send((':OF' + measure_offset() + '#').encode('ascii'))
                    elif cmd == 'GV':
                        client.send((':GV' + version + '#').encode('ascii'))
                    elif cmd == 'GO':
                        client.send((':GO' + offset_str + '#').encode('ascii'))
                    elif cmd == 'SO':
                        client.send((':SO' + reset_offset() + '#').encode('ascii'))
                    elif cmd == 'GS':
                        client.send((':GS' + str(stars) + '#').encode('ascii'))
                    elif cmd == 'GK':
                        client.send((':GK' + str(peak) + '#').encode('ascii'))
                    elif cmd == 'Gt':
                        client.send((':Gt' + eTime + '#').encode('ascii'))
                    elif cmd == 'SE':
                        client.send((':SE' + adjExp(float(x[3:5])) + '#').encode('ascii'))
                    elif cmd == 'SX':
                        client.send((':SX' + setExp(x.strip('#')[3:]) + '#').encode('ascii'))
                    elif cmd == 'GX':
                        client.send((':GX' + getAutoExp() + '#').encode('ascii'))
                    elif cmd == 'GA':
                        client.send((':GA' + getScopeAlt() + '#').encode('ascii'))
                    elif cmd == 'IM':
                        client.send((':IM' + startImage(x.strip('#')[3:4]) + '#').encode('ascii'))
                    elif cmd == 'TS':
                        client.send((':TS' + flipTestMode(True) + '#').encode('ascii'))
                    elif cmd == 'TO':
                        client.send((':TO' + flipTestMode(False) + '#').encode('ascii'))
                    elif cmd == 'AC':
                        result = '1' if enable_accelerometer() else '0'
                        client.send((':AC' + result + '#').encode('ascii'))
                    elif cmd == 'AD':
                        disable_accelerometer()
                        client.send((':AD1#').encode('ascii'))
                    elif cmd == 'AG':
                        # Get accelerometer state: 1=enabled, 0=disabled
                        client.send((':AG' + ('1' if altAngle else '0') + '#').encode('ascii'))
            print('SkySafari disconnected')
        except Exception as e:
            print('WiFi server error:', e)
            print('Restarting WiFi server socket...')
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
print('cedar-detect server expected at', CEDAR_DETECT_ADDR)
print('Mount mode: %s' % MOUNT_MODE)
if MOUNT_MODE == 'wifi':
    print('  Mount host: %s:%d' % (MOUNT_HOST, MOUNT_PORT))
    print('  SkySafari: connect to mount on port 9998')
elif MOUNT_MODE == 'serial':
    print('  Mount serial: %s @ %d baud' % (MOUNT_SERIAL, MOUNT_BAUD))
    print('  SkySafari: connect to this device on port 4060')
else:
    print('  SkySafari: connect to this device on port 4060')

print('Starting solve loop...')
solveloop = Thread(target=loop_solve, daemon=True)
solveloop.start()
time.sleep(0.5)

print('Starting WiFi/LX200 server on port 4060...')
wifiloop = Thread(target=serveWifi, daemon=True)
wifiloop.start()
time.sleep(0.5)

print('eFinder running')

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print('eFinder stopped.')
    _detect_channel.close()
    if _mount_wifi_sock:
        _mount_wifi_sock.close()
    if _mount_serial:
        _mount_serial.close()
