<?php
/**
 * api/calibrate.php - Alignment calibration API
 * 
 * Handles calibration wizard workflow:
 * - start: Begin new calibration
 * - capture_sample: Record calibration sample
 * - calculate: Calculate and save final offset
 * - clear: Reset calibration
 */

header('Content-Type: application/json');

$action = $_GET['action'] ?? '';

// Path to Python calibration module
$calibrate_script = '/home/efinder/Solver/alignment_calibration.py';

switch ($action) {
    case 'start':
        $target_samples = intval($_GET['target_samples'] ?? 3);
        
        $cmd = "python3 $calibrate_script --action start --target $target_samples --json 2>&1";
        $output = shell_exec($cmd);
        
        $result = json_decode(trim($output), true);
        
        if ($result === null) {
            echo json_encode([
                'status' => 'error',
                'message' => 'Failed to start calibration',
                'raw_output' => $output
            ]);
        } else {
            echo json_encode($result);
        }
        break;
    
    case 'capture_sample':
        // Get current mount position from state
        $state_file = '/dev/shm/efinder_state.json';
        
        if (!file_exists($state_file)) {
            echo json_encode([
                'status' => 'error',
                'message' => 'Cannot capture sample - eFinder not running'
            ]);
            exit;
        }
        
        $state = json_decode(file_get_contents($state_file), true);
        
        // Call calibration script with current position
        $target_ra = $state['mount_ra'] ?? $state['ra'];
        $target_dec = $state['mount_dec'] ?? $state['dec'];
        $solved_ra = $state['ra'];
        $solved_dec = $state['dec'];
        $alt = $state['alt'] ?? 0;
        $az = $state['az'] ?? 0;
        
        $cmd = sprintf(
            "python3 %s --action capture_sample --target_ra %f --target_dec %f --solved_ra %f --solved_dec %f --alt %f --az %f --json 2>&1",
            $calibrate_script,
            $target_ra,
            $target_dec,
            $solved_ra,
            $solved_dec,
            $alt,
            $az
        );
        
        $output = shell_exec($cmd);
        $result = json_decode(trim($output), true);
        
        if ($result === null) {
            echo json_encode([
                'status' => 'error',
                'message' => 'Failed to capture sample',
                'raw_output' => $output
            ]);
        } else {
            echo json_encode($result);
        }
        break;
    
    case 'calculate':
        $cmd = "python3 $calibrate_script --action calculate --json 2>&1";
        $output = shell_exec($cmd);
        
        $result = json_decode(trim($output), true);
        
        if ($result === null) {
            echo json_encode([
                'status' => 'error',
                'message' => 'Failed to calculate offset',
                'raw_output' => $output
            ]);
        } else {
            echo json_encode($result);
        }
        break;
    
    case 'clear':
        $cmd = "python3 $calibrate_script --action clear --json 2>&1";
        $output = shell_exec($cmd);
        
        echo json_encode([
            'status' => 'success',
            'message' => 'Samples cleared'
        ]);
        break;
    
    case 'status':
        $cmd = "python3 $calibrate_script --action status --json 2>&1";
        $output = shell_exec($cmd);
        
        $result = json_decode(trim($output), true);
        
        if ($result === null) {
            echo json_encode([
                'status' => 'error',
                'message' => 'Failed to get status',
                'raw_output' => $output
            ]);
        } else {
            echo json_encode($result);
        }
        break;
    
    default:
        echo json_encode([
            'status' => 'error',
            'message' => 'Invalid action',
            'valid_actions' => ['start', 'capture_sample', 'calculate', 'clear', 'status']
        ]);
        break;
}
?>
