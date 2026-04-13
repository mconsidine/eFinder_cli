#!/usr/bin/python3

# eFinder — electronic finder scope, plate-solving over LX200/WiFi for SkySafari
# Derived from original work Copyright (C) 2025 Keith Venables (GPL v3)
# Simplified: direct picamera2, no Nexus, no GPIO, no LED, no WiFi switching
#
# Cedar edition v2 — multiprocess rewrite:
#   Process 0 (main):    spawns the three worker processes; monitors health.
#   Process 1 (camera):  picamera2 capture loop → shared memory frame slot.
#   Process 2 (solver):  cedar-detect + cedar-solve → shared state.
#   Process 3 (lx200):   LX200/WiFi server — never blocked by imaging work.
#
# The Pi Zero 2W has 4 Cortex-A53 cores; this layout keeps one per role
# and leaves the 4th free for the OS + the cedar-detect gRPC server.
#
# Inter-process communication:
#   frame_shm   — multiprocessing.shared_memory.SharedMemory (760×960 uint8)
#                 Written by camera process, read by solver process.
#   frame_ready — multiprocessing.Event   (camera → solver: new frame waiting)
#   cmd_q       — multiprocessing.Queue   (lx200 → solver: tuning commands)
#   result_q    — multiprocessing.Queue   (solver → lx200: command results)
#   state       — multiprocessing.Manager dict  (solver → lx200: live telemetry)
#
# The Manager dict holds everything LX200 needs to respond to SkySafari:
#   solved_ra, solved_dec, solve_ok, stars, peak, eTime,
#   offset_str, offset_flag, version, ...
#
# Mount integration (optional — same as non-multiprocess version):
#   mount_mode: none | wifi | serial   (eFinder.config)

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
    Process, Queue, Event, Manager,
    shared_memory, set_start_method
)
from multiprocessing.managers import DictProxy

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
FRAME_SZ = FRAME_H * FRAME_W   # bytes in a YUV420 Y-plane

CAM_ARCSEC_PX = 50.8
CAM_FOV_DEG   = 13.5

# ---------------------------------------------------------------------------
# Config helpers (safe to call in any process after fork)
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
# Coordinate helpers (pure functions — used in both solver and lx200 processes)
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
# Offset / pixel conversion (pure — used in solver process)
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
# PROCESS 1 — Camera
# ===========================================================================
def camera_process(shm_name: str, frame_ready: Event, cmd_q: Queue,
                   result_q: Queue, state: DictProxy):
    """
    Owns the Picamera2 instance.  Runs an exposure loop:
        capture → copy into shared memory → set frame_ready event.

    Also handles camera-control commands arriving on cmd_q:
        ('set_exp', exposure, gain)   — change exposure/gain
        ('capture_once', None, None)  — single capture, put result on result_q
        ('stop', None, None)          — clean shutdown
    """
    from picamera2 import Picamera2

    param = load_param()

    # --- attach to shared memory frame slot ---
    shm = shared_memory.SharedMemory(name=shm_name)
    frame_buf = np.ndarray((FRAME_H, FRAME_W), dtype=np.uint8, buffer=shm.buf)

    # --- camera init ---
    picam2 = Picamera2()
    cfg = picam2.create_still_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "YUV420"},
        sensor={"output_size": (2028, 1520)},
        buffer_count=2,
    )
    picam2.configure(cfg)

    def _apply_settings(exp_s, gain):
        picam2.stop()
        picam2.set_controls({
            "AeEnable":     False,
            "AwbEnable":    False,
            "ExposureTime": int(float(exp_s) * 1_000_000),
            "AnalogueGain": int(float(gain)),
        })
        picam2.start()

    _apply_settings(param.get("Exposure", "0.1"), param.get("Gain", "10"))
    test_path = os.path.join(home_path, "Solver/test.npy")

    def _capture_raw():
        if state.get('testMode') and os.path.exists(test_path):
            return np.load(test_path)
        arr = np.array(picam2.capture_array())
        return arr[0:FRAME_H, 0:FRAME_W]

    print('[camera] ready')

    while True:
        # --- drain command queue (non-blocking) ---
        try:
            while True:
                cmd, a, b = cmd_q.get_nowait()
                if cmd == 'set_exp':
                    _apply_settings(a, b)
                elif cmd == 'capture_once':
                    arr = _capture_raw()
                    result_q.put(('frame', arr.copy()))
                elif cmd == 'stop':
                    picam2.stop()
                    shm.close()
                    return
        except Exception:
            pass  # queue empty — normal

        # --- normal capture cycle ---
        if not state.get('offset_flag', False):
            arr = _capture_raw()
            np.copyto(frame_buf, arr)
            frame_ready.set()   # signal solver: new frame in shared memory

        time.sleep(0.05)   # ~20 fps cap; solver will pace itself

# ===========================================================================
# PROCESS 2 — Solver
# ===========================================================================
def solver_process(shm_name: str, frame_ready: Event, cam_cmd_q: Queue,
                   cam_result_q: Queue, lx200_cmd_q: Queue,
                   lx200_result_q: Queue, state: DictProxy):
    """
    Owns tetra3 database and cedar-detect gRPC stub.
    Main loop: wait for frame_ready → solve → update state.
    Also drains lx200_cmd_q for on-demand commands:
        ('measure_offset', ...), ('go_solve', ...), ('auto_exp', ...),
        ('set_exp', exp, gain), ('adj_exp', delta, None),
        ('adj_gain', delta, None), ('select_exp', exp, gain), ...
    """
    # gRPC and tetra3 imports — only in this process
    import grpc
    if solver_path not in sys.path:
        sys.path.insert(0, solver_path)
    import cedar_detect_pb2
    import cedar_detect_pb2_grpc
    import tetra3
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps

    CEDAR_DETECT_ADDR = "localhost:50051"

    param = load_param()
    coordinates = Coordinates()

    # --- attach to shared memory ---
    shm = shared_memory.SharedMemory(name=shm_name)
    frame_buf = np.ndarray((FRAME_H, FRAME_W), dtype=np.uint8, buffer=shm.buf)

    # --- cedar-detect gRPC ---
    def _make_channel():
        return grpc.insecure_channel(CEDAR_DETECT_ADDR)

    _ch   = _make_channel()
    _stub = cedar_detect_pb2_grpc.CedarDetectStub(_ch)

    def get_centroids(img: np.ndarray) -> np.ndarray:
        nonlocal _ch, _stub
        h, w = img.shape
        req = cedar_detect_pb2.CentroidsRequest(
            input_image=cedar_detect_pb2.Image(width=w, height=h,
                                               image_data=img.tobytes()),
            sigma=8.0, detect_hot_pixels=True,
        )
        try:
            resp = _stub.ExtractCentroids(req, timeout=10.0)
        except grpc.RpcError as e:
            print('[solver] cedar-detect error:', e.code(), '— reconnecting')
            try: _ch.close()
            except Exception: pass
            _ch   = _make_channel()
            _stub = cedar_detect_pb2_grpc.CedarDetectStub(_ch)
            return np.empty((0, 2), dtype=np.float64)
        return np.array(
            [(s.centroid_position.y, s.centroid_position.x)
             for s in resp.star_candidates],
            dtype=np.float64,
        )

    # --- tetra3 / cedar-solve ---
    print('[solver] loading cedar-solve database…')
    t3 = tetra3.Tetra3('t3_fov14_mag8')
    print('[solver] cedar-solve ready')

    # --- font for annotated images ---
    try:
        fnt = ImageFont.truetype(os.path.join(home_path, "Solver/text.ttf"), 16)
    except Exception:
        fnt = ImageFont.load_default()

    # --- FOV calibration state ---
    _fov_samples  = []
    _FOV_MIN      = 5
    _FOV_MAX      = 20
    _fov_measured = float(param.get('fov_measured', '0'))

    def _get_fov_estimate():
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
    def _build_offset(param):
        _ox, _oy = dxdy2pixel(
            float(param.get("d_x", "0")) / 60,
            float(param.get("d_y", "0")) / 60,
        )
        return (_oy, _ox)

    offset = _build_offset(param)

    MAX_CENTROIDS = 30

    # solver internal state
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

    def _write_state_file():
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
            'solve_duration':  int(float(eTime) * 1000) if eTime else 0,
            'version':         version,
            'fov_measured':    round(_fov_measured, 3) if _fov_measured > 0 else None,
            'fov_samples':     len(_fov_samples),
            'roll':            round(solution.get('Roll', 0.0), 2) if solution else 0.0,
            'rmse_arcsec':     round(float(solution['RMSE']), 2)
                               if solution and solution.get('RMSE') else None,
            'cpu_temp':        round(cpu_temp, 1),
            'memory_usage':    memory_mb,
        }
        with open('/dev/shm/efinder_state.json', 'w') as f:
            json.dump(s, f)

    def _write_live_image(arr):
        try:
            os.makedirs(os.path.join(home_path, 'Solver/images'), exist_ok=True)
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

    def _save_debug_image(arr, txt):
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
            keep    = False
            frame_n = 0

    def _push_state():
        """Mirror critical telemetry into the Manager dict for lx200 process."""
        state['solved_ra']   = solved_radec[0]
        state['solved_dec']  = solved_radec[1]
        state['solve_ok']    = solve
        state['stars']       = stars
        state['peak']        = peak
        state['eTime']       = eTime
        state['offset_str']  = offset_str
        state['exposure']    = param.get('Exposure', '0.1')
        state['gain']        = param.get('Gain', '10')

    def _do_solve(img: np.ndarray) -> bool:
        nonlocal solve, solved_radec, solution, firstStar, stars, peak, eTime
        t0 = time.time()
        np_img = img if img.dtype == np.uint8 else img.astype(np.uint8)
        centroids = get_centroids(np_img)
        img_peak  = int(np.max(np_img))
        print('[solver] centroids=%d  peak=%d' % (len(centroids), img_peak))

        if len(centroids) < 15:
            solve = False
            if keep:
                _save_debug_image(img, "Bad image - %d stars  Exp=%ss Gain=%s" % (
                    len(centroids), param['Exposure'], param['Gain']))
            return False

        if len(centroids) > MAX_CENTROIDS:
            centroids = centroids[:MAX_CENTROIDS]

        stars = '%4d' % len(centroids)
        peak  = '%3d' % img_peak

        _fov_est, _fov_err = _get_fov_estimate()
        kwargs = dict(fov_estimate=_fov_est, fov_max_error=_fov_err,
                      target_pixel=offset, return_matches=True)
        if solve and solved_radec != (0.0, 0.0):
            kwargs['ra_dec_center'] = solved_radec
            kwargs['search_radius'] = 8.0

        sol = t3.solve_from_centroids(centroids, (FRAME_H, FRAME_W), **kwargs)
        if sol['RA'] is None and 'ra_dec_center' in kwargs:
            print('[solver] seeded solve failed — retrying blind')
            bkw = {k: v for k, v in kwargs.items()
                   if k not in ('ra_dec_center', 'search_radius')}
            sol = t3.solve_from_centroids(centroids, (FRAME_H, FRAME_W), **bkw)

        eTime = ('%2.2f' % (time.time() - t0)).zfill(5)

        if sol['RA'] is None:
            solve = False
            if keep:
                _save_debug_image(img, "Not Solved - %s stars  Exp=%ss Gain=%s" % (
                    stars, param['Exposure'], param['Gain']))
            return False

        solution  = sol
        firstStar = centroids[0]
        ra  = sol['RA_target']
        dec = sol['Dec_target']
        ra, dec = coordinates.precess(ra, dec)
        _update_fov(sol.get('FOV'))
        if keep:
            _save_debug_image(img, "Peak=%d  Stars=%s  Exp=%ss Gain=%s" % (
                img_peak, stars, param['Exposure'], param['Gain']))
        solved_radec = (ra, dec)
        solve = True
        print('[solver] JNow', coordinates.hh2dms(ra / 15),
              coordinates.dd2aligndms(dec))
        _write_state_file()
        _push_state()

        # Push to mount (fire-and-forget in this process — cheap thread)
        if state.get('mount_mode', 'none') != 'none':
            from threading import Thread as _Thread
            _Thread(target=_push_to_mount_solver,
                    args=(ra, dec), daemon=True).start()
        return True

    # --- mount push (solver-side, avoids needing mount socket in lx200 proc) ---
    import serial as _pyserial
    from threading import Lock as _Lock
    _MOUNT_MODE   = param.get('mount_mode', 'none').lower().strip()
    _MOUNT_HOST   = param.get('mount_host', '192.168.0.1').strip()
    _MOUNT_PORT   = int(param.get('mount_port', '9999'))
    _MOUNT_SERIAL = param.get('mount_serial', '/dev/ttyAMA0').strip()
    _MOUNT_BAUD   = int(param.get('mount_baud', '9600'))
    _mount_lock   = _Lock()
    _mount_sock   = None
    _mount_ser    = None
    state['mount_mode'] = _MOUNT_MODE

    def _fmt_ra(deg):
        h = (deg / 15.0) % 24.0
        hh = int(h); mm = int((h-hh)*60); ss = int(((h-hh)*60-mm)*60)
        return '%02d:%02d:%02d' % (hh, mm, ss)

    def _fmt_dec(deg):
        s = '+' if deg >= 0 else '-'; d = abs(deg)
        dd = int(d); mm = int((d-dd)*60); ss = int(((d-dd)*60-mm)*60)
        return '%s%02d*%02d:%02d' % (s, dd, mm, ss)

    def _try_connect_mount():
        nonlocal _mount_sock, _mount_ser
        if _MOUNT_MODE == 'wifi':
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3.0)
                s.connect((_MOUNT_HOST, _MOUNT_PORT))
                s.settimeout(1.0)
                s.sendall(b':GVN#')
                ver = s.recv(64).decode('ascii', errors='ignore')
                _mount_sock = s
                print('[solver] mount (WiFi) connected, fw=%s' % ver.strip('#'))
            except Exception as e:
                print('[solver] mount (WiFi) not reachable:', e)
        elif _MOUNT_MODE == 'serial':
            try:
                ser = _pyserial.Serial(_MOUNT_SERIAL, _MOUNT_BAUD,
                                       timeout=1.0, write_timeout=1.0)
                _mount_ser = ser
                print('[solver] mount (serial) connected')
            except Exception as e:
                print('[solver] mount (serial) not available:', e)

    def _push_to_mount_solver(ra, dec):
        nonlocal _mount_sock, _mount_ser
        ra_s = _fmt_ra(ra); dec_s = _fmt_dec(dec)
        with _mount_lock:
            try:
                if _MOUNT_MODE == 'wifi' and _mount_sock:
                    for cmd in [':Sr%s#' % ra_s, ':Sd%s#' % dec_s, ':CM#']:
                        _mount_sock.sendall(cmd.encode('ascii'))
                        _mount_sock.recv(64)
                    print('[solver] mount synced (WiFi)')
                elif _MOUNT_MODE == 'serial' and _mount_ser:
                    for cmd in [':Sr%s#' % ra_s, ':Sd%s#' % dec_s, ':CM#']:
                        _mount_ser.reset_input_buffer()
                        _mount_ser.write(cmd.encode('ascii'))
                        time.sleep(0.1)
                    print('[solver] mount synced (serial)')
            except Exception as e:
                print('[solver] mount sync failed:', e)
                try:
                    if _mount_sock: _mount_sock.close()
                    if _mount_ser:  _mount_ser.close()
                except Exception: pass
                _mount_sock = _mount_ser = None
                from threading import Thread as _T
                _T(target=_try_connect_mount, daemon=True).start()

    if _MOUNT_MODE != 'none':
        _try_connect_mount()

    # --- camera helpers called from lx200 commands ---
    def _request_capture() -> np.ndarray:
        """Ask camera process for one frame and wait for it."""
        cam_cmd_q.put(('capture_once', None, None))
        try:
            tag, arr = cam_result_q.get(timeout=10.0)
            return arr
        except Exception:
            return frame_buf.copy()

    def _set_camera(exp, gain):
        param['Exposure'] = str(exp)
        param['Gain']     = str(gain)
        save_param(param)
        cam_cmd_q.put(('set_exp', exp, gain))
        _push_state()

    def _handle_lx200_command(cmd, arg1, arg2):
        nonlocal solve, solved_radec, offset, offset_str, keep, frame_n
        """
        Handle on-demand commands from the lx200 process.
        Returns a result string that lx200 will forward to SkySafari.
        """
        if cmd == 'adj_exp':
            new_exp = '%.1f' % max(0.1, float(param.get('Exposure', '0.1'))
                                   + float(arg1) * 0.1)
            _set_camera(new_exp, param.get('Gain', '10'))
            return new_exp

        elif cmd == 'adj_gain':
            g = float(param.get('Gain', '10')) + float(arg1) * 5
            g = max(0, min(50, g))
            _set_camera(param.get('Exposure', '0.1'), '%.1f' % g)
            return '%.1f' % g

        elif cmd == 'select_exp':
            _set_camera(arg1, arg2)
            return '1'

        elif cmd == 'set_exp':
            _set_camera(float(arg1), param.get('Gain', '10'))
            return '1'

        elif cmd == 'auto_exp':
            exp = float(param.get('Exposure', '0.1'))
            _set_camera(exp, param.get('Gain', '10'))
            img = _request_capture()
            for _ in range(20):
                pk = int(np.max(img))
                centroids = get_centroids(img)
                print('[solver] auto_exp: %d stars  %d peak' % (len(centroids), pk))
                if len(centroids) < 20:
                    exp *= 2
                elif len(centroids) > 50 and pk > 250:
                    exp = int((exp / 2) * 10) / 10
                else:
                    break
                _set_camera(exp, param.get('Gain', '10'))
                img = _request_capture()
            return str(exp)

        elif cmd == 'go_solve':
            img = _request_capture()
            ok  = _do_solve(img)
            return '1' if ok else '0'

        elif cmd == 'measure_offset':
            state['offset_flag'] = True
            img = _request_capture()
            ok = _do_solve(img)
            if not ok:
                state['offset_flag'] = False
                return 'fail'
            exp = float(param.get('Exposure', '0.1'))
            while float(peak) > 255:
                exp *= 0.75
                _set_camera(exp, param.get('Gain', '10'))
                img = _request_capture()
                ok = _do_solve(img)
            if not ok:
                state['offset_flag'] = False
                return 'fail'
            scope_x = firstStar[1]; scope_y = firstStar[0]
            offset = firstStar
            d_x, d_y = pixel2dxdy(scope_x, scope_y)
            param['d_x'] = '{: .2f}'.format(float(60 * d_x))
            param['d_y'] = '{: .2f}'.format(float(60 * d_y))
            save_param(param)
            offset_str = '%1.3f,%1.3f' % (d_x, d_y)
            hipId = str(solution['matched_catID'][0])
            name = secondname = ''
            try:
                with open(os.path.join(home_path, 'Solver/starnames.csv')) as f:
                    for row in csv.reader(f):
                        if str(row[1]) == hipId:
                            hipId = row[1]; name = row[0].strip()
                            secondname = (' (%s)' % row[2].strip()) if row[2].strip() else ''
                            break
            except Exception: pass
            state['offset_flag'] = False
            _push_state()
            return name + secondname + ',HIP' + hipId + ',' + offset_str

        elif cmd == 'reset_offset':
            offset = (FRAME_H / 2, FRAME_W / 2)
            param['d_x'] = 0; param['d_y'] = 0
            offset_str = '%1.3f,%1.3f' % (0.0, 0.0)
            save_param(param)
            _push_state()
            return '1'

        elif cmd == 'start_images':
            keep    = (arg1 == '1')
            frame_n = 0 if keep else frame_n
            print('[solver] image saving:', 'on' if keep else 'off')
            return '1'

        elif cmd == 'date_set':
            # arg1=(timeOffset, timeStr, dateStr)
            coordinates.dateSet(*arg1)
            return '1'

        return 'ok'

    # initialise state dict
    _push_state()
    state['offset_flag'] = False
    state['testMode']    = False

    print('[solver] ready, entering main loop')

    # --- main solver loop ---
    while True:
        # 1. Drain on-demand commands from lx200 — highest priority
        try:
            while True:
                cmd, a, b = lx200_cmd_q.get_nowait()
                result = _handle_lx200_command(cmd, a, b)
                lx200_result_q.put((cmd, result))
        except Exception:
            pass   # queue empty

        # 2. If a new frame is ready, solve it
        got_frame = frame_ready.wait(timeout=0.5)
        if got_frame and not state.get('offset_flag', False):
            frame_ready.clear()
            img = frame_buf.copy()   # snapshot — camera may overwrite shm next
            _do_solve(img)
            _write_live_image(img)
            print('[solver] ****************')
            time.sleep(1.0)   # pace: 1 s minimum between solve iterations


# ===========================================================================
# PROCESS 3 — LX200 / WiFi server
# ===========================================================================
def lx200_process(solver_cmd_q: Queue, solver_result_q: Queue,
                  state: DictProxy):
    """
    Serves SkySafari on port 4060 using the LX200 protocol.
    Reads telemetry (RA/Dec/stars/etc.) from the Manager dict `state`.
    Sends tuning commands to the solver process via solver_cmd_q and waits
    for results on solver_result_q.
    """
    coordinates = Coordinates()
    USE_ACCELEROMETER = False
    altAngle = False; angle = None

    def enable_accel():
        nonlocal altAngle, angle, USE_ACCELEROMETER
        try:
            import board, adafruit_adxl34x
            angle = adafruit_adxl34x.ADXL343(board.I2C())
            altAngle = True; USE_ACCELEROMETER = True
            print('[lx200] accelerometer enabled'); return True
        except Exception as e:
            print('[lx200] accelerometer init failed:', e)
            return False

    def disable_accel():
        nonlocal altAngle, angle, USE_ACCELEROMETER
        altAngle = False; angle = None; USE_ACCELEROMETER = False

    def get_alt():
        if not altAngle: return '-2'
        try:
            x, y, z = angle.acceleration
            if z > 0: return '-1'
            if x > 0: return '99'
            return '%2d' % (-180 / math.pi * math.asin(z / 10))
        except Exception:
            return '-2'

    def _cmd(cmd, a=None, b=None, timeout=15.0) -> str:
        """Send a command to the solver and wait for its result."""
        solver_cmd_q.put((cmd, a, b))
        try:
            tag, result = solver_result_q.get(timeout=timeout)
            return str(result)
        except Exception:
            return 'err'

    print('[lx200] starting on port 4060')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 4060))
    s.listen(50)
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

                # Read current telemetry from shared state
                ra  = state.get('solved_ra',  0.0)
                dec = state.get('solved_dec', 0.0)
                raPacket  = coordinates.hh2dms(ra / 15) + '#'
                decPacket = coordinates.dd2aligndms(dec) + '#'

                for x in pkt.split('#'):
                    if not x: continue
                    cmd = x[1:3]

                    if   x == ':GR':  client.send(raPacket.encode('ascii'))
                    elif x == ':GD':  client.send(decPacket.encode('ascii'))

                    elif cmd == 'St':
                        client.send(b'1')
                    elif cmd == 'Sg':
                        client.send(b'1')
                    elif cmd == 'SG':
                        if len(x) > 5:
                            client.send(b'1')
                            timeOffset = x[3:]
                        else:
                            res = _cmd('adj_gain', x[3:5])
                            client.send((':SG' + res + '#').encode('ascii'))
                    elif cmd == 'SL':
                        client.send(b'1')
                        timeStr = x[3:]
                    elif cmd == 'SC':
                        client.send(b'Updating Planetary Data#                              #')
                        _cmd('date_set', (timeOffset, timeStr, x[3:]))
                    elif cmd == 'RG':  _cmd('select_exp', 0.1, 10)
                    elif cmd == 'RC':  _cmd('select_exp', 0.1, 20)
                    elif cmd == 'RM':  _cmd('select_exp', 0.2, 20)
                    elif cmd == 'RS':  _cmd('select_exp', 0.5, 30)
                    elif cmd == 'Sr':
                        raStr = x[3:]; client.send(b'1')
                    elif cmd == 'Sd':
                        decStr = x[3:]; client.send(b'1')
                    elif cmd == 'MS':
                        client.send(b'0')
                    elif cmd == 'Ms':  _cmd('adj_exp', -1)
                    elif cmd == 'Mn':  _cmd('adj_exp',  1)
                    elif cmd == 'Mw':  _cmd('start_images', '0')
                    elif cmd == 'Me':  _cmd('start_images', '1')
                    elif cmd == 'CM':
                        client.send(b'0')
                        _cmd('measure_offset', timeout=30.0)
                        try:
                            ra_p = raStr.split(':')
                            targetRa = int(ra_p[0]) + int(ra_p[1]) / 60 + int(ra_p[2]) / 3600
                            dec_p = decStr.split('*')
                            dd = dec_p[1].split(':')
                            targetDec = int(dec_p[0]) + math.copysign(
                                int(dd[0]) / 60 + int(dd[1]) / 3600, float(dec_p[0]))
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
                        client.send((':GO' + state.get('offset_str', '0,0') + '#').encode('ascii'))
                    elif cmd == 'SO':
                        res = _cmd('reset_offset')
                        client.send((':SO' + res + '#').encode('ascii'))
                    elif cmd == 'GS':
                        client.send((':GS' + state.get('stars', '0') + '#').encode('ascii'))
                    elif cmd == 'GK':
                        client.send((':GK' + state.get('peak', '0') + '#').encode('ascii'))
                    elif cmd == 'Gt':
                        client.send((':Gt' + state.get('eTime', '00.00') + '#').encode('ascii'))
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
                        state['testMode'] = True
                        client.send((':TS1#').encode('ascii'))
                    elif cmd == 'TO':
                        state['testMode'] = False
                        client.send((':TO1#').encode('ascii'))
                    elif cmd == 'AC':
                        result = '1' if enable_accel() else '0'
                        client.send((':AC' + result + '#').encode('ascii'))
                    elif cmd == 'AD':
                        disable_accel()
                        client.send(b':AD1#')
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
# MAIN — spawn processes, monitor health
# ===========================================================================
def main():
    if len(sys.argv) > 1:
        print('Killing running version')
        os.system('pkill -9 -f eFinder_cedar_v2.py')
        time.sleep(1)

    print('eFinder version', version)
    print('cedar-detect server expected at localhost:50051')

    # --- shared memory for camera frames ---
    shm = shared_memory.SharedMemory(create=True, size=FRAME_SZ)
    print('Shared memory:', shm.name, '(%d bytes)' % FRAME_SZ)

    # --- inter-process plumbing ---
    frame_ready    = Event()
    cam_cmd_q      = Queue()    # main → camera: set_exp, capture_once, stop
    cam_result_q   = Queue()    # camera → solver: captured frames
    solver_cmd_q   = Queue()    # lx200 → solver: on-demand commands
    solver_result_q = Queue()   # solver → lx200: command results

    mgr   = Manager()
    state = mgr.dict()
    state['solved_ra']   = 0.0
    state['solved_dec']  = 0.0
    state['solve_ok']    = False
    state['stars']       = '0'
    state['peak']        = '0'
    state['eTime']       = '00.00'
    state['offset_str']  = '0,0'
    state['offset_flag'] = False
    state['testMode']    = False
    state['mount_mode']  = 'none'

    # --- spawn workers ---
    procs = {
        'camera': Process(
            target=camera_process,
            args=(shm.name, frame_ready, cam_cmd_q, cam_result_q, state),
            name='eFinder-camera', daemon=True),
        'solver': Process(
            target=solver_process,
            args=(shm.name, frame_ready, cam_cmd_q, cam_result_q,
                  solver_cmd_q, solver_result_q, state),
            name='eFinder-solver', daemon=True),
        'lx200': Process(
            target=lx200_process,
            args=(solver_cmd_q, solver_result_q, state),
            name='eFinder-lx200', daemon=True),
    }

    for name, p in procs.items():
        p.start()
        print('Started %s (pid %d)' % (name, p.pid))

    time.sleep(2.0)
    print('eFinder running — SkySafari → port 4060')

    # --- health monitor: restart dead processes ---
    try:
        while True:
            time.sleep(30)
            for name, p in procs.items():
                if not p.is_alive():
                    print('[main] %s process died (exit %s) — restarting' % (
                        name, p.exitcode))
                    # Restart with same args
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
    set_start_method('fork')   # 'fork' is default on Linux; explicit for clarity
    main()
