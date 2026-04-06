<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eFinder - Alignment Calibration</title>
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
            max-width: 900px;
            margin: 0 auto;
        }
        
        h1 {
            color: #4CAF50;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .panel {
            background: linear-gradient(135deg, #1a1f3a 0%, #2d3561 100%);
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        
        .info-box {
            background: rgba(33, 150, 243, 0.2);
            border: 1px solid #2196F3;
            color: #90CAF9;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
        }
        
        .wizard-steps {
            counter-reset: step;
        }
        
        .wizard-step {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 15px;
            border-left: 4px solid #666;
            position: relative;
        }
        
        .wizard-step.active {
            border-left-color: #4CAF50;
            background: rgba(76, 175, 80, 0.1);
        }
        
        .wizard-step.completed {
            border-left-color: #2196F3;
            opacity: 0.7;
        }
        
        .step-number {
            display: inline-block;
            width: 30px;
            height: 30px;
            background: #666;
            color: white;
            border-radius: 50%;
            text-align: center;
            line-height: 30px;
            font-weight: bold;
            margin-right: 10px;
        }
        
        .wizard-step.active .step-number {
            background: #4CAF50;
        }
        
        .wizard-step.completed .step-number {
            background: #2196F3;
        }
        
        .step-content {
            margin-top: 15px;
            padding-left: 40px;
        }
        
        .step-instruction {
            font-size: 1.1em;
            margin-bottom: 15px;
            color: #e0e0e0;
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
        
        .btn:hover:not(:disabled) {
            background: #45a049;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(76, 175, 80, 0.4);
        }
        
        .btn:disabled {
            background: #555;
            cursor: not-allowed;
            transform: none;
            opacity: 0.6;
        }
        
        .btn-primary {
            background: #2196F3;
        }
        
        .btn-primary:hover:not(:disabled) {
            background: #0b7dda;
        }
        
        .btn-danger {
            background: #f44336;
        }
        
        .btn-danger:hover:not(:disabled) {
            background: #da190b;
        }
        
        .samples-table {
            width: 100%;
            margin-top: 20px;
            border-collapse: collapse;
        }
        
        .samples-table th,
        .samples-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .samples-table th {
            background: rgba(255,255,255,0.05);
            font-weight: 600;
        }
        
        .results-panel {
            background: rgba(76, 175, 80, 0.2);
            border: 2px solid #4CAF50;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }
        
        .result-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .result-item:last-child {
            border-bottom: none;
        }
        
        .result-label {
            font-weight: 600;
            color: #9e9e9e;
        }
        
        .result-value {
            font-size: 1.2em;
            font-weight: 700;
            color: #4CAF50;
        }
        
        .loading {
            display: inline-block;
            margin-left: 10px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .spinner {
            border: 3px solid rgba(255,255,255,0.1);
            border-top-color: #4CAF50;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            animation: spin 0.8s linear infinite;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Alignment Calibration</h1>
        
        <?php include 'nav.php'; ?>
        
        <div class="info-box">
            ℹ️ <strong>Purpose:</strong> This wizard measures the offset between your eFinder camera's optical axis 
            and your main telescope's optical axis. Complete 2-3 samples at different sky positions for best accuracy.
        </div>
        
        <div class="panel">
            <div id="wizardSteps" class="wizard-steps">
                <div class="wizard-step active" id="step0">
                    <span class="step-number">0</span>
                    <strong>Start Calibration</strong>
                    <div class="step-content">
                        <p class="step-instruction">Click below to begin a new calibration session.</p>
                        <button class="btn btn-primary" onclick="startCalibration()">
                            Start New Calibration
                        </button>
                    </div>
                </div>
                
                <div class="wizard-step" id="step1">
                    <span class="step-number">1</span>
                    <strong>Sample 1: East/Low Altitude</strong>
                    <div class="step-content">
                        <p class="step-instruction">
                            1. Slew to a bright star in the eastern sky (low altitude, 20-40°)<br>
                            2. Center the star precisely in your main telescope eyepiece<br>
                            3. Click "Capture Sample 1" to record the offset
                        </p>
                        <button class="btn" onclick="captureSample(1)" id="sample1Btn" disabled>
                            Capture Sample 1
                        </button>
                        <span id="sample1Status"></span>
                    </div>
                </div>
                
                <div class="wizard-step" id="step2">
                    <span class="step-number">2</span>
                    <strong>Sample 2: South/High Altitude</strong>
                    <div class="step-content">
                        <p class="step-instruction">
                            1. Slew to a bright star in the southern sky (high altitude, 60-80°)<br>
                            2. Center the star precisely in your main telescope eyepiece<br>
                            3. Click "Capture Sample 2" to record the offset
                        </p>
                        <button class="btn" onclick="captureSample(2)" id="sample2Btn" disabled>
                            Capture Sample 2
                        </button>
                        <span id="sample2Status"></span>
                    </div>
                </div>
                
                <div class="wizard-step" id="step3">
                    <span class="step-number">3</span>
                    <strong>Sample 3: West/Medium Altitude (Optional)</strong>
                    <div class="step-content">
                        <p class="step-instruction">
                            1. Slew to a bright star in the western sky (medium altitude, 40-60°)<br>
                            2. Center the star precisely in your main telescope eyepiece<br>
                            3. Click "Capture Sample 3" to record the offset
                        </p>
                        <button class="btn" onclick="captureSample(3)" id="sample3Btn" disabled>
                            Capture Sample 3
                        </button>
                        <span id="sample3Status"></span>
                    </div>
                </div>
                
                <div class="wizard-step" id="step4">
                    <span class="step-number">4</span>
                    <strong>Calculate Offset</strong>
                    <div class="step-content">
                        <p class="step-instruction">Review your samples below, then calculate the final offset.</p>
                        
                        <table class="samples-table" id="samplesTable">
                            <thead>
                                <tr>
                                    <th>Sample</th>
                                    <th>RA Offset (")</th>
                                    <th>Dec Offset (")</th>
                                    <th>Total Offset (")</th>
                                </tr>
                            </thead>
                            <tbody id="samplesTableBody">
                                <tr><td colspan="4" style="text-align: center; color: #666;">No samples yet</td></tr>
                            </tbody>
                        </table>
                        
                        <div style="margin-top: 20px; text-align: center;">
                            <button class="btn btn-danger" onclick="clearSamples()" id="clearBtn" disabled>
                                Clear All Samples
                            </button>
                            <button class="btn btn-primary" onclick="calculateOffset()" id="calculateBtn" disabled>
                                Calculate & Save Offset
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div id="resultsPanel" style="display: none;">
            <div class="results-panel">
                <h2 style="margin-bottom: 20px; color: #4CAF50;">✓ Calibration Complete!</h2>
                <div class="result-item">
                    <span class="result-label">RA Offset:</span>
                    <span class="result-value"><span id="resultRA">--</span> arcsec</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Dec Offset:</span>
                    <span class="result-value"><span id="resultDec">--</span> arcsec</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Standard Deviation (RA):</span>
                    <span class="result-value"><span id="resultStdRA">--</span> arcsec</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Standard Deviation (Dec):</span>
                    <span class="result-value"><span id="resultStdDec">--</span> arcsec</span>
                </div>
                <p style="margin-top: 20px; color: #90CAF9;">
                    These values have been saved to <code>eFinder.config</code> as <code>d_x</code> and <code>d_y</code>.
                    Your eFinder will now automatically apply this calibration.
                </p>
            </div>
        </div>
    </div>
    
    <script src="efinder-common.js"></script>
    <script>
        let calibrationState = 'idle';
        let samples = [];
        
        function startCalibration() {
            fetch('api/calibrate.php?action=start&target_samples=3')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'started') {
                        calibrationState = 'collecting';
                        samples = [];
                        updateUI();
                        activateStep(1);
                        document.getElementById('sample1Btn').disabled = false;
                    }
                })
                .catch(err => {
                    console.error('Failed to start calibration:', err);
                    alert('Failed to start calibration. Check console for details.');
                });
        }
        
        function captureSample(sampleNum) {
            const btn = document.getElementById(`sample${sampleNum}Btn`);
            const status = document.getElementById(`sample${sampleNum}Status`);
            
            btn.disabled = true;
            status.innerHTML = '<div class="loading"><div class="spinner"></div></div> Plate solving...';
            
            // This would call your plate solving endpoint
            // For now, simulating with a delay
            fetch('api/calibrate.php?action=capture_sample')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'sample_added' || data.status === 'ready_to_calculate') {
                        samples.push(data);
                        updateSamplesTable();
                        
                        status.innerHTML = `<span style="color: #4CAF50;">✓ Captured: RA ${data.offset_ra}", Dec ${data.offset_dec}"</span>`;
                        
                        completeStep(sampleNum);
                        
                        if (data.status === 'ready_to_calculate') {
                            activateStep(4);
                            document.getElementById('calculateBtn').disabled = false;
                            document.getElementById('clearBtn').disabled = false;
                        } else {
                            // Enable next sample
                            if (sampleNum < 3) {
                                activateStep(sampleNum + 1);
                                document.getElementById(`sample${sampleNum + 1}Btn`).disabled = false;
                            }
                        }
                    }
                })
                .catch(err => {
                    console.error('Sample capture failed:', err);
                    status.innerHTML = '<span style="color: #f44336;">✗ Failed - retry or check logs</span>';
                    btn.disabled = false;
                });
        }
        
        function updateSamplesTable() {
            const tbody = document.getElementById('samplesTableBody');
            
            if (samples.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #666;">No samples yet</td></tr>';
                return;
            }
            
            tbody.innerHTML = samples.map((s, i) => `
                <tr>
                    <td>Sample ${s.sample_number}</td>
                    <td>${s.offset_ra}</td>
                    <td>${s.offset_dec}</td>
                    <td>${s.offset_magnitude}</td>
                </tr>
            `).join('');
        }
        
        function clearSamples() {
            if (!confirm('Clear all samples and start over?')) {
                return;
            }
            
            fetch('api/calibrate.php?action=clear')
                .then(() => {
                    samples = [];
                    calibrationState = 'idle';
                    updateSamplesTable();
                    resetUI();
                });
        }
        
        function calculateOffset() {
            document.getElementById('calculateBtn').disabled = true;
            document.getElementById('calculateBtn').innerHTML = 'Calculating... <div class="loading"><div class="spinner"></div></div>';
            
            fetch('api/calibrate.php?action=calculate')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        document.getElementById('resultRA').textContent = data.offset_ra;
                        document.getElementById('resultDec').textContent = data.offset_dec;
                        document.getElementById('resultStdRA').textContent = data.std_ra;
                        document.getElementById('resultStdDec').textContent = data.std_dec;
                        
                        document.getElementById('resultsPanel').style.display = 'block';
                        completeStep(4);
                        
                        // Scroll to results
                        document.getElementById('resultsPanel').scrollIntoView({ behavior: 'smooth' });
                    } else {
                        alert('Calculation failed: ' + data.message);
                    }
                })
                .catch(err => {
                    console.error('Calculation failed:', err);
                    alert('Calculation failed. Check console for details.');
                })
                .finally(() => {
                    document.getElementById('calculateBtn').innerHTML = 'Calculate & Save Offset';
                });
        }
        
        function activateStep(stepNum) {
            document.getElementById(`step${stepNum}`).classList.add('active');
        }
        
        function completeStep(stepNum) {
            const step = document.getElementById(`step${stepNum}`);
            step.classList.remove('active');
            step.classList.add('completed');
        }
        
        function resetUI() {
            for (let i = 0; i <= 4; i++) {
                const step = document.getElementById(`step${i}`);
                step.classList.remove('active', 'completed');
            }
            document.getElementById('step0').classList.add('active');
            
            for (let i = 1; i <= 3; i++) {
                document.getElementById(`sample${i}Btn`).disabled = true;
                document.getElementById(`sample${i}Status`).innerHTML = '';
            }
            
            document.getElementById('calculateBtn').disabled = true;
            document.getElementById('clearBtn').disabled = true;
            document.getElementById('resultsPanel').style.display = 'none';
        }
        
        function updateUI() {
            // Any initialization needed
        }
        
        // Initial state
        resetUI();
    </script>
</body>
</html>
