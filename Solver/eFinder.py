#!/usr/bin/python3

# eFinder — electronic finder scope, plate-solving over LX200/WiFi for SkySafari
# Derived from original work Copyright (C) 2025 Keith Venables (GPL v3)
# Simplified: direct picamera2, no Nexus, no GPIO, no LED, no WiFi switching
#
# Cedar edition v2 — multiprocess rewrite:
#   Process 0 (main):    spawns the three worker processes; monitors health.
#   Process 1 (camera):  picamera2 capture loop -> shared memory frame slot.
#   Process 2 (solver):  cedar-detect + cedar-solve -> shared Values + JSON.
#   Process 3 (lx200):   LX200/WiFi server — reads Values directly, no IPC lag.
#
# Inter-process communication:
#   frame_shm      — SharedMemory  (760x960 uint8, camera -> solver)
#   frame_ready    — Event         (camera signals solver: new frame ready)
#   shared_ra      — Value(c_double) solver writes, lx200 reads — zero-copy
#   shared_dec     — Value(c_double) solver writes, lx200 reads — zero-copy
#   offset_flag    — Value(c_bool)   lx200/solver coordinate during offset meas.
#   test_mode      — Value(c_bool)   lx200 sets, camera reads
#   cmd_q          — Queue  lx200 -> solver: tuning/on-demand commands
#   result_q       — Queue  solver -> lx200: command results
#   cam_cmd_q      — Queue  solver -> camera: set_exp, capture_once
#   cam_result_q   — Queue  camera -> solver: captured frames
#
# /dev/shm/efinder_state.json  written by solver after each solve — slow
#   telemetry (stars, peak, eTime, etc.) read by lx200 only for diagnostic
#   commands (:GS, :GK, :Gt) which are not timing-critical.

import os
import sys
import math
import socket
import time
import csv
import json
import ctypes
from datetime import datetime
from pathlib import Path
from multiprocessing import (
    Process, Queue, Event, Value,
    shared_memory, set_start_method
)

import numpy as np

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
home_path   = str(Path.home())
version     = "6.6-cedar-v2-mp"
config_path = os.path.join(home_path, "Solver/eFinder.config")
solver_path = os.path.join(home_path, "Solver")

FRAME_H  = 760
FRAME_W  = 960
FRAME_SZ = FRAME_H * FRAME_W

CAM_ARCSEC_PX = 50.8
CAM_FOV_DEG   = 13.5

STATE_FILE = '/dev/shm/efinder_state.json'

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_param():
    param = {}
    if os.path.exists(config_path):
        with open(config_path) as h:
            for line in h:
                parts = line.strip("\n").split(":")
                if len(parts) == 2:
                    param[parts[0]] = str(parts[1])
    return param

def save_param(param):
    with open(config_path, "w") as h:
        for key, value in param.items():
            h.write("%s:%s\n" % (key, value))

# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------
class Coordinates:
    def __init__(self):
        self._update_precession_constants()

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
            hours = str(int(hours - 24)); days = 1
        elif hours < 0:
            hours = str(int(hours + 24)); days = -1
        else:
            hours = str(int(hours))
        timeStr = hours + ':' + minutes + ':' + seconds
        month, day, year = dateStr.split('/')
        day = str(int(day) + days)
        dateStr = month + '/' + day + '/20' + year
        dt_str = dateStr + ' ' + timeStr
        print('Calculated UTC', dt_str)
        os.system('sudo date -u --set "%s"' % dt_str + '.000Z')
        self._update_precession_constants()

    def precess(self, r, d):
        dR = self.m + self.n1 * math.sin(math.radians(r)) * math.tan(math.radians(d))
        dD = self.n2 * math.cos(math.radians(r))
        return r + dR / 240 * self.t, d + dD / 3600 * self.t

    def hh2dms(self, dd):
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%02d:%02d:%02d' % (degrees, minutes, seconds)

    def dd2aligndms(self, dd):
        sign = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d*%02d:%02d' % (sign, degrees, minutes, seconds)

    def dd2dms(self, dd):
        sign = '+' if dd >= 0 else '-'
        minutes, seconds = divmod(abs(dd) * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        return '%s%02d:%02d:%02d' % (sign, degrees, minutes, seconds)

# ---------------------------------------------------------------------------
# Offset / pixel conversion
# ---------------------------------------------------------------------------
def dxdy2pixel(dx, dy):
    pix_x = dx * 3600 / CAM_ARCSEC_PX + FRAME_W / 2
    pix_y = FRAME_H / 2 - dy * 3600 / CAM_ARCSEC_PX
    return pix_x, pix_y

def pixel2dxdy(pix_x, pix_y):
    deg_x = (float(pix_x) - FRAME_W / 2) * CAM_ARCSEC_PX / 3600
    deg_y = (FRAME_H / 2 - float(pix_y)) * CAM_ARCSEC_PX / 3600
    return deg_x, deg_y

# ===========================================================================
# PROCESS 1 - Camera
# ===========================================================================
def camera_process(shm_name, frame_ready, cam_cmd_q, cam_result_q, test_mode):
    """
    Owns Picamera2. Loops: capture -> write shared memory -> set frame_ready.
    Commands on cam_cmd_q:
        ('set_exp', exposure, gain)
        ('capture_once', None, None)  -> puts ('frame', array) on cam_result_q
        ('stop', None, None)
    """
    from picamera2 import Picamera2

    param = load_param()

    shm = shared_memory.SharedMemory(name=shm_name)
    frame_buf = np.ndarray((FRAME_H, FRAME_W), dtype=np.uint8, buffer=shm.buf)

    picam2 = Picamera2()
    cfg = picam2.create_still_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "YUV420"},
        sensor={"output_size": (2028, 1520)},
        buffer_count=2,
    )
    picam2.configure(cfg)

    def _apply(exp_s, gain):
        picam2.stop()
        picam2.set_controls({
            "AeEnable":     False,
            "AwbEnable":    False,
            "ExposureTime": int(float(exp_s) * 1_000_000),
            "AnalogueGain": int(float(gain)),
        })
        picam2.start()

    _apply(param.get("Exposure", "0.1"), param.get("Gain", "10"))
    test_path = os.path.join(home_path, "Solver/test.npy")

    def _capture():
        if test_mode.value and os.path.exists(test_path):
            return np.load(test_path)
        arr = np.array(picam2.capture_array())
        return arr[0:FRAME_H, 0:FRAME_W]

    print('[camera] ready')

    while True:
        # drain commands
        try:
            while True:
                cmd, a, b = cam_cmd_q.get_nowait()
                if cmd == 'set_exp':
                    _apply(a, b)
                elif cmd == 'capture_once':
                    cam_result_q.put(('frame', _capture().copy()))
                elif cmd == 'stop':
                    picam2.stop(); shm.close(); return
        except Exception:
            pass

        # continuous capture into shared memory
        arr = _capture()
        np.copyto(frame_buf, arr)
        frame_ready.set()
        time.sleep(0.05)

# ===========================================================================
# PROCESS 2 - Solver
# ===========================================================================
def solver_process(shm_name, frame_ready, cam_cmd_q, cam_result_q,
                   lx200_cmd_q, lx200_result_q,
                   shared_ra, shared_dec, offset_flag, test_mode):
    """
    Owns tetra3 database and cedar-detect gRPC stub.
    Continuous loop: wait for frame -> solve -> update shared_ra/shared_dec.
    Also handles on-demand commands from lx200_cmd_q.
    """
    import grpc
    import serial as _pyserial
    from threading import Thread as _Thread, Lock as _Lock
    if solver_path not in sys.path:
        sys.path.insert(0, solver_path)
    import cedar_detect_pb2
    import cedar_detect_pb2_grpc
    import tetra3
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps

    param = load_param()
    coordinates = Coordinates()

    shm = shared_memory.SharedMemory(name=shm_name)
    frame_buf = np.ndarray((FRAME_H, FRAME_W), dtype=np.uint8, buffer=shm.buf)

    # --- cedar-detect ---
    CEDAR_ADDR = "localhost:50051"

    def _make_ch():
        return grpc.insecure_channel(CEDAR_ADDR)

    _ch = _make_ch()
    _stub = cedar_detect_pb2_grpc.CedarDetectStub(_ch)

    def get_centroids(img):
        nonlocal _ch, _stub
        h, w = img.shape
        req = cedar_detect_pb2.CentroidsRequest(
            input_image=cedar_detect_pb2.Image(
                width=w, height=h, image_data=img.tobytes()),
            sigma=8.0, detect_hot_pixels=True,
        )
        try:
            resp = _stub.ExtractCentroids(req, timeout=10.0)
        except grpc.RpcError as e:
            print('[solver] cedar-detect error:', e.code(), '- reconnecting')
            try: _ch.close()
            except Exception: pass
            _ch   = _make_ch()
            _stub = cedar_detect_pb2_grpc.CedarDetectStub(_ch)
            return np.empty((0, 2), dtype=np.float64)
        return np.array(
            [(s.centroid_position.y, s.centroid_position.x)
             for s in resp.star_candidates],
            dtype=np.float64)

    # --- tetra3 ---
    print('[solver] loading cedar-solve database...')
    t3 = tetra3.Tetra3('t3_fov14_mag8')
    print('[solver] cedar-solve ready')

    try:
        fnt = ImageFont.truetype(os.path.join(home_path, "Solver/text.ttf"), 16)
    except Exception:
        fnt = ImageFont.load_default()

    # --- FOV calibration ---
    _fov_samples  = []
    _FOV_MIN, _FOV_MAX = 5, 20
    _fov_measured = float(param.get('fov_measured', '0'))

    def _get_fov():
        if _fov_measured > 0 and len(_fov_samples) >= _FOV_MIN:
            return _fov_measured, 0.3
        return CAM_FOV_DEG, 1.0

    def _update_fov(fov_deg):
        nonlocal _fov_measured
        if not fov_deg or fov_deg <= 0: return
        _fov_samples.append(fov_deg)
        if len(_fov_samples) > _FOV_MAX: _fov_samples.pop(0)
        if len(_fov_samples) < _FOV_MIN: return
        avg = sum(_fov_samples) / len(_fov_samples)
        if abs(avg - _fov_measured) > 0.05:
            _fov_measured = avg
            param['fov_measured'] = '%.4f' % avg
            save_param(param)
            print('[solver] FOV calibrated: %.3f deg' % avg)

    # --- offset ---
    def _build_offset():
        ox, oy = dxdy2pixel(
            float(param.get("d_x", "0")) / 60,
            float(param.get("d_y", "0")) / 60)
        return (oy, ox)

    offset = _build_offset()

    MAX_CENTROIDS = 30

    # solver state
    solve        = False
    solved_radec = (0.0, 0.0)
    solution     = None
    firstStar    = None
    stars        = '0'
    peak         = '0'
    eTime        = '00.00'
    keep         = False
    frame_n      = 0
    offset_str   = '%1.3f,%1.3f' % (0.0, 0.0)

    def _write_state():
        try:
            try:
                with open('/sys/class/thermal/thermal_zone0/temp') as f:
                    cpu_temp = int(f.read()) / 1000.0
            except Exception:
                cpu_temp = 0.0
            try:
                with open('/proc/self/status') as f:
                    mem_kb = next(l for l in f if l.startswith('VmRSS:'))
                memory_mb = int(mem_kb.split()[1]) // 1024
            except Exception:
                memory_mb = 0
            s = {
                'ra':              solved_radec[0] / 15.0,
                'dec':             solved_radec[1],
                'solve_status':    'Solved' if solve else 'No solve',
                'solve_timestamp': int(time.time()),
                'stars':           stars,
                'peak':            peak,
                'exposure':        param.get('Exposure', '?'),
                'gain':            param.get('Gain', '?'),
                'solve_time':      eTime,
                'version':         version,
                'fov_measured':    round(_fov_measured, 3) if _fov_measured > 0 else None,
                'fov_samples':     len(_fov_samples),
                'offset_str':      offset_str,
                'cpu_temp':        round(cpu_temp, 1),
                'memory_usage':    memory_mb,
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(s, f)
        except Exception as e:
            print('[solver] state write failed:', e)

    def _write_live(arr):
        try:
            img  = Image.fromarray(arr)
            img2 = ImageEnhance.Contrast(img).enhance(5)
            img2 = img2.rotate(angle=180)
            if solve and solution is not None:
                d = ImageDraw.Draw(img2)
                d.text((5, 5), 'RA %s  Dec %s  Stars %s  %.2fs' % (
                    coordinates.hh2dms(solved_radec[0] / 15),
                    coordinates.dd2aligndms(solved_radec[1]),
                    stars, float(eTime)), font=fnt, fill='white')
            img2.save('/dev/shm/efinder_live.jpg')
        except Exception as e:
            print('[solver] live image write failed:', e)

    def _save_debug(arr, txt):
        nonlocal frame_n, keep
        frame_n += 1
        img  = Image.fromarray(arr)
        img2 = ImageEnhance.Contrast(img).enhance(5)
        img2 = img2.rotate(angle=180)
        d    = ImageDraw.Draw(img2)
        d.text((70, 5), txt + "      Frame %d" % frame_n, font=fnt, fill='white')
        img2 = ImageOps.expand(img2, border=5, fill='red')
        img2.save(os.path.join(home_path, 'Solver/images/capture.jpg'))
        if frame_n > 100:
            keep = False; frame_n = 0

    def _do_solve(img):
        nonlocal solve, solved_radec, solution, firstStar, stars, peak, eTime
        t0 = time.time()
        np_img = img if img.dtype == np.uint8 else img.astype(np.uint8)
        centroids = get_centroids(np_img)
        img_peak  = int(np.max(np_img))
        print('[solver] centroids=%d  peak=%d' % (len(centroids), img_peak))

        if len(centroids) < 15:
            solve = False
            if keep:
                _save_debug(img, "Bad image - %d stars  Exp=%ss Gain=%s" % (
                    len(centroids), param['Exposure'], param['Gain']))
            return False

        if len(centroids) > MAX_CENTROIDS:
            centroids = centroids[:MAX_CENTROIDS]

        stars = '%4d' % len(centroids)
        peak  = '%3d' % img_peak

        fov_est, fov_err = _get_fov()
        kwargs = dict(fov_estimate=fov_est, fov_max_error=fov_err,
                      target_pixel=offset, return_matches=True)
        if solve and solved_radec != (0.0, 0.0):
            kwargs['ra_dec_center'] = solved_radec
            kwargs['search_radius'] = 8.0

        sol = t3.solve_from_centroids(centroids, (FRAME_H, FRAME_W), **kwargs)
        if sol['RA'] is None and 'ra_dec_center' in kwargs:
            print('[solver] seeded solve failed - retrying blind')
            bkw = {k: v for k, v in kwargs.items()
                   if k not in ('ra_dec_center', 'search_radius')}
            sol = t3.solve_from_centroids(centroids, (FRAME_H, FRAME_W), **bkw)

        eTime = ('%2.2f' % (time.time() - t0)).zfill(5)

        if sol['RA'] is None:
            solve = False
            if keep:
                _save_debug(img, "Not Solved - %s stars  Exp=%ss Gain=%s" % (
                    stars, param['Exposure'], param['Gain']))
            return False

        solution  = sol
        firstStar = centroids[0]
        ra, dec = coordinates.precess(sol['RA_target'], sol['Dec_target'])
        _update_fov(sol.get('FOV'))
        if keep:
            _save_debug(img, "Peak=%d  Stars=%s  Exp=%ss Gain=%s" % (
                img_peak, stars, param['Exposure'], param['Gain']))

        solved_radec = (ra, dec)
        solve = True

        # Write ra/dec to shared Values - lx200 reads these directly, zero IPC cost
        shared_ra.value  = ra
        shared_dec.value = dec

        print('[solver] JNow', coordinates.hh2dms(ra / 15),
              coordinates.dd2aligndms(dec))
        _write_state()

        if _MOUNT_MODE != 'none':
            _Thread(target=_push_mount, args=(ra, dec), daemon=True).start()
        return True

    # --- mount ---
    _MOUNT_MODE   = param.get('mount_mode', 'none').lower().strip()
    _MOUNT_HOST   = param.get('mount_host', '192.168.0.1').strip()
    _MOUNT_PORT   = int(param.get('mount_port', '9999'))
    _MOUNT_SERIAL = param.get('mount_serial', '/dev/ttyAMA0').strip()
    _MOUNT_BAUD   = int(param.get('mount_baud', '9600'))
    _mount_lock   = _Lock()
    _mount_sock   = None
    _mount_ser    = None

    def _fmt_ra(deg):
        h = (deg / 15.0) % 24.0
        hh = int(h); mm = int((h-hh)*60); ss = int(((h-hh)*60-mm)*60)
        return '%02d:%02d:%02d' % (hh, mm, ss)

    def _fmt_dec(deg):
        s = '+' if deg >= 0 else '-'; d = abs(deg)
        dd = int(d); mm = int((d-dd)*60); ss = int(((d-dd)*60-mm)*60)
        return '%s%02d*%02d:%02d' % (s, dd, mm, ss)

    def _connect_mount():
        nonlocal _mount_sock, _mount_ser
        if _MOUNT_MODE == 'wifi':
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3.0); s.connect((_MOUNT_HOST, _MOUNT_PORT))
                s.settimeout(1.0)
                _mount_sock = s
                print('[solver] mount (WiFi) connected')
            except Exception as e:
                print('[solver] mount not reachable:', e)
        elif _MOUNT_MODE == 'serial':
            try:
                _mount_ser = _pyserial.Serial(
                    _MOUNT_SERIAL, _MOUNT_BAUD, timeout=1.0, write_timeout=1.0)
                print('[solver] mount (serial) connected')
            except Exception as e:
                print('[solver] mount serial not available:', e)

    def _push_mount(ra, dec):
        nonlocal _mount_sock, _mount_ser
        ra_s = _fmt_ra(ra); dec_s = _fmt_dec(dec)
        with _mount_lock:
            try:
                if _MOUNT_MODE == 'wifi' and _mount_sock:
                    for cmd in [':Sr%s#'%ra_s, ':Sd%s#'%dec_s, ':CM#']:
                        _mount_sock.sendall(cmd.encode('ascii'))
                        _mount_sock.recv(64)
                elif _MOUNT_MODE == 'serial' and _mount_ser:
                    for cmd in [':Sr%s#'%ra_s, ':Sd%s#'%dec_s, ':CM#']:
                        _mount_ser.reset_input_buffer()
                        _mount_ser.write(cmd.encode('ascii'))
                        time.sleep(0.1)
            except Exception as e:
                print('[solver] mount sync failed:', e)
                try:
                    if _mount_sock: _mount_sock.close()
                    if _mount_ser:  _mount_ser.close()
                except Exception: pass
                _mount_sock = _mount_ser = None
                _Thread(target=_connect_mount, daemon=True).start()

    if _MOUNT_MODE != 'none':
        _connect_mount()

    # --- camera helpers ---
    def _request_capture():
        cam_cmd_q.put(('capture_once', None, None))
        try:
            _, arr = cam_result_q.get(timeout=10.0)
            return arr
        except Exception:
            return frame_buf.copy()

    def _set_camera(exp, gain):
        param['Exposure'] = str(exp)
        param['Gain']     = str(gain)
        save_param(param)
        cam_cmd_q.put(('set_exp', exp, gain))

    # --- on-demand command handler ---
    def _handle(cmd, a, b):
        nonlocal solve, solved_radec, offset, offset_str, keep, frame_n

        if cmd == 'adj_exp':
            new_exp = '%.1f' % max(0.1, float(param.get('Exposure','0.1'))
                                   + float(a) * 0.1)
            _set_camera(new_exp, param.get('Gain','10'))
            return new_exp

        elif cmd == 'adj_gain':
            g = max(0, min(50, float(param.get('Gain','10')) + float(a) * 5))
            _set_camera(param.get('Exposure','0.1'), '%.1f' % g)
            return '%.1f' % g

        elif cmd == 'select_exp':
            _set_camera(a, b); return '1'

        elif cmd == 'set_exp':
            _set_camera(float(a), param.get('Gain','10')); return '1'

        elif cmd == 'auto_exp':
            exp = float(param.get('Exposure','0.1'))
            _set_camera(exp, param.get('Gain','10'))
            img = _request_capture()
            for _ in range(20):
                pk = int(np.max(img))
                c  = get_centroids(img)
                print('[solver] auto_exp: %d stars %d peak' % (len(c), pk))
                if len(c) < 20:
                    exp *= 2
                elif len(c) > 50 and pk > 250:
                    exp = int((exp / 2) * 10) / 10
                else:
                    break
                _set_camera(exp, param.get('Gain','10'))
                img = _request_capture()
            return str(exp)

        elif cmd == 'go_solve':
            img = _request_capture()
            return '1' if _do_solve(img) else '0'

        elif cmd == 'measure_offset':
            offset_flag.value = True
            ok = _do_solve(_request_capture())
            if not ok:
                offset_flag.value = False; return 'fail'
            exp = float(param.get('Exposure','0.1'))
            while float(peak) > 255:
                exp *= 0.75
                _set_camera(exp, param.get('Gain','10'))
                ok = _do_solve(_request_capture())
            if not ok:
                offset_flag.value = False; return 'fail'
            sx = firstStar[1]; sy = firstStar[0]
            offset = firstStar
            d_x, d_y = pixel2dxdy(sx, sy)
            param['d_x'] = '{: .2f}'.format(float(60 * d_x))
            param['d_y'] = '{: .2f}'.format(float(60 * d_y))
            save_param(param)
            offset_str = '%1.3f,%1.3f' % (d_x, d_y)
            hipId = str(solution['matched_catID'][0])
            name = sn = ''
            try:
                with open(os.path.join(home_path,'Solver/starnames.csv')) as f:
                    for row in csv.reader(f):
                        if str(row[1]) == hipId:
                            name = row[0].strip()
                            sn = (' (%s)' % row[2].strip()) if row[2].strip() else ''
                            break
            except Exception: pass
            offset_flag.value = False
            _write_state()
            return name + sn + ',HIP' + hipId + ',' + offset_str

        elif cmd == 'reset_offset':
            offset = (FRAME_H / 2, FRAME_W / 2)
            param['d_x'] = 0; param['d_y'] = 0
            offset_str = '%1.3f,%1.3f' % (0.0, 0.0)
            save_param(param); _write_state(); return '1'

        elif cmd == 'start_images':
            keep = (a == '1'); frame_n = 0 if keep else frame_n
            print('[solver] image saving:', 'on' if keep else 'off')
            return '1'

        elif cmd == 'date_set':
            coordinates.dateSet(*a); return '1'

        return 'ok'

    print('[solver] ready, entering main loop')

    while True:
        # drain on-demand commands first
        try:
            while True:
                cmd, a, b = lx200_cmd_q.get_nowait()
                result = _handle(cmd, a, b)
                lx200_result_q.put((cmd, result))
        except Exception:
            pass

        # wait for a new frame (up to 0.5 s)
        if frame_ready.wait(timeout=0.5) and not offset_flag.value:
            frame_ready.clear()
            img = frame_buf.copy()
            _do_solve(img)
            _write_live(img)
            print('[solver] ****************')
            time.sleep(1.0)

# ===========================================================================
# PROCESS 3 - LX200 / WiFi server
# ===========================================================================
def lx200_process(lx200_cmd_q, lx200_result_q,
                  shared_ra, shared_dec, offset_flag, test_mode):
    """
    Serves SkySafari on port 4060.
    Reads ra/dec directly from shared Values - no IPC latency on hot path.
    Reads other telemetry from /dev/shm/efinder_state.json (non-critical path).
    Sends tuning/on-demand commands to solver via lx200_cmd_q.
    """
    coordinates = Coordinates()
    altAngle = False; angle = None

    def enable_accel():
        nonlocal altAngle, angle
        try:
            import board, adafruit_adxl34x
            angle = adafruit_adxl34x.ADXL343(board.I2C())
            altAngle = True
            print('[lx200] accelerometer enabled'); return True
        except Exception as e:
            print('[lx200] accelerometer init failed:', e); return False

    def disable_accel():
        nonlocal altAngle, angle
        altAngle = False; angle = None

    def get_alt():
        if not altAngle: return '-2'
        try:
            x, y, z = angle.acceleration
            if z > 0: return '-1'
            if x > 0: return '99'
            return '%2d' % (-180 / math.pi * math.asin(z / 10))
        except Exception: return '-2'

    def _read_state(key, default=''):
        """Read a single key from the JSON state file - non-critical path only."""
        try:
            with open(STATE_FILE) as f:
                return str(json.load(f).get(key, default))
        except Exception:
            return default

    def _cmd(cmd, a=None, b=None, timeout=15.0):
        lx200_cmd_q.put((cmd, a, b))
        try:
            _, result = lx200_result_q.get(timeout=timeout)
            return str(result)
        except Exception:
            return 'err'

    print('[lx200] starting on port 4060')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 4060)); s.listen(50)
    raStr = decStr = ''
    timeOffset = '0'; timeStr = '23:00:00'

    while True:
        try:
            client, address = s.accept()
            print('[lx200] SkySafari connected from', address)
            while True:
                data = client.recv(1024)
                if not data: break
                pkt = data.decode('utf-8', 'ignore')
                time.sleep(0.02)

                # Hot path: read directly from shared memory - no IPC
                ra  = shared_ra.value
                dec = shared_dec.value
                raPacket  = coordinates.hh2dms(ra / 15) + '#'
                decPacket = coordinates.dd2aligndms(dec) + '#'

                for x in pkt.split('#'):
                    if not x: continue
                    cmd = x[1:3]

                    if   x == ':GR':  client.send(raPacket.encode('ascii'))
                    elif x == ':GD':  client.send(decPacket.encode('ascii'))

                    elif cmd == 'St': client.send(b'1')
                    elif cmd == 'Sg': client.send(b'1')
                    elif cmd == 'SG':
                        if len(x) > 5:
                            client.send(b'1'); timeOffset = x[3:]
                        else:
                            res = _cmd('adj_gain', x[3:5])
                            client.send((':SG' + res + '#').encode('ascii'))
                    elif cmd == 'SL':
                        client.send(b'1'); timeStr = x[3:]
                    elif cmd == 'SC':
                        client.send(b'Updating Planetary Data#                              #')
                        _cmd('date_set', (timeOffset, timeStr, x[3:]))
                    elif cmd == 'RG': _cmd('select_exp', 0.1, 10)
                    elif cmd == 'RC': _cmd('select_exp', 0.1, 20)
                    elif cmd == 'RM': _cmd('select_exp', 0.2, 20)
                    elif cmd == 'RS': _cmd('select_exp', 0.5, 30)
                    elif cmd == 'Sr': raStr = x[3:]; client.send(b'1')
                    elif cmd == 'Sd': decStr = x[3:]; client.send(b'1')
                    elif cmd == 'MS': client.send(b'0')
                    elif cmd == 'Ms': _cmd('adj_exp', -1)
                    elif cmd == 'Mn': _cmd('adj_exp',  1)
                    elif cmd == 'Mw': _cmd('start_images', '0')
                    elif cmd == 'Me': _cmd('start_images', '1')
                    elif cmd == 'CM':
                        client.send(b'0')
                        _cmd('measure_offset', timeout=30.0)
                        try:
                            rp = raStr.split(':')
                            targetRa = int(rp[0]) + int(rp[1])/60 + int(rp[2])/3600
                            dp = decStr.split('*'); dd = dp[1].split(':')
                            targetDec = int(dp[0]) + math.copysign(
                                int(dd[0])/60 + int(dd[1])/3600, float(dp[0]))
                            print('[lx200] align target:', targetRa, targetDec)
                        except Exception: pass
                    elif x and x[-1] == 'Q':
                        _cmd('start_images', '0')
                    elif cmd == 'PS':
                        res = _cmd('go_solve')
                        client.send((':PS' + res + '#').encode('ascii'))
                    elif cmd == 'OF':
                        res = _cmd('measure_offset', timeout=30.0)
                        client.send((':OF' + res + '#').encode('ascii'))
                    elif cmd == 'GV':
                        client.send((':GV' + version + '#').encode('ascii'))
                    elif cmd == 'GO':
                        client.send((':GO' + _read_state('offset_str','0,0') + '#').encode('ascii'))
                    elif cmd == 'SO':
                        res = _cmd('reset_offset')
                        client.send((':SO' + res + '#').encode('ascii'))
                    elif cmd == 'GS':
                        client.send((':GS' + _read_state('stars','0') + '#').encode('ascii'))
                    elif cmd == 'GK':
                        client.send((':GK' + _read_state('peak','0') + '#').encode('ascii'))
                    elif cmd == 'Gt':
                        client.send((':Gt' + _read_state('solve_time','00.00') + '#').encode('ascii'))
                    elif cmd == 'SE':
                        res = _cmd('adj_exp', x[3:5])
                        client.send((':SE' + res + '#').encode('ascii'))
                    elif cmd == 'SX':
                        res = _cmd('set_exp', x.strip('#')[3:])
                        client.send((':SX' + res + '#').encode('ascii'))
                    elif cmd == 'GX':
                        res = _cmd('auto_exp', timeout=60.0)
                        client.send((':GX' + res + '#').encode('ascii'))
                    elif cmd == 'GA':
                        client.send((':GA' + get_alt() + '#').encode('ascii'))
                    elif cmd == 'IM':
                        res = _cmd('start_images', x.strip('#')[3:4])
                        client.send((':IM' + res + '#').encode('ascii'))
                    elif cmd == 'TS':
                        test_mode.value = True
                        client.send(b':TS1#')
                    elif cmd == 'TO':
                        test_mode.value = False
                        client.send(b':TO1#')
                    elif cmd == 'AC':
                        client.send((':AC' + ('1' if enable_accel() else '0') + '#').encode('ascii'))
                    elif cmd == 'AD':
                        disable_accel(); client.send(b':AD1#')
                    elif cmd == 'AG':
                        client.send((':AG' + ('1' if altAngle else '0') + '#').encode('ascii'))

            print('[lx200] SkySafari disconnected')
        except Exception as e:
            print('[lx200] server error:', e)
            try: s.close()
            except Exception: pass
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', 4060)); s.listen(50)

# ===========================================================================
# MAIN
# ===========================================================================
def main():
    if len(sys.argv) > 1:
        print('Killing running version')
        os.system('pkill -9 -f eFinder.py')
        time.sleep(1)

    print('eFinder version', version)
    print('cedar-detect server expected at localhost:50051')

    # shared memory for camera frames
    shm = shared_memory.SharedMemory(create=True, size=FRAME_SZ)
    print('Shared memory:', shm.name, '(%d bytes)' % FRAME_SZ)

    # shared Values for hot-path ra/dec - direct memory read, zero IPC
    shared_ra   = Value(ctypes.c_double, 0.0)
    shared_dec  = Value(ctypes.c_double, 0.0)
    offset_flag = Value(ctypes.c_bool, False)
    test_mode   = Value(ctypes.c_bool, False)

    # queues and events
    frame_ready    = Event()
    cam_cmd_q      = Queue()
    cam_result_q   = Queue()
    lx200_cmd_q    = Queue()
    lx200_result_q = Queue()

    procs = {
        'camera': Process(
            target=camera_process,
            args=(shm.name, frame_ready, cam_cmd_q, cam_result_q, test_mode),
            name='eFinder-camera', daemon=True),
        'solver': Process(
            target=solver_process,
            args=(shm.name, frame_ready, cam_cmd_q, cam_result_q,
                  lx200_cmd_q, lx200_result_q,
                  shared_ra, shared_dec, offset_flag, test_mode),
            name='eFinder-solver', daemon=True),
        'lx200': Process(
            target=lx200_process,
            args=(lx200_cmd_q, lx200_result_q,
                  shared_ra, shared_dec, offset_flag, test_mode),
            name='eFinder-lx200', daemon=True),
    }

    for name, p in procs.items():
        p.start()
        print('Started %s (pid %d)' % (name, p.pid))

    time.sleep(2.0)
    print('eFinder running - SkySafari -> port 4060')

    try:
        while True:
            time.sleep(30)
            for name, p in list(procs.items()):
                if not p.is_alive():
                    print('[main] %s died (exit %s) - restarting' % (name, p.exitcode))
                    new_p = Process(target=p._target, args=p._args,
                                    name=p.name, daemon=True)
                    new_p.start()
                    procs[name] = new_p
                    print('[main] %s restarted (pid %d)' % (name, new_p.pid))
    except KeyboardInterrupt:
        print('eFinder stopped.')
    finally:
        for p in procs.values():
            p.terminate()
        shm.unlink()
        shm.close()

if __name__ == '__main__':
    set_start_method('fork')
    main()
