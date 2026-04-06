#!/usr/bin/env python3
"""
alignment_calibration.py - eFinder Alignment Calibration Wizard

Measures the offset between eFinder optical axis and main telescope optical axis.
Stores calibration data in eFinder.config as d_x and d_y values.

Usage:
    1. Slew to bright star
    2. Center star in main telescope eyepiece
    3. Capture calibration sample
    4. Repeat at different part of sky
    5. Calculate average offset
    6. Save to config
"""

import numpy as np
from typing import List, Tuple, Dict, Optional
import logging
import configparser
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AlignmentSample:
    """Single calibration sample"""
    
    def __init__(
        self, 
        target_ra: float, 
        target_dec: float, 
        solved_ra: float, 
        solved_dec: float,
        alt: float,
        az: float
    ):
        """
        Args:
            target_ra: Where telescope is pointing (hours)
            target_dec: Where telescope is pointing (degrees)
            solved_ra: Where eFinder is actually pointing (hours)
            solved_dec: Where eFinder is actually pointing (degrees)
            alt: Altitude when sample taken (degrees)
            az: Azimuth when sample taken (degrees)
        """
        self.target_ra = target_ra
        self.target_dec = target_dec
        self.solved_ra = solved_ra
        self.solved_dec = solved_dec
        self.alt = alt
        self.az = az
        
        # Calculate offset in arcseconds
        self.offset_ra_arcsec = (solved_ra - target_ra) * 15.0 * 3600.0  # hours → arcsec
        self.offset_dec_arcsec = (solved_dec - target_dec) * 3600.0      # deg → arcsec
        
        # Angular separation
        self.offset_magnitude = np.sqrt(
            self.offset_ra_arcsec**2 + self.offset_dec_arcsec**2
        )
    
    def __repr__(self):
        return (
            f"Sample(target=[{self.target_ra:.4f}h, {self.target_dec:.4f}°], "
            f"offset=[{self.offset_ra_arcsec:.1f}\", {self.offset_dec_arcsec:.1f}\"], "
            f"mag={self.offset_magnitude:.1f}\")"
        )


class AlignmentCalibrator:
    """Manages alignment calibration workflow"""
    
    def __init__(self, config_path="/home/efinder/Solver/eFinder.config"):
        """
        Initialize calibrator.
        
        Args:
            config_path: Path to eFinder.config file
        """
        self.config_path = Path(config_path)
        self.samples: List[AlignmentSample] = []
        self.current_offset_ra = 0.0  # arcsec
        self.current_offset_dec = 0.0  # arcsec
        
        # Load existing offset from config
        self._load_current_offset()
    
    def _load_current_offset(self):
        """Load current d_x, d_y from config file"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return
        
        try:
            config = configparser.ConfigParser()
            config.read(self.config_path)
            
            # d_x and d_y are in arcseconds
            if 'alignment' in config:
                self.current_offset_ra = config.getfloat('alignment', 'd_x', fallback=0.0)
                self.current_offset_dec = config.getfloat('alignment', 'd_y', fallback=0.0)
            
            logger.info(
                f"Current offset: RA={self.current_offset_ra:.1f}\", "
                f"Dec={self.current_offset_dec:.1f}\""
            )
        except Exception as e:
            logger.error(f"Failed to load current offset: {e}")
    
    def add_sample(
        self,
        target_ra: float,
        target_dec: float,
        solved_ra: float,
        solved_dec: float,
        alt: float = 0.0,
        az: float = 0.0
    ):
        """
        Add calibration sample.
        
        Args:
            target_ra: Telescope pointing RA (hours)
            target_dec: Telescope pointing Dec (degrees)
            solved_ra: eFinder plate-solved RA (hours)
            solved_dec: eFinder plate-solved Dec (degrees)
            alt: Altitude (degrees)
            az: Azimuth (degrees)
        """
        sample = AlignmentSample(
            target_ra, target_dec, 
            solved_ra, solved_dec,
            alt, az
        )
        
        self.samples.append(sample)
        
        logger.info(f"Sample {len(self.samples)} added: {sample}")
        
        return sample
    
    def calculate_offset(self) -> Optional[Tuple[float, float]]:
        """
        Calculate average offset from all samples.
        
        Returns:
            (offset_ra_arcsec, offset_dec_arcsec) or None if insufficient samples
        """
        if len(self.samples) < 2:
            logger.warning("Need at least 2 samples for calibration")
            return None
        
        # Simple average
        offset_ra = np.mean([s.offset_ra_arcsec for s in self.samples])
        offset_dec = np.mean([s.offset_dec_arcsec for s in self.samples])
        
        # Calculate standard deviation (measure of consistency)
        std_ra = np.std([s.offset_ra_arcsec for s in self.samples])
        std_dec = np.std([s.offset_dec_arcsec for s in self.samples])
        
        logger.info(
            f"\nCalibration result ({len(self.samples)} samples):"
        )
        logger.info(f"  RA offset:  {offset_ra:.1f}\" ± {std_ra:.1f}\"")
        logger.info(f"  Dec offset: {offset_dec:.1f}\" ± {std_dec:.1f}\"")
        
        # Warn if standard deviation is high (inconsistent samples)
        if std_ra > 30.0 or std_dec > 30.0:
            logger.warning(
                "High variance in samples - may indicate poor plate solves "
                "or telescope not centered properly"
            )
        
        return offset_ra, offset_dec
    
    def save_offset(self, offset_ra: float, offset_dec: float):
        """
        Save calibrated offset to config file.
        
        Args:
            offset_ra: RA offset in arcseconds
            offset_dec: Dec offset in arcseconds
        """
        if not self.config_path.exists():
            logger.error(f"Config file not found: {self.config_path}")
            return False
        
        try:
            config = configparser.ConfigParser()
            config.read(self.config_path)
            
            # Ensure [alignment] section exists
            if 'alignment' not in config:
                config.add_section('alignment')
            
            # Update d_x and d_y
            config.set('alignment', 'd_x', f"{offset_ra:.2f}")
            config.set('alignment', 'd_y', f"{offset_dec:.2f}")
            
            # Write back
            with open(self.config_path, 'w') as f:
                config.write(f)
            
            logger.info(f"Offset saved to {self.config_path}")
            logger.info(f"  d_x = {offset_ra:.2f} arcsec")
            logger.info(f"  d_y = {offset_dec:.2f} arcsec")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save offset: {e}")
            return False
    
    def get_sample_stats(self) -> Dict:
        """
        Get statistics about calibration samples.
        
        Returns:
            Dict with sample statistics
        """
        if not self.samples:
            return {'count': 0}
        
        offsets_ra = [s.offset_ra_arcsec for s in self.samples]
        offsets_dec = [s.offset_dec_arcsec for s in self.samples]
        magnitudes = [s.offset_magnitude for s in self.samples]
        
        return {
            'count': len(self.samples),
            'mean_offset_ra': np.mean(offsets_ra),
            'mean_offset_dec': np.mean(offsets_dec),
            'std_offset_ra': np.std(offsets_ra),
            'std_offset_dec': np.std(offsets_dec),
            'mean_magnitude': np.mean(magnitudes),
            'max_magnitude': np.max(magnitudes),
            'min_magnitude': np.min(magnitudes)
        }
    
    def clear_samples(self):
        """Clear all calibration samples"""
        self.samples.clear()
        logger.info("All samples cleared")
    
    def remove_outlier(self):
        """Remove the sample with largest offset (outlier detection)"""
        if len(self.samples) < 3:
            logger.warning("Need at least 3 samples to remove outlier")
            return
        
        # Find sample with largest deviation from mean
        mean_ra = np.mean([s.offset_ra_arcsec for s in self.samples])
        mean_dec = np.mean([s.offset_dec_arcsec for s in self.samples])
        
        max_deviation = 0
        outlier_idx = 0
        
        for i, sample in enumerate(self.samples):
            deviation = np.sqrt(
                (sample.offset_ra_arcsec - mean_ra)**2 +
                (sample.offset_dec_arcsec - mean_dec)**2
            )
            
            if deviation > max_deviation:
                max_deviation = deviation
                outlier_idx = i
        
        removed = self.samples.pop(outlier_idx)
        logger.info(f"Removed outlier: {removed}")


# Web API integration
class CalibrationWizard:
    """
    Web-based calibration wizard workflow.
    
    States: idle → collecting → complete
    """
    
    def __init__(self):
        self.calibrator = AlignmentCalibrator()
        self.state = "idle"
        self.target_samples = 3  # Recommend 3 samples minimum
    
    def start_calibration(self, target_samples: int = 3):
        """Start new calibration session"""
        self.calibrator.clear_samples()
        self.state = "collecting"
        self.target_samples = max(2, target_samples)
        
        return {
            'status': 'started',
            'target_samples': self.target_samples,
            'instructions': [
                'Slew to a bright star in the east',
                'Center star precisely in eyepiece',
                'Click "Capture Sample 1"'
            ]
        }
    
    def capture_sample(
        self,
        target_ra: float,
        target_dec: float,
        solved_ra: float,
        solved_dec: float,
        alt: float = 0.0,
        az: float = 0.0
    ) -> Dict:
        """
        Capture calibration sample.
        
        Returns:
            Dict with sample info and next instructions
        """
        if self.state != "collecting":
            return {'status': 'error', 'message': 'No calibration in progress'}
        
        sample = self.calibrator.add_sample(
            target_ra, target_dec,
            solved_ra, solved_dec,
            alt, az
        )
        
        sample_num = len(self.calibrator.samples)
        
        response = {
            'status': 'sample_added',
            'sample_number': sample_num,
            'total_required': self.target_samples,
            'offset_ra': round(sample.offset_ra_arcsec, 1),
            'offset_dec': round(sample.offset_dec_arcsec, 1),
            'offset_magnitude': round(sample.offset_magnitude, 1)
        }
        
        if sample_num < self.target_samples:
            # Need more samples
            response['instructions'] = [
                f'Good! Sample {sample_num}/{self.target_samples} captured',
                'Slew to different part of sky (different altitude)',
                'Center new star in eyepiece',
                f'Click "Capture Sample {sample_num + 1}"'
            ]
        else:
            # Enough samples, ready to calculate
            self.state = "complete"
            response['status'] = 'ready_to_calculate'
            response['instructions'] = [
                f'All {self.target_samples} samples captured!',
                'Review samples below',
                'Click "Calculate Offset" to finish'
            ]
        
        return response
    
    def calculate_and_save(self) -> Dict:
        """Calculate offset and save to config"""
        if self.state != "complete":
            return {'status': 'error', 'message': 'Not ready to calculate'}
        
        result = self.calibrator.calculate_offset()
        
        if result is None:
            return {
                'status': 'error',
                'message': 'Insufficient samples'
            }
        
        offset_ra, offset_dec = result
        
        # Save to config
        success = self.calibrator.save_offset(offset_ra, offset_dec)
        
        if success:
            self.state = "idle"
            
            stats = self.calibrator.get_sample_stats()
            
            return {
                'status': 'success',
                'offset_ra': round(offset_ra, 1),
                'offset_dec': round(offset_dec, 1),
                'std_ra': round(stats['std_offset_ra'], 1),
                'std_dec': round(stats['std_offset_dec'], 1),
                'message': 'Calibration saved to eFinder.config'
            }
        else:
            return {
                'status': 'error',
                'message': 'Failed to save calibration'
            }
    
    def get_status(self) -> Dict:
        """Get current calibration status"""
        stats = self.calibrator.get_sample_stats()
        
        return {
            'state': self.state,
            'sample_count': stats.get('count', 0),
            'target_samples': self.target_samples,
            'samples': [
                {
                    'number': i + 1,
                    'offset_ra': round(s.offset_ra_arcsec, 1),
                    'offset_dec': round(s.offset_dec_arcsec, 1),
                    'magnitude': round(s.offset_magnitude, 1)
                }
                for i, s in enumerate(self.calibrator.samples)
            ],
            'current_offset_ra': self.calibrator.current_offset_ra,
            'current_offset_dec': self.calibrator.current_offset_dec
        }


# Example usage
if __name__ == "__main__":
    print("Alignment Calibration Wizard - Test\n")
    
    wizard = CalibrationWizard()
    
    # Start calibration
    result = wizard.start_calibration(target_samples=3)
    print(f"Status: {result['status']}")
    print(f"Instructions: {result['instructions']}\n")
    
    # Simulate 3 calibration samples
    # Sample 1: East, low altitude
    print("Sample 1:")
    result = wizard.capture_sample(
        target_ra=6.5, target_dec=30.0,     # Where telescope thinks it's pointing
        solved_ra=6.502, solved_dec=30.05,  # Where eFinder actually sees
        alt=30.0, az=90.0
    )
    print(f"  Offset: RA={result['offset_ra']}\", Dec={result['offset_dec']}\"")
    print(f"  {result['instructions'][0]}\n")
    
    # Sample 2: South, high altitude
    print("Sample 2:")
    result = wizard.capture_sample(
        target_ra=12.0, target_dec=60.0,
        solved_ra=12.003, solved_dec=60.04,
        alt=70.0, az=180.0
    )
    print(f"  Offset: RA={result['offset_ra']}\", Dec={result['offset_dec']}\"")
    print(f"  {result['instructions'][0]}\n")
    
    # Sample 3: West, medium altitude
    print("Sample 3:")
    result = wizard.capture_sample(
        target_ra=18.5, target_dec=45.0,
        solved_ra=18.504, solved_dec=45.05,
        alt=50.0, az=270.0
    )
    print(f"  Offset: RA={result['offset_ra']}\", Dec={result['offset_dec']}\"")
    print(f"  Status: {result['status']}\n")
    
    # Calculate final offset
    print("Calculating final offset:")
    result = wizard.calculate_and_save()
    
    if result['status'] == 'success':
        print(f"  ✓ Calibration complete!")
        print(f"  RA offset:  {result['offset_ra']}\" ± {result['std_ra']}\"")
        print(f"  Dec offset: {result['offset_dec']}\" ± {result['std_dec']}\"")
        print(f"  {result['message']}")
    else:
        print(f"  ✗ {result['message']}")
