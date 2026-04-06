/**
 * efinder-common.js - Shared JavaScript utilities for eFinder web interface
 * 
 * Provides common functions used across all pages:
 * - State file reading
 * - API helpers
 * - Formatting utilities
 */

// API base path
const API_BASE = 'api/';

/**
 * Read eFinder state from shared JSON file
 * State is written by eFinder_cedar_v2.py to RAM disk
 */
function readState() {
    return fetch(API_BASE + 'state.php')
        .then(response => {
            if (!response.ok) {
                throw new Error('State read failed');
            }
            return response.json();
        })
        .catch(err => {
            console.error('Failed to read state:', err);
            return null;
        });
}

/**
 * Format RA from decimal hours to HH:MM:SS
 */
function formatRA(raHours) {
    if (raHours === null || raHours === undefined) return '--:--:--';
    
    raHours = parseFloat(raHours);
    if (isNaN(raHours)) return '--:--:--';
    
    raHours = raHours % 24; // Wrap to 0-24
    if (raHours < 0) raHours += 24;
    
    const hours = Math.floor(raHours);
    const minutes = Math.floor((raHours - hours) * 60);
    const seconds = Math.floor(((raHours - hours) * 60 - minutes) * 60);
    
    return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)}`;
}

/**
 * Format Dec from decimal degrees to ±DD:MM:SS
 */
function formatDec(decDegrees) {
    if (decDegrees === null || decDegrees === undefined) return '--:--:--';
    
    decDegrees = parseFloat(decDegrees);
    if (isNaN(decDegrees)) return '--:--:--';
    
    const sign = decDegrees >= 0 ? '+' : '-';
    decDegrees = Math.abs(decDegrees);
    
    const degrees = Math.floor(decDegrees);
    const minutes = Math.floor((decDegrees - degrees) * 60);
    const seconds = Math.floor(((decDegrees - degrees) * 60 - minutes) * 60);
    
    return `${sign}${pad(degrees, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)}`;
}

/**
 * Zero-pad number
 */
function pad(num, length) {
    return String(num).padStart(length, '0');
}

/**
 * Format timestamp as human-readable string
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '--';
    
    const date = new Date(timestamp * 1000); // Unix timestamp to JS Date
    const now = new Date();
    const diff = Math.floor((now - date) / 1000); // seconds ago
    
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    
    return date.toLocaleString();
}

/**
 * Show notification toast
 */
function showNotification(message, type = 'info') {
    // Simple notification - in production you'd use a proper library
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
        color: white;
        padding: 15px 25px;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 10000;
        max-width: 300px;
        animation: slideIn 0.3s ease;
    `;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Add animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
