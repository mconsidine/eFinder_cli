<?php
/**
 * api/lx200cmd.php — Send a single LX200 command to eFinder and return response.
 *
 * Usage: GET api/lx200cmd.php?cmd=:AC#
 *
 * Only whitelisted commands are permitted to prevent abuse.
 * The eFinder LX200 server listens on localhost:4060.
 */

header('Content-Type: application/json');

$ALLOWED = [
    ':AC#',   // Enable accelerometer
    ':AD#',   // Disable accelerometer
    ':AG#',   // Get accelerometer state
    ':GV#',   // Get version
    ':GA#',   // Get altitude
    ':GS#',   // Get star count
    ':GK#',   // Get peak
    ':Gt#',   // Get solve time
];

$cmd = $_GET['cmd'] ?? '';

if (!in_array($cmd, $ALLOWED, true)) {
    echo json_encode(['status' => 'error', 'message' => 'Command not permitted']);
    exit;
}

$sock = @fsockopen('127.0.0.1', 4060, $errno, $errstr, 2);
if (!$sock) {
    echo json_encode(['status' => 'error', 'message' => 'Cannot connect to eFinder: ' . $errstr]);
    exit;
}

stream_set_timeout($sock, 2);
fwrite($sock, $cmd);

$response = '';
$deadline = microtime(true) + 2.0;
while (microtime(true) < $deadline) {
    $ch = fread($sock, 64);
    if ($ch === false || $ch === '') break;
    $response .= $ch;
    if (strpos($response, '#') !== false) break;
}
fclose($sock);

echo json_encode([
    'status'   => 'success',
    'cmd'      => $cmd,
    'response' => rtrim($response, '#'),
]);
