#!/usr/bin/env python3
"""
onstepx_serial.py - OnStepX Serial Connection Module

Adds direct serial connection support to eFinder for OnStepX-based mounts.
Maintains backward compatibility with WiFi/SkySafari mode.

Usage:
    from onstepx_serial import MountConnection
    
    mount = MountConnection()  # Auto-detects serial or falls back to WiFi
    mount.slew_to(ra_hours, dec_degrees)
    mount.sync_position(solved_ra, solved_dec)
"""

import serial
import socket
import time
import logging
from typing import Optional, Tuple
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionMode(Enum):
    """Mount connection modes"""
    SERIAL = "serial"  # Direct serial to OnStepX
    WIFI = "wifi"      # WiFi LX200 server for SkySafari


class MountConnection:
    """
    Unified interface for mount communication.
    Automatically detects OnStepX serial connection or falls back to WiFi.
    """
    
    def __init__(self, config_file="/home/efinder/Solver/eFinder.config"):
        """
        Initialize mount connection.
        
        Args:
            config_file: Path to eFinder configuration file
        """
        self.config = self._load_config(config_file)
        self.mode = None
        self.connection = None
        self.connect()
    
    def _load_config(self, config_file: str) -> dict:
        """Load mount configuration from file"""
        config = {
            'mode': 'AUTO',  # AUTO, SERIAL, WIFI
            'serial_port': '/dev/ttyAMA0',
            'serial_baudrate': 9600,
            'wifi_port': 4060
        }
        
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    if line.startswith('[mount]'):
                        continue
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key in config:
                            if key.endswith('_port') or key.endswith('baudrate'):
                                config[key] = int(value)
                            else:
                                config[key] = value
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_file}, using defaults")
        
        return config
    
    def connect(self):
        """Establish mount connection based on configuration"""
        mode = self.config['mode'].upper()
        
        if mode == 'AUTO':
            # Try serial first, fall back to WiFi
            if self._try_serial():
                return
            self._connect_wifi()
        elif mode == 'SERIAL':
            if not self._try_serial():
                raise ConnectionError("Serial connection requested but failed")
        elif mode == 'WIFI':
            self._connect_wifi()
        else:
            raise ValueError(f"Invalid mount mode: {mode}")
    
    def _try_serial(self) -> bool:
        """
        Attempt to connect via serial.
        
        Returns:
            True if successful, False otherwise
        """
        import os
        
        port = self.config['serial_port']
        baudrate = self.config['serial_baudrate']
        
        if not os.path.exists(port):
            logger.info(f"Serial port {port} not found")
            return False
        
        try:
            self.connection = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=2.0,
                write_timeout=2.0
            )
            
            # Test connection with version query
            response = self._send_lx200_serial(":GVN#")
            
            if response and len(response) > 0:
                self.mode = ConnectionMode.SERIAL
                logger.info(f"OnStepX connected via {port} at {baudrate} baud")
                logger.info(f"OnStep version: {response}")
                return True
            else:
                self.connection.close()
                self.connection = None
                logger.warning("Serial port exists but no OnStepX response")
                return False
                
        except (serial.SerialException, OSError) as e:
            logger.warning(f"Serial connection failed: {e}")
            if self.connection:
                self.connection.close()
                self.connection = None
            return False
    
    def _connect_wifi(self):
        """Connect as WiFi LX200 server for SkySafari"""
        port = self.config['wifi_port']
        
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.connection.bind(('0.0.0.0', port))
        self.connection.listen(1)
        
        self.mode = ConnectionMode.WIFI
        logger.info(f"WiFi LX200 server listening on port {port}")
        logger.info("Waiting for SkySafari connection...")
    
    def _send_lx200_serial(self, command: str) -> str:
        """
        Send LX200 command over serial and read response.
        
        Args:
            command: LX200 command string (e.g., ":GR#")
        
        Returns:
            Response string (without terminator)
        """
        if not self.connection or self.mode != ConnectionMode.SERIAL:
            raise RuntimeError("Not connected via serial")
        
        # Flush buffers
        self.connection.reset_input_buffer()
        self.connection.reset_output_buffer()
        
        # Send command
        self.connection.write(command.encode('ascii'))
        
        # Read response
        # Most LX200 responses end with '#', some are just '1' or '0'
        response = b''
        start_time = time.time()
        
        while time.time() - start_time < 2.0:  # 2 second timeout
            if self.connection.in_waiting:
                char = self.connection.read(1)
                response += char
                if char == b'#':
                    break
                # Some commands (like :MS#) return just '0' or '1'
                if len(response) == 1 and char in (b'0', b'1'):
                    break
        
        return response.decode('ascii', errors='ignore').rstrip('#')
    
    def get_position(self) -> Tuple[float, float]:
        """
        Get current mount RA/Dec position.
        
        Returns:
            (ra_hours, dec_degrees)
        """
        if self.mode == ConnectionMode.SERIAL:
            # Query RA
            ra_str = self._send_lx200_serial(":GR#")  # Returns HH:MM:SS
            # Query Dec
            dec_str = self._send_lx200_serial(":GD#")  # Returns ±DD:MM:SS
            
            ra_hours = self._parse_ra(ra_str)
            dec_degrees = self._parse_dec(dec_str)
            
            return ra_hours, dec_degrees
        else:
            # WiFi mode: get from last SkySafari command
            # This requires tracking state from SkySafari's :Sr# and :Sd# commands
            # For now, return placeholder
            logger.warning("get_position() in WiFi mode requires SkySafari state tracking")
            return 0.0, 0.0
    
    def slew_to(self, ra_hours: float, dec_degrees: float) -> bool:
        """
        Slew mount to target coordinates.
        
        Args:
            ra_hours: Right Ascension in decimal hours (0-24)
            dec_degrees: Declination in decimal degrees (-90 to +90)
        
        Returns:
            True if slew started successfully
        """
        if self.mode == ConnectionMode.SERIAL:
            # Set target RA
            ra_str = self._format_ra(ra_hours)
            self._send_lx200_serial(f":Sr{ra_str}#")
            
            # Set target Dec
            dec_str = self._format_dec(dec_degrees)
            self._send_lx200_serial(f":Sd{dec_str}#")
            
            # Start slew
            response = self._send_lx200_serial(":MS#")
            
            # Response: '0' = slew started, '1' = object below horizon, '2' = object below limit
            if response == '0':
                logger.info(f"Slewing to RA={ra_hours:.4f}h, Dec={dec_degrees:.4f}°")
                return True
            else:
                logger.warning(f"Slew rejected: {response}")
                return False
        else:
            logger.warning("slew_to() not implemented in WiFi mode")
            return False
    
    def sync_position(self, ra_hours: float, dec_degrees: float):
        """
        Sync mount to solved plate position.
        
        This tells the mount "you're currently pointing at these coordinates",
        which improves pointing accuracy by correcting alignment errors.
        
        Args:
            ra_hours: Solved RA in decimal hours
            dec_degrees: Solved Dec in decimal degrees
        """
        if self.mode == ConnectionMode.SERIAL:
            # Set target RA
            ra_str = self._format_ra(ra_hours)
            self._send_lx200_serial(f":Sr{ra_str}#")
            
            # Set target Dec
            dec_str = self._format_dec(dec_degrees)
            self._send_lx200_serial(f":Sd{dec_str}#")
            
            # Sync
            self._send_lx200_serial(":CM#")
            
            logger.info(f"Synced to RA={ra_hours:.4f}h, Dec={dec_degrees:.4f}°")
        else:
            logger.warning("sync_position() not implemented in WiFi mode")
    
    def stop_slew(self):
        """Stop any ongoing slew"""
        if self.mode == ConnectionMode.SERIAL:
            self._send_lx200_serial(":Q#")  # Quit motion in all axes
            logger.info("Slew stopped")
        else:
            logger.warning("stop_slew() not implemented in WiFi mode")
    
    def _parse_ra(self, ra_str: str) -> float:
        """
        Parse RA string to decimal hours.
        
        Args:
            ra_str: RA in format "HH:MM:SS"
        
        Returns:
            RA in decimal hours
        """
        try:
            parts = ra_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours + minutes/60.0 + seconds/3600.0
        except (ValueError, IndexError):
            logger.error(f"Failed to parse RA: {ra_str}")
            return 0.0
    
    def _parse_dec(self, dec_str: str) -> float:
        """
        Parse Dec string to decimal degrees.
        
        Args:
            dec_str: Dec in format "±DD:MM:SS"
        
        Returns:
            Dec in decimal degrees
        """
        try:
            # Handle sign
            sign = 1.0
            if dec_str.startswith('-'):
                sign = -1.0
                dec_str = dec_str[1:]
            elif dec_str.startswith('+'):
                dec_str = dec_str[1:]
            
            parts = dec_str.split(':')
            degrees = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            
            return sign * (degrees + minutes/60.0 + seconds/3600.0)
        except (ValueError, IndexError):
            logger.error(f"Failed to parse Dec: {dec_str}")
            return 0.0
    
    def _format_ra(self, ra_hours: float) -> str:
        """
        Format RA from decimal hours to LX200 string.
        
        Args:
            ra_hours: RA in decimal hours
        
        Returns:
            RA string in format "HH:MM:SS"
        """
        ra_hours = ra_hours % 24.0  # Wrap to 0-24
        
        hours = int(ra_hours)
        minutes = int((ra_hours - hours) * 60.0)
        seconds = int(((ra_hours - hours) * 60.0 - minutes) * 60.0)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def _format_dec(self, dec_degrees: float) -> str:
        """
        Format Dec from decimal degrees to LX200 string.
        
        Args:
            dec_degrees: Dec in decimal degrees
        
        Returns:
            Dec string in format "±DD:MM:SS"
        """
        sign = '+' if dec_degrees >= 0 else '-'
        dec_degrees = abs(dec_degrees)
        
        degrees = int(dec_degrees)
        minutes = int((dec_degrees - degrees) * 60.0)
        seconds = int(((dec_degrees - degrees) * 60.0 - minutes) * 60.0)
        
        return f"{sign}{degrees:02d}:{minutes:02d}:{seconds:02d}"
    
    def close(self):
        """Close mount connection"""
        if self.connection:
            if self.mode == ConnectionMode.SERIAL:
                self.connection.close()
            else:
                self.connection.close()
            logger.info("Mount connection closed")


# Example usage and testing
if __name__ == "__main__":
    print("Testing OnStepX serial connection...")
    
    mount = MountConnection()
    
    if mount.mode == ConnectionMode.SERIAL:
        print("\n✓ Connected to OnStepX via serial")
        
        # Get current position
        ra, dec = mount.get_position()
        print(f"Current position: RA={ra:.4f}h, Dec={dec:.4f}°")
        
        # Sync to a test position (don't actually slew)
        print("\nSyncing to test position: RA=12.5h, Dec=45.0°")
        mount.sync_position(12.5, 45.0)
        
        # Verify sync worked
        ra, dec = mount.get_position()
        print(f"Position after sync: RA={ra:.4f}h, Dec={dec:.4f}°")
        
    elif mount.mode == ConnectionMode.WIFI:
        print("\n✓ WiFi LX200 server ready for SkySafari")
        print("Connect SkySafari to this device's IP on port 4060")
    
    mount.close()
    print("\nTest complete")
