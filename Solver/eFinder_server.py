#!/usr/bin/python3
# eFinder LX200 WiFi server — runs as a separate process from the solve loop.
# Reads solved RA/Dec from /dev/shm/efinder_state.json written by eFinder_cedar_v2.py.
# No camera, no grpc, no picamera2 — clean socket operations unaffected by libcamera.

import os
import sys
import math
import socket
import json
import time
from datetime import datetime
from pathlib import Path

home_path = str(Path.home())
version   = "6.6-cedar-v2"
STATE_FILE = '/dev/shm/efinder_state.json'

# ---------------------------------------------------------------------------
# Config
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
# Coordinates (needed for formatting only)
# ---------------------------------------------------------------------------
def hh2dms(dd):
    minutes, seconds = divmod(abs(dd) * 3600, 60)
    degrees, minutes = divmod(minutes, 60)
    return '%02d:%02d:%02d' % (degrees, minutes, seconds)

def dd2aligndms(dd):
    sign             = '+' if dd >= 0 else '-'
    minutes, seconds = divmod(abs(dd) * 3600, 60)
    degrees, minutes = divmod(minutes, 60)
    return '%s%02d*%02d:%02d' % (sign, degrees, minutes, seconds)

# ---------------------------------------------------------------------------
# State reader
# ---------------------------------------------------------------------------
def get_radec():
    """Read RA (degrees) and Dec (degrees) from state file."""
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        return float(st.get('ra', 0.0)) * 15.0, float(st.get('dec', 0.0))
    except Exception:
        return 0.0, 0.0

def get_state():
    """Read full state dict."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def write_command(cmd, value):
    """Write a command to a command file for the solver to pick up."""
    try:
        cmd_file = '/dev/shm/efinder_cmd.json'
        with open(cmd_file, 'w') as f:
            json.dump({'cmd': cmd, 'value': value, 'ts': time.time()}, f)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# LX200 server
# ---------------------------------------------------------------------------
def serve():
    print('eFinder LX200 server starting on port 4060')
    host = ''
    port = 4060
    size = 1024
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(50)

    raStr = decStr = ""
    timeOffset = '0'
    timeStr    = '23:00:00'

    print('Listening on port 4060')

    while True:
        try:
            client, address = s.accept()
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.settimeout(2.0)

            try:
                data = client.recv(size)
            except socket.timeout:
                client.close()
                continue
            if not data:
                client.close()
                continue

            pkt = data.decode("utf-8", "ignore")
            ra_deg, dec_deg = get_radec()
            raPacket  = hh2dms(ra_deg / 15) + '#'
            decPacket = dd2aligndms(dec_deg) + '#'

            for x in pkt.split('#'):
                if not x:
                    continue
                cmd = x[1:3]
                if x == ':GR':
                    client.send(raPacket.encode('ascii'))
                elif x == ':GD':
                    client.send(decPacket.encode('ascii'))
                elif cmd == 'St':
                    client.send(b'1')
                elif cmd == 'Sg':
                    client.send(b'1')
                elif cmd == 'SG':
                    if len(x) > 5:
                        client.send(b'1')
                        timeOffset = x[3:]
                    else:
                        client.send(b'1')
                elif cmd == 'SL':
                    client.send(b'1')
                    timeStr = x[3:]
                elif cmd == 'SC':
                    client.send(b'Updating Planetary Data#                              #')
                elif cmd in ('RG', 'RC', 'RM', 'RS'):
                    write_command('exp_preset', cmd)
                elif cmd == 'Sr':
                    raStr = x[3:]
                    client.send(b'1')
                elif cmd == 'Sd':
                    decStr = x[3:]
                    client.send(b'1')
                elif cmd == 'MS':
                    client.send(b'0')
                elif cmd in ('Ms', 'Mn'):
                    write_command('adj_exp', cmd)
                elif cmd == 'Mw':
                    write_command('keep', '0')
                elif cmd == 'Me':
                    write_command('keep', '1')
                elif cmd == 'CM':
                    client.send(b'0')
                    write_command('measure_offset', '')
                elif x and x[-1] == 'Q':
                    write_command('keep', '0')
                elif cmd == 'PS':
                    write_command('solve', '')
                    client.send(b':PS1#')
                elif cmd == 'GV':
                    client.send((':GV' + version + '#').encode('ascii'))
                elif cmd == 'GS':
                    st = get_state()
                    client.send((':GS' + str(st.get('stars', '0')) + '#').encode('ascii'))
                elif cmd == 'GK':
                    st = get_state()
                    client.send((':GK' + str(st.get('peak', '0')) + '#').encode('ascii'))
                elif cmd == 'Gt':
                    st = get_state()
                    client.send((':Gt' + str(st.get('solve_time', '00.00')) + '#').encode('ascii'))
                elif cmd == 'SE':
                    write_command('adj_exp', float(x[3:5]))
                    client.send((':SE' + x[3:5] + '#').encode('ascii'))
                elif cmd == 'GA':
                    client.send(b':GA-2#')

            client.close()

        except Exception as e:
            print('Server error:', e)
            try:
                client.close()
            except Exception:
                pass

if __name__ == '__main__':
    serve()
