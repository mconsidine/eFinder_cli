<?php
$lines = isset($_GET['lines']) ? intval($_GET['lines']) : 50;
$lines = max(10, min(500, $lines));
?>
<!DOCTYPE html>
<html>
<head>
    <title>eFinder Log</title>
    <meta http-equiv="refresh" content="5">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body  { background:#111; color:#0f0; font-family:monospace; font-size:13px;
                padding:1em; margin:0; }
        h2    { color:#fff; margin:0 0 0.5em 0; font-size:1em; }
        pre   { white-space:pre-wrap; word-break:break-all; margin:0; }
        a     { color:#8af; text-decoration:none; }
        a:hover { text-decoration:underline; }
        .bar  { display:flex; justify-content:space-between; align-items:baseline;
                margin-bottom:0.75em; flex-wrap:wrap; gap:0.5em; }
        .links a { margin-right:0.5em; }
        .note { color:#888; font-size:0.85em; }
        .nav  { margin-top:1em; }
        .nav a { margin-right:1em; }
    </style>
</head>
<body>
<div class="bar">
    <h2>eFinder Log</h2>
    <div class="links">
        Lines:
        <a href="?lines=50">50</a>
        <a href="?lines=100">100</a>
        <a href="?lines=200">200</a>
        <a href="?lines=500">500</a>
    </div>
    <span class="note">auto-refreshes every 5s &nbsp;|&nbsp; showing last <?php echo $lines; ?> lines</span>
</div>
<pre><?php
$output = shell_exec('journalctl -u efinder -n ' . $lines . ' --no-pager --output=short 2>&1');
echo htmlspecialchars($output ?? 'No log output available.');
?></pre>
<div class="nav">
    <a href="/">Home</a>
    <a href="/README.html">README</a>
</div>
</body>
</html>
