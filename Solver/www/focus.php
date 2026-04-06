<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eFinder - Focus Assist</title>
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
        
        .focus-panel {
            background: linear-gradient(135deg, #1a1f3a 0%, #2d3561 100%);
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        
        .focus-score {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .score-value {
            font-size: 4em;
            font-weight: 700;
            margin: 10px 0;
        }
        
        .score-label {
            font-size: 1.2em;
            color: #9e9e9e;
        }
        
        .score-excellent { color: #4CAF50; }
        .score-good { color: #8BC34A; }
        .score-fair { color: #FFC107; }
        .score-poor { color: #FF9800; }
        .score-bad { color: #f44336; }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .metric-card {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border-top: 3px solid #4CAF50;
        }
        
        .metric-label {
            font-size: 0.9em;
            color: #9e9e9e;
            margin-bottom: 10px;
        }
        
        .metric-value {
            font-size: 2em;
            font-weight: 600;
            color: #ffffff;
        }
        
        .metric-unit {
            font-size: 0.5em;
            color: #9e9e9e;
            margin-left: 5px;
        }
        
        .trend-indicator {
            display: inline-block;
            margin-left: 10px;
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.85em;
            font-weight: 600;
        }
        
        .trend-improving {
            background: rgba(76, 175, 80, 0.3);
            color: #4CAF50;
        }
        
        .trend-degrading {
            background: rgba(244, 67, 54, 0.3);
            color: #f44336;
        }
        
        .trend-stable {
            background: rgba(33, 150, 243, 0.3);
            color: #2196F3;
        }
        
        .controls {
            text-align: center;
            margin-bottom: 20px;
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
        
        .info-box {
            background: rgba(33, 150, 243, 0.2);
            border: 1px solid #2196F3;
            color: #90CAF9;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
        }
        
        .history-chart {
            background: rgba(0,0,0,0.3);
            padding: 15px;
            border-radius: 8px;
            min-height: 200px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            font-style: italic;
        }
        
        .no-data {
            text-align: center;
            padding: 40px;
            color: #666;
            font-size: 1.1em;
        }
        
        @media (max-width: 768px) {
            .metrics-grid {
                grid-template-columns: 1fr 1fr;
            }
            
            .score-value {
                font-size: 3em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Focus Assist</h1>
        
        <?php include 'nav.php'; ?>
        
        <div class="info-box">
            ℹ️ <strong>How to use:</strong> Start focus monitoring to get real-time feedback as you adjust focus. 
            Aim for FWHM &lt; 3.0 pixels and Focus Score &gt; 80 for optimal results.
        </div>
        
        <div class="controls">
            <button class="btn" id="startBtn" onclick="startFocusMonitoring()">Start Focus Monitoring</button>
            <button class="btn btn-stop" id="stopBtn" onclick="stopFocusMonitoring()" disabled>Stop Monitoring</button>
        </div>
        
        <div id="focusData" style="display: none;">
            <div class="focus-panel">
                <div class="focus-score">
                    <div class="score-label">Focus Quality Score</div>
                    <div class="score-value" id="focusScore">--</div>
                    <span class="trend-indicator" id="trendIndicator"></span>
                </div>
                
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">FWHM</div>
                        <div class="metric-value">
                            <span id="fwhm">--</span>
                            <span class="metric-unit">px</span>
                        </div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">HFD</div>
                        <div class="metric-value">
                            <span id="hfd">--</span>
                            <span class="metric-unit">px</span>
                        </div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">Peak Intensity</div>
                        <div class="metric-value">
                            <span id="peak">--</span>
                            <span class="metric-unit">ADU</span>
                        </div>
                    </div>
                    
                    <div class="metric-card">
                        <div class="metric-label">SNR</div>
                        <div class="metric-value">
                            <span id="snr">--</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="focus-panel">
                <h3 style="margin-bottom: 15px;">Focus History</h3>
                <div class="history-chart" id="historyChart">
                    Chart will appear after collecting data...
                </div>
            </div>
        </div>
        
        <div class="no-data" id="noData">
            <p>Click "Start Focus Monitoring" to begin.</p>
            <p style="margin-top: 10px; font-size: 0.9em; color: #888;">
                Ensure camera is capturing and pointing at stars.
            </p>
        </div>
    </div>
    
    <script src="efinder-common.js"></script>
    <script>
        let monitoring = false;
        let updateInterval = null;
        let historyData = [];
        const maxHistory = 50;
        
        function startFocusMonitoring() {
            monitoring = true;
            
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('focusData').style.display = 'block';
            document.getElementById('noData').style.display = 'none';
            
            // Start polling
            updateInterval = setInterval(updateFocusMetrics, 1000);
            updateFocusMetrics(); // Initial update
        }
        
        function stopFocusMonitoring() {
            monitoring = false;
            
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            
            if (updateInterval) {
                clearInterval(updateInterval);
                updateInterval = null;
            }
        }
        
        function updateFocusMetrics() {
            fetch('api/focus.php')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateDisplay(data);
                        addToHistory(data);
                    } else {
                        console.warn('Focus data unavailable:', data.message);
                    }
                })
                .catch(err => console.error('Focus update failed:', err));
        }
        
        function updateDisplay(data) {
            // Update score
            const scoreElem = document.getElementById('focusScore');
            const score = data.score || 0;
            scoreElem.textContent = score.toFixed(1);
            
            // Color code score
            scoreElem.className = 'score-value';
            if (score >= 80) scoreElem.classList.add('score-excellent');
            else if (score >= 60) scoreElem.classList.add('score-good');
            else if (score >= 40) scoreElem.classList.add('score-fair');
            else if (score >= 20) scoreElem.classList.add('score-poor');
            else scoreElem.classList.add('score-bad');
            
            // Update trend
            const trendElem = document.getElementById('trendIndicator');
            const trend = data.trend || 'insufficient_data';
            
            if (trend === 'improving') {
                trendElem.className = 'trend-indicator trend-improving';
                trendElem.textContent = '↗ Improving';
            } else if (trend === 'degrading') {
                trendElem.className = 'trend-indicator trend-degrading';
                trendElem.textContent = '↘ Degrading';
            } else if (trend === 'stable') {
                trendElem.className = 'trend-indicator trend-stable';
                trendElem.textContent = '→ Stable';
            } else {
                trendElem.textContent = '';
            }
            
            // Update metrics
            document.getElementById('fwhm').textContent = (data.fwhm || 0).toFixed(2);
            document.getElementById('hfd').textContent = (data.hfd || 0).toFixed(2);
            document.getElementById('peak').textContent = data.peak || 0;
            document.getElementById('snr').textContent = (data.snr || 0).toFixed(1);
        }
        
        function addToHistory(data) {
            historyData.push({
                time: new Date(),
                score: data.score || 0,
                fwhm: data.fwhm || 0
            });
            
            // Trim history
            if (historyData.length > maxHistory) {
                historyData.shift();
            }
            
            // Simple text-based history display
            // In production, you'd use a charting library like Chart.js
            const chart = document.getElementById('historyChart');
            
            if (historyData.length < 3) {
                chart.textContent = `Collecting data... (${historyData.length}/${maxHistory})`;
                return;
            }
            
            // Create simple ASCII-style visualization
            const scores = historyData.map(d => d.score);
            const minScore = Math.min(...scores);
            const maxScore = Math.max(...scores);
            const avgScore = scores.reduce((a, b) => a + b) / scores.length;
            
            chart.innerHTML = `
                <div style="width: 100%; color: #e0e0e0;">
                    <div style="margin-bottom: 10px;">
                        <strong>Last ${historyData.length} samples:</strong>
                    </div>
                    <div style="display: flex; justify-content: space-around; margin-top: 15px;">
                        <div>Min: ${minScore.toFixed(1)}</div>
                        <div>Avg: ${avgScore.toFixed(1)}</div>
                        <div>Max: ${maxScore.toFixed(1)}</div>
                    </div>
                    <div style="margin-top: 15px; font-size: 0.85em; color: #888;">
                        Latest FWHM: ${historyData[historyData.length-1].fwhm.toFixed(2)} px
                    </div>
                </div>
            `;
        }
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', function() {
            if (monitoring) {
                stopFocusMonitoring();
            }
        });
    </script>
</body>
</html>
