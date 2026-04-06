#!/usr/bin/env python3
"""
focus_assist.py - Focus Assistance Module for eFinder

Analyzes star images to provide real-time focus quality metrics:
- FWHM (Full Width Half Maximum) - star sharpness
- HFD (Half-Flux Diameter) - robust focus measure
- Peak intensity and SNR
- Focus quality score (0-100)

Integrates with web interface for live focus feedback.
"""

import numpy as np
from scipy import ndimage, optimize
from typing import Tuple, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FocusAnalyzer:
    """Analyzes captured images for focus quality"""
    
    def __init__(self, threshold_sigma=3.0):
        """
        Initialize focus analyzer.
        
        Args:
            threshold_sigma: Star detection threshold (sigma above background)
        """
        self.threshold_sigma = threshold_sigma
        self.history = []  # Track focus metrics over time
        self.max_history = 100
    
    def find_brightest_star(self, image: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Find the brightest star in the image.
        
        Args:
            image: 2D numpy array (grayscale image)
        
        Returns:
            (x, y) coordinates of brightest star, or None if not found
        """
        # Estimate background
        background = np.median(image)
        noise = np.std(image)
        
        # Threshold image
        threshold = background + self.threshold_sigma * noise
        binary = image > threshold
        
        # Label connected components (stars)
        labeled, num_features = ndimage.label(binary)
        
        if num_features == 0:
            logger.warning("No stars detected in image")
            return None
        
        # Find brightest star
        max_intensity = 0
        brightest_label = 0
        
        for label in range(1, num_features + 1):
            mask = labeled == label
            intensity = np.sum(image[mask])
            
            if intensity > max_intensity:
                max_intensity = intensity
                brightest_label = label
        
        # Get centroid of brightest star
        mask = labeled == brightest_label
        y_coords, x_coords = np.where(mask)
        
        if len(x_coords) == 0:
            return None
        
        # Intensity-weighted centroid
        weights = image[y_coords, x_coords]
        x = int(np.average(x_coords, weights=weights))
        y = int(np.average(y_coords, weights=weights))
        
        return x, y
    
    def extract_star_region(
        self, 
        image: np.ndarray, 
        x: int, 
        y: int, 
        radius: int = 20
    ) -> Optional[np.ndarray]:
        """
        Extract square region around star.
        
        Args:
            image: Full image
            x, y: Star center coordinates
            radius: Half-width of extraction box
        
        Returns:
            Extracted region, or None if out of bounds
        """
        height, width = image.shape
        
        x_min = max(0, x - radius)
        x_max = min(width, x + radius)
        y_min = max(0, y - radius)
        y_max = min(height, y + radius)
        
        if x_max - x_min < 10 or y_max - y_min < 10:
            return None
        
        return image[y_min:y_max, x_min:x_max].copy()
    
    def calculate_fwhm(self, star_region: np.ndarray) -> float:
        """
        Calculate Full Width Half Maximum.
        
        FWHM measures star sharpness. Lower values = better focus.
        Typical range: 1.5-8 pixels for well-focused stars.
        
        Args:
            star_region: Small image cutout containing star
        
        Returns:
            FWHM in pixels
        """
        # Find peak and background
        peak = np.max(star_region)
        background = np.median(star_region)
        
        # Half-maximum threshold
        half_max = (peak + background) / 2.0
        
        # Count pixels above half-max
        above_half = star_region > half_max
        area = np.sum(above_half)
        
        # Estimate FWHM from area assuming circular PSF
        # Area = π * (FWHM/2)^2
        # FWHM = 2 * sqrt(Area / π)
        fwhm = 2.0 * np.sqrt(area / np.pi)
        
        return fwhm
    
    def calculate_hfd(self, star_region: np.ndarray) -> float:
        """
        Calculate Half-Flux Diameter (HFD).
        
        HFD is more robust to noise than FWHM. It measures the diameter
        containing 50% of the star's total flux.
        
        Args:
            star_region: Small image cutout containing star
        
        Returns:
            HFD in pixels
        """
        height, width = star_region.shape
        center_y, center_x = height // 2, width // 2
        
        # Subtract background
        background = np.median(star_region)
        star_region = np.maximum(0, star_region - background)
        
        total_flux = np.sum(star_region)
        
        if total_flux < 1e-6:
            return 0.0
        
        # Calculate flux-weighted centroid
        y_coords, x_coords = np.mgrid[0:height, 0:width]
        cx = np.sum(star_region * x_coords) / total_flux
        cy = np.sum(star_region * y_coords) / total_flux
        
        # Calculate distances from centroid
        dx = x_coords - cx
        dy = y_coords - cy
        distances = np.sqrt(dx**2 + dy**2)
        
        # Sort pixels by distance
        flat_dist = distances.flatten()
        flat_flux = star_region.flatten()
        
        sort_idx = np.argsort(flat_dist)
        sorted_dist = flat_dist[sort_idx]
        sorted_flux = flat_flux[sort_idx]
        
        # Find radius containing 50% of flux
        cumulative_flux = np.cumsum(sorted_flux)
        half_flux = total_flux / 2.0
        
        idx = np.searchsorted(cumulative_flux, half_flux)
        
        if idx >= len(sorted_dist):
            idx = len(sorted_dist) - 1
        
        hfd = 2.0 * sorted_dist[idx]  # Diameter, not radius
        
        return hfd
    
    def calculate_snr(self, star_region: np.ndarray) -> float:
        """
        Calculate signal-to-noise ratio.
        
        Args:
            star_region: Small image cutout containing star
        
        Returns:
            SNR (dimensionless)
        """
        peak = np.max(star_region)
        
        # Estimate noise from outer annulus
        height, width = star_region.shape
        y, x = np.mgrid[0:height, 0:width]
        center_y, center_x = height // 2, width // 2
        
        r = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        
        # Annulus between radius 0.6*max and 0.9*max
        max_r = min(height, width) / 2
        annulus = (r > 0.6 * max_r) & (r < 0.9 * max_r)
        
        if np.sum(annulus) > 0:
            noise = np.std(star_region[annulus])
        else:
            noise = np.std(star_region)
        
        if noise < 1e-6:
            noise = 1.0
        
        snr = peak / noise
        
        return snr
    
    def calculate_focus_score(self, metrics: Dict) -> float:
        """
        Calculate overall focus quality score (0-100).
        
        Score combines FWHM, HFD, and SNR into single metric.
        Higher is better.
        
        Args:
            metrics: Dict with 'fwhm', 'hfd', 'snr', 'peak' keys
        
        Returns:
            Focus score 0-100
        """
        fwhm = metrics.get('fwhm', 10.0)
        hfd = metrics.get('hfd', 10.0)
        snr = metrics.get('snr', 1.0)
        
        # Ideal FWHM: 2.0 pixels, HFD: 3.0 pixels
        # Score decreases as we deviate from ideal
        
        # FWHM component (0-40 points)
        fwhm_ideal = 2.0
        fwhm_score = 40.0 * np.exp(-((fwhm - fwhm_ideal) / 2.0)**2)
        
        # HFD component (0-40 points)
        hfd_ideal = 3.0
        hfd_score = 40.0 * np.exp(-((hfd - hfd_ideal) / 2.0)**2)
        
        # SNR component (0-20 points)
        # Good SNR > 50, excellent > 100
        snr_score = 20.0 * min(1.0, snr / 100.0)
        
        total_score = fwhm_score + hfd_score + snr_score
        
        return min(100.0, max(0.0, total_score))
    
    def analyze_focus(self, image: np.ndarray) -> Optional[Dict]:
        """
        Complete focus analysis on an image.
        
        Args:
            image: Grayscale image array
        
        Returns:
            Dict with metrics: {
                'x', 'y': star position
                'fwhm': Full Width Half Maximum (pixels)
                'hfd': Half-Flux Diameter (pixels)
                'peak': Peak intensity (ADU)
                'snr': Signal-to-noise ratio
                'score': Overall focus quality (0-100)
            }
            or None if analysis failed
        """
        # Find brightest star
        star_pos = self.find_brightest_star(image)
        
        if star_pos is None:
            return None
        
        x, y = star_pos
        
        # Extract star region
        star_region = self.extract_star_region(image, x, y, radius=20)
        
        if star_region is None:
            return None
        
        # Calculate metrics
        try:
            fwhm = self.calculate_fwhm(star_region)
            hfd = self.calculate_hfd(star_region)
            snr = self.calculate_snr(star_region)
            peak = np.max(star_region)
            
            metrics = {
                'x': x,
                'y': y,
                'fwhm': fwhm,
                'hfd': hfd,
                'peak': float(peak),
                'snr': snr,
                'star_cutout': star_region  # For display
            }
            
            # Calculate composite score
            metrics['score'] = self.calculate_focus_score(metrics)
            
            # Add to history
            self.history.append({
                'fwhm': fwhm,
                'hfd': hfd,
                'snr': snr,
                'score': metrics['score']
            })
            
            # Trim history
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            
            return metrics
            
        except Exception as e:
            logger.error(f"Focus analysis failed: {e}")
            return None
    
    def get_focus_trend(self) -> str:
        """
        Analyze focus trend from history.
        
        Returns:
            "improving", "degrading", "stable", or "insufficient_data"
        """
        if len(self.history) < 5:
            return "insufficient_data"
        
        # Look at last 10 samples
        recent = self.history[-10:]
        scores = [h['score'] for h in recent]
        
        # Linear regression on scores
        x = np.arange(len(scores))
        slope, _ = np.polyfit(x, scores, 1)
        
        # Threshold for "significant" trend
        if slope > 1.0:
            return "improving"
        elif slope < -1.0:
            return "degrading"
        else:
            return "stable"


# Web API integration
def focus_api_handler(image: np.ndarray) -> dict:
    """
    Handler for web API focus endpoint.
    
    Args:
        image: Captured image from camera
    
    Returns:
        JSON-serializable dict with focus metrics
    """
    analyzer = FocusAnalyzer()
    metrics = analyzer.analyze_focus(image)
    
    if metrics is None:
        return {
            'status': 'error',
            'message': 'No stars detected in image'
        }
    
    # Don't send star_cutout over API (too large)
    result = {
        'status': 'success',
        'x': metrics['x'],
        'y': metrics['y'],
        'fwhm': round(metrics['fwhm'], 2),
        'hfd': round(metrics['hfd'], 2),
        'peak': int(metrics['peak']),
        'snr': round(metrics['snr'], 1),
        'score': round(metrics['score'], 1),
        'trend': analyzer.get_focus_trend()
    }
    
    return result


# Example usage
if __name__ == "__main__":
    print("Focus Assist Module - Test")
    
    # Create synthetic star image for testing
    from scipy import signal
    
    size = 100
    y, x = np.mgrid[0:size, 0:size]
    
    # Gaussian star with FWHM=3 pixels
    fwhm = 3.0
    sigma = fwhm / 2.355
    
    center_x, center_y = 50, 50
    star = 1000.0 * np.exp(-((x - center_x)**2 + (y - center_y)**2) / (2 * sigma**2))
    
    # Add noise
    noise = np.random.normal(0, 10, (size, size))
    image = star + noise + 100  # Background = 100
    
    # Analyze
    analyzer = FocusAnalyzer()
    metrics = analyzer.analyze_focus(image)
    
    if metrics:
        print("\nFocus Metrics:")
        print(f"  Star position: ({metrics['x']}, {metrics['y']})")
        print(f"  FWHM: {metrics['fwhm']:.2f} pixels")
        print(f"  HFD: {metrics['hfd']:.2f} pixels")
        print(f"  Peak: {metrics['peak']:.0f} ADU")
        print(f"  SNR: {metrics['snr']:.1f}")
        print(f"  Focus Score: {metrics['score']:.1f}/100")
        
        if metrics['score'] > 80:
            print("\n  ✓ Excellent focus!")
        elif metrics['score'] > 60:
            print("\n  → Good focus, minor adjustment possible")
        else:
            print("\n  ✗ Poor focus - adjustment needed")
    else:
        print("\n✗ Analysis failed")
