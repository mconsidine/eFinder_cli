<!-- nav.php - Shared navigation menu for all eFinder pages -->
<style>
    .nav-menu {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 0;
        margin: 0 0 20px 0;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        border-radius: 8px;
        overflow: hidden;
    }
    
    .nav-menu ul {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-wrap: wrap;
    }
    
    .nav-menu li {
        flex: 1 1 auto;
        min-width: 120px;
    }
    
    .nav-menu a {
        display: block;
        padding: 15px 20px;
        color: #fff;
        text-decoration: none;
        text-align: center;
        font-weight: 500;
        transition: all 0.3s ease;
        border-right: 1px solid rgba(255,255,255,0.1);
        position: relative;
    }
    
    .nav-menu li:last-child a {
        border-right: none;
    }
    
    .nav-menu a:hover {
        background: rgba(255,255,255,0.15);
    }
    
    .nav-menu a.active {
        background: rgba(255,255,255,0.25);
        font-weight: 600;
    }
    
    .nav-menu a.active::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: #4CAF50;
    }
    
    @media (max-width: 768px) {
        .nav-menu ul {
            flex-direction: column;
        }
        .nav-menu a {
            border-right: none;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
    }
</style>

<?php
// Determine current page
$current_page = basename($_SERVER['PHP_SELF']);
?>

<nav class="nav-menu">
    <ul>
        <li>
            <a href="index.php" <?php echo $current_page == 'index.php' ? 'class="active"' : ''; ?>>
                Live View
            </a>
        </li>
        <li>
            <a href="focus.php" <?php echo $current_page == 'focus.php' ? 'class="active"' : ''; ?>>
                Focus Assist
            </a>
        </li>
        <li>
            <a href="calibrate.php" <?php echo $current_page == 'calibrate.php' ? 'class="active"' : ''; ?>>
                Calibration
            </a>
        </li>
        <li>
            <a href="status.php" <?php echo $current_page == 'status.php' ? 'class="active"' : ''; ?>>
                Status
            </a>
        </li>
        <li>
            <a href="log.php" <?php echo $current_page == 'log.php' ? 'class="active"' : ''; ?>>
                Logs
            </a>
        </li>
        <li>
            <a href="README.md" target="_blank">
                Help
            </a>
        </li>
    </ul>
</nav>
