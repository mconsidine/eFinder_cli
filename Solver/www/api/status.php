<?php
/**
 * api/status.php - Get eFinder status summary
 * 
 * Returns formatted status info for display
 */

header('Content-Type: application/json');

$state_file = '/dev/shm/efinder_state.json';

if (!file_exists($state_file)) {
    echo json_encode([
        'status' => 'error',
        'message' => 'eFinder not running'
    ]);
    exit;
}

$state = json_decode(file_get_contents($state_file), true);

if ($state === null) {
    echo json_encode([
        'status' => 'error',
        'message' => 'Invalid state data'
    ]);
    exit;
}

// Format RA
$ra_hours = $state['ra'] ?? 0;
$ra_h = floor($ra_hours);
$ra_m = floor(($ra_hours - $ra_h) * 60);
$ra_s = floor((($ra_hours - $ra_h) * 60 - $ra_m) * 60);
$ra_formatted = sprintf('%02d:%02d:%02d', $ra_h, $ra_m, $ra_s);

// Format Dec
$dec_deg = $state['dec'] ?? 0;
$dec_sign = $dec_deg >= 0 ? '+' : '-';
$dec_deg = abs($dec_deg);
$dec_d = floor($dec_deg);
$dec_m = floor(($dec_deg - $dec_d) * 60);
$dec_s = floor((($dec_deg - $dec_d) * 60 - $dec_m) * 60);
$dec_formatted = sprintf('%s%02d:%02d:%02d', $dec_sign, $dec_d, $dec_m, $dec_s);

// Time since last solve
$solve_timestamp = $state['solve_timestamp'] ?? 0;
$now = time();
$elapsed = $now - $solve_timestamp;

if ($elapsed < 60) {
    $solve_time = $elapsed . 's ago';
} elseif ($elapsed < 3600) {
    $solve_time = floor($elapsed / 60) . 'm ago';
} else {
    $solve_time = date('H:i:s', $solve_timestamp);
}

echo json_encode([
    'status' => 'success',
    'ra' => $ra_formatted,
    'dec' => $dec_formatted,
    'solve_time' => $solve_time,
    'solve_status' => $state['solve_status'] ?? 'Unknown',
    'mount_mode' => $state['mount_mode'] ?? 'Unknown',
    'focus_score' => $state['focus_score'] ?? null
]);
?>
