<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eFinder - Live View</title>
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
        
        .info-panel {
            background: linear-gradient(135deg, #1a1f3a 0%, #2d3561 100%);
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        
        .info-item {
            background: rgba(255,255,255,0.05);
            padding: 12px;
            border-radius: 6px;
            border-left: 3px solid #4CAF50;
        }
        
        .info-label {
            font-size: 0.85em;
            color: #9e9e9e;
            margin-bottom: 5px;
        }
        
        .info-value {
            font-size: 1.2em;
            font-weight: 600;
            color: #ffffff;
        }
        
        .video-container {
            background: #000;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            margin-bottom: 20px;
            position: relative;
        }
        
        #liveStream {
            width: 100%;
            height: auto;
            display: block;
        }
        
        .stream-overlay {
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(0,0,0,0.7);
            color: #4CAF50;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: 600;
        }
        
        .stream-controls {
            background: linear-gradient(135deg, #1a1f3a 0%, #2d3561 100%);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 6px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 5px;
        }
        
        .btn:hover {
            background: #45a049;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(76, 175, 80, 0.4);
        }
        
        .btn:disabled {
            background: #555;
            cursor: not-allowed;
            transform: none;
        }
        
        .btn-stop {
            background: #f44336;
        }
        
        .btn-stop:hover {
            background: #da190b;
        }
        
        .frame-counter {
            display: inline-block;
            margin-left: 15px;
            color: #9e9e9e;
            font-size: 0.9em;
        }
        
        .warning {
            background: rgba(255, 152, 0, 0.2);
            border: 1px solid #ff9800;
            color: #ffb74d;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 15px;
        }
        
        @media (max-width: 768px) {
            .info-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>eFinder Live View</h1>
        
        <?php include 'nav.php'; ?>
        
        <div class="info-panel">
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">RA Position</div>
                    <div class="info-value" id="ra-pos">--:--:--</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Dec Position</div>
                    <div class="info-value" id="dec-pos">--:--:--</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Last Solve</div>
                    <div class="info-value" id="solve-time">--</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Solve Status</div>
                    <div class="info-value" id="solve-status">Idle</div>
                </div>
            </div>
        </div>
        
        <div class="stream-controls">
            <button class="btn" id="startBtn" onclick="startStream()">Start Live View</button>
            <button class="btn btn-stop" id="stopBtn" onclick="stopStream()" disabled>Stop Live View</button>
            <span class="frame-counter" id="frameCounter"></span>
        </div>
        
        <div class="warning">
            ℹ️ Live view is limited to 1000 frames per session to prevent resource exhaustion. 
            Refresh the page to start a new session.
        </div>
        
        <div class="video-container" id="videoContainer" style="display: none;">
            <img id="liveStream" alt="Live camera feed">
            <div class="stream-overlay">● LIVE</div>
        </div>
    </div>
    
    <script src="efinder-common.js"></script>
    <script>
        let streamActive = false;
        let frameCount = 0;
        let maxFrames = 1000;
        let statusUpdateInterval = null;
        
        function startStream() {
            const img = document.getElementById('liveStream');
            const container = document.getElementById('videoContainer');
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            
            // Add timestamp to prevent caching
            img.src = 'stream.php?t=' + new Date().getTime();
            
            container.style.display = 'block';
            streamActive = true;
            frameCount = 0;
            
            startBtn.disabled = true;
            stopBtn.disabled = false;
            
            // Monitor frame count
            img.onload = function() {
                frameCount++;
                updateFrameCounter();
                
                if (frameCount >= maxFrames) {
                    stopStream();
                    alert('Live view session ended: 1000 frame limit reached.\nRefresh page to start new session.');
                }
            };
            
            // Start status updates
            if (!statusUpdateInterval) {
                statusUpdateInterval = setInterval(updateStatus, 2000);
            }
        }
        
        function stopStream() {
            const img = document.getElementById('liveStream');
            const container = document.getElementById('videoContainer');
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            
            // Stop stream by removing src
            img.src = '';
            
            container.style.display = 'none';
            streamActive = false;
            
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
        
        function updateFrameCounter() {
            const counter = document.getElementById('frameCounter');
            const remaining = maxFrames - frameCount;
            counter.textContent = `Frames: ${frameCount} / ${maxFrames} (${remaining} remaining)`;
        }
        
        function updateStatus() {
            fetch('api/status.php')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        document.getElementById('ra-pos').textContent = data.ra || '--:--:--';
                        document.getElementById('dec-pos').textContent = data.dec || '--:--:--';
                        document.getElementById('solve-time').textContent = data.solve_time || '--';
                        document.getElementById('solve-status').textContent = data.solve_status || 'Idle';
                    }
                })
                .catch(err => console.error('Status update failed:', err));
        }
        
        // Initial status update
        updateStatus();
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', function() {
            if (streamActive) {
                stopStream();
            }
            if (statusUpdateInterval) {
                clearInterval(statusUpdateInterval);
            }
        });
    </script>
</body>
</html>
