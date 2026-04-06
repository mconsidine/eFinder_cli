<?php
/**
 * api/focus.php - Get current focus metrics
 * 
 * Triggers focus analysis on latest captured frame
 * Returns FWHM, HFD, SNR, and focus score
 */

header('Content-Type: application/json');

// Path to Python focus module
$focus_script = '/home/efinder/Solver/focus_assist.py';

// Trigger focus analysis by calling Python script
// The script reads the latest image from /dev/shm/latest_frame.npy
$cmd = "python3 $focus_script --json 2>&1";
$output = shell_exec($cmd);

if ($output === null || empty($output)) {
    echo json_encode([
        'status' => 'error',
        'message' => 'Focus analysis failed - no output from script'
    ]);
    exit;
}

// Parse JSON output from Python script
$result = json_decode(trim($output), true);

if ($result === null) {
    echo json_encode([
        'status' => 'error',
        'message' => 'Invalid JSON from focus script',
        'raw_output' => $output
    ]);
    exit;
}

// Return result
echo json_encode($result);
?>
