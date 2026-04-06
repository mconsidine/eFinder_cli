<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eFinder - Status</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        h1 {
            color: #4CAF50;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .status-card {
            background: linear-gradient(135deg, #1a1f3a 0%, #2d3561 100%);
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        
        .status-card h2 {
            color: #4CAF50;
            font-size: 1.2em;
            margin-bottom: 15px;
            border-bottom: 2px solid rgba(76, 175, 80, 0.3);
            padding-bottom: 10px;
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .status-item:last-child {
            border-bottom: none;
        }
        
        .status-label {
            color: #9e9e9e;
        }
        
        .status-value {
            font-weight: 600;
            color: #ffffff;
        }
        
        .status-online {
            color: #4CAF50;
        }
        
        .status-offline {
            color: #f44336;
        }
        
        .system-info {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 6px;
            margin-top: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>eFinder Status Dashboard</h1>
        
        <?php include 'nav.php'; ?>
        
        <div class="status-grid">
            <div class="status-card">
                <h2>Mount Position</h2>
                <div class="status-item">
                    <span class="status-label">RA:</span>
                    <span class="status-value" id="ra">--:--:--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Dec:</span>
                    <span class="status-value" id="dec">--:--:--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Alt:</span>
                    <span class="status-value" id="alt">--°</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Az:</span>
                    <span class="status-value" id="az">--°</span>
                </div>
            </div>
            
            <div class="status-card">
                <h2>Plate Solving</h2>
                <div class="status-item">
                    <span class="status-label">Status:</span>
                    <span class="status-value" id="solve-status">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Last Solve:</span>
                    <span class="status-value" id="solve-time">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Solve Time:</span>
                    <span class="status-value" id="solve-duration">-- ms</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Success Rate:</span>
                    <span class="status-value" id="success-rate">--%</span>
                </div>
            </div>
            
            <div class="status-card">
                <h2>Mount Connection</h2>
                <div class="status-item">
                    <span class="status-label">Mode:</span>
                    <span class="status-value" id="mount-mode">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Status:</span>
                    <span class="status-value" id="mount-status">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Last Command:</span>
                    <span class="status-value" id="last-command">--</span>
                </div>
            </div>
            
            <div class="status-card">
                <h2>Focus Metrics</h2>
                <div class="status-item">
                    <span class="status-label">Focus Score:</span>
                    <span class="status-value" id="focus-score">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">FWHM:</span>
                    <span class="status-value" id="fwhm">-- px</span>
                </div>
                <div class="status-item">
                    <span class="status-label">HFD:</span>
                    <span class="status-value" id="hfd">-- px</span>
                </div>
                <div class="status-item">
                    <span class="status-label">SNR:</span>
                    <span class="status-value" id="snr">--</span>
                </div>
            </div>
            
            <div class="status-card">
                <h2>System Info</h2>
                <div class="status-item">
                    <span class="status-label">eFinder Process:</span>
                    <span class="status-value status-online" id="process-status">Running</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Uptime:</span>
                    <span class="status-value" id="uptime">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">CPU Temp:</span>
                    <span class="status-value" id="cpu-temp">--°C</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Memory:</span>
                    <span class="status-value" id="memory">--</span>
                </div>
            </div>
            
            <div class="status-card">
                <h2>Network</h2>
                <div class="status-item">
                    <span class="status-label">Hostname:</span>
                    <span class="status-value" id="hostname">efinder</span>
                </div>
                <div class="status-item">
                    <span class="status-label">WiFi Mode:</span>
                    <span class="status-value" id="wifi-mode">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">IP Address:</span>
                    <span class="status-value" id="ip-address">--</span>
                </div>
                <div class="status-item">
                    <span class="status-label">SSID:</span>
                    <span class="status-value" id="ssid">--</span>
                </div>
            </div>
        </div>
        
        <div class="status-card">
            <h2>Raw State Data</h2>
            <div class="system-info" id="raw-state">Loading...</div>
        </div>
    </div>
    
    <script src="efinder-common.js"></script>
    <script>
        function updateStatus() {
            fetch('api/state.php')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        // Mount position
                        document.getElementById('ra').textContent = formatRA(data.ra);
                        document.getElementById('dec').textContent = formatDec(data.dec);
                        document.getElementById('alt').textContent = (data.alt || 0).toFixed(1) + '°';
                        document.getElementById('az').textContent = (data.az || 0).toFixed(1) + '°';
                        
                        // Plate solving
                        document.getElementById('solve-status').textContent = data.solve_status || 'Unknown';
                        document.getElementById('solve-time').textContent = formatTimestamp(data.solve_timestamp);
                        document.getElementById('solve-duration').textContent = (data.solve_duration || 0) + ' ms';
                        document.getElementById('success-rate').textContent = (data.solve_success_rate || 0) + '%';
                        
                        // Mount connection
                        document.getElementById('mount-mode').textContent = data.mount_mode || 'Unknown';
                        document.getElementById('mount-status').textContent = data.mount_connected ? 'Connected' : 'Disconnected';
                        document.getElementById('last-command').textContent = data.last_mount_command || '--';
                        
                        // Focus
                        if (data.focus_score) {
                            document.getElementById('focus-score').textContent = data.focus_score.toFixed(1);
                            document.getElementById('fwhm').textContent = (data.focus_fwhm || 0).toFixed(2) + ' px';
                            document.getElementById('hfd').textContent = (data.focus_hfd || 0).toFixed(2) + ' px';
                            document.getElementById('snr').textContent = (data.focus_snr || 0).toFixed(1);
                        }
                        
                        // System
                        document.getElementById('uptime').textContent = formatTimestamp(data.start_timestamp);
                        document.getElementById('cpu-temp').textContent = (data.cpu_temp || 0).toFixed(1) + '°C';
                        document.getElementById('memory').textContent = (data.memory_usage || 0) + ' MB';
                        
                        // Network
                        document.getElementById('wifi-mode').textContent = data.wifi_mode || '--';
                        document.getElementById('ip-address').textContent = data.ip_address || '--';
                        document.getElementById('ssid').textContent = data.ssid || '--';
                        
                        // Raw state
                        document.getElementById('raw-state').textContent = JSON.stringify(data, null, 2);
                        
                        // Update process status
                        document.getElementById('process-status').className = 'status-value status-online';
                    } else {
                        document.getElementById('process-status').className = 'status-value status-offline';
                        document.getElementById('process-status').textContent = 'Not Running';
                    }
                })
                .catch(err => {
                    console.error('Status update failed:', err);
                    document.getElementById('process-status').className = 'status-value status-offline';
                    document.getElementById('process-status').textContent = 'Error';
                });
        }
        
        // Initial update
        updateStatus();
        
        // Update every 2 seconds
        setInterval(updateStatus, 2000);
    </script>
</body>
</html>
