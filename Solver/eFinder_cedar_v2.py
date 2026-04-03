#!/usr/bin/python3

# eFinder — electronic finder scope, plate-solving over LX200/WiFi for SkySafari
# Derived from original work Copyright (C) 2025 Keith Venables (GPL v3)
# Simplified: direct picamera2, no Nexus, no GPIO, no LED, no WiFi switching
#
# Cedar edition v2:
#   - Fully offline — no internet required at any boot.
#   - Star detection: cedar-detect (Rust gRPC microservice, pre-built in image)
#   - Plate solving: cedar-solve (pre-installed in image venv)
#   - Database: cedar_database.npz pre-generated in image
#   - gRPC stubs: pre-compiled into ~/Solver/ in image
#
# The cedar-detect-server systemd unit starts before this script.
# It listens on localhost:50051.

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
import grpc
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from picamera2 import Picamera2
import tetra3  # cedar-solve installs as the 'tetra3' module

# ---------------------------------------------------------------------------
# Paths and startup
# ---------------------------------------------------------------------------
home_path = str(Path.home())
version   = "6.6-cedar-v2"

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
    """Call cedar-detect gRPC server; return (N,2) array of (row,col) centroids."""
    global _detect_channel, _detect_stub

    assert np_image.dtype == np.uint8
    h, w = np_image.shape

    request = cedar_detect_pb2.ImageRequest(
        image_data=np_image.tobytes(),
        image_width=w,
        image_height=h,
        bpp=8,
    )

    try:
        response = _detect_stub.DetectStars(request, timeout=10.0)
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

    # cedar-detect returns (col, row); tetra3 expects (row, col), brightest-first.
    centroids = np.array(
        [(s.centroid_y, s.centroid_x) for s in response.star_centroids],
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
# Accelerometer (optional)
# ---------------------------------------------------------------------------
try:
    import board
    import adafruit_adxl34x
    i2c    = board.I2C()
    angle  = adafruit_adxl34x.ADXL343(i2c)
    altAngle = True
    print('Accelerometer found')
except Exception:
    print('No accelerometer fitted')
    altAngle = False

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

expInc  = 0.1
gainInc = 5

fnt = ImageFont.truetype(os.path.join(home_path, "Solver/text.ttf"), 16)
cam = (960, 760, 50.8, 13.5)

# ---------------------------------------------------------------------------
# Camera and cedar-solve initialisation
# ---------------------------------------------------------------------------
camera = Camera()
camera.set(float(param.get("Exposure", "0.1")), param.get("Gain", "10"))

print('Loading cedar-solve database...')
t3 = tetra3.Tetra3('cedar_database')
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

    stars = '%4d' % len(centroids)
    peak  = '%3d' % img_peak

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
            img_peak, len(centroids), param['Exposure'], param['Gain']))

    radec        = '%6.4f %+6.4f' % (ra, dec)
    solved_radec = ra, dec
    print('JNow', coordinates.hh2dms(solved_radec[0] / 15),
          coordinates.dd2aligndms(solved_radec[1]))
    solve = True

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
# LX200 WiFi server
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
print('Starting solve loop...')
solveloop = Thread(target=loop_solve, daemon=True)
solveloop.start()
time.sleep(0.5)

print('Starting WiFi/LX200 server...')
wifiloop = Thread(target=serveWifi, daemon=True)
wifiloop.start()
time.sleep(0.5)

print('eFinder running — waiting for SkySafari connection on port 4060')

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print('eFinder stopped.')
    _detect_channel.close()
