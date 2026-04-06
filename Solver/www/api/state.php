<?php
/**
 * api/state.php - Read current eFinder state
 * 
 * Reads state from shared JSON file written by eFinder_cedar_v2.py
 * State file is in RAM disk (/dev/shm) for zero I/O overhead
 */

header('Content-Type: application/json');

$state_file = '/dev/shm/efinder_state.json';

// Check if state file exists
if (!file_exists($state_file)) {
    echo json_encode([
        'status' => 'error',
        'message' => 'State file not found - eFinder may not be running'
    ]);
    exit;
}

// Read state file
$state_json = file_get_contents($state_file);

if ($state_json === false) {
    echo json_encode([
        'status' => 'error',
        'message' => 'Failed to read state file'
    ]);
    exit;
}

// Parse JSON
$state = json_decode($state_json, true);

if ($state === null) {
    echo json_encode([
        'status' => 'error',
        'message' => 'Invalid JSON in state file'
    ]);
    exit;
}

// Return state
$state['status'] = 'success';
echo json_encode($state);
?>
