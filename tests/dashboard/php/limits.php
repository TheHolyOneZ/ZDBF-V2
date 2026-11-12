<?php
declare(strict_types=1);

$worker = ($argv[1] ?? '') === '--worker';
if (!$worker) {
    $data = sys_get_temp_dir() . '/zdbf-dashboard-limits-' . bin2hex(random_bytes(4));
    mkdir($data, 0700, true);
    putenv('ZDBF_DASHBOARD_DATA=' . $data);
}
require dirname(__DIR__, 3) . '/dashboard/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Db;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Schema;

const WORKERS = 8;
const HITS = 25;
const MAX = 60;

if ($worker) {
    $allowed = 0;
    for ($i = 0; $i < HITS; $i++) {
        $allowed += RateLimit::hit($argv[2], MAX, 600) ? 1 : 0;
    }
    echo $allowed;
    exit(0);
}

$mysql = (string) getenv('ZDBF_TEST_MYSQL');
if (in_array('sqlite', Db::drivers(), true)) {
    $db = ['driver' => 'sqlite', 'path' => $data . '/limits.sqlite'];
} elseif ($mysql !== '' && in_array('mysql', Db::drivers(), true)) {
    [$host, $port, $name, $user, $pass] = explode(':', $mysql, 5);
    $db = ['driver' => 'mysql', 'host' => $host, 'port' => (int) $port, 'name' => $name, 'user' => $user, 'pass' => $pass];
} else {
    echo "skipped: no PDO driver (sqlite, or mysql with ZDBF_TEST_MYSQL)\n";
    exit(0);
}
App::setConfig(['app_key' => base64_encode(random_bytes(32)), 'db' => $db]);
Schema::migrate(App::db());

$failed = 0;
$check = static function (string $name, bool $ok) use (&$failed): void {
    if (!$ok) {
        $failed++;
        fwrite(STDERR, 'FAIL ' . $name . "\n");
    }
};

$key = 'test:' . bin2hex(random_bytes(6));
$check('first hits pass', RateLimit::hit($key, 2, 600) && RateLimit::hit($key, 2, 600));
$check('third hit is refused', !RateLimit::hit($key, 2, 600) && RateLimit::blocked($key, 2));
App::db()->run('UPDATE ' . App::T . 'limits SET reset_at = ? WHERE k = ?', [time() - 1, $key]);
$check('an expired window starts over', RateLimit::hit($key, 2, 600) && !RateLimit::blocked($key, 2));
RateLimit::clear($key);

$race = 'race:' . bin2hex(random_bytes(6));
$args = array_merge([PHP_BINARY], array_map(static fn (string $ini): string => '-d' . $ini, array_filter([
    extension_loaded('pdo_mysql') ? 'extension=pdo_mysql' : '',
])), [__FILE__, '--worker', $race]);
$procs = [];
for ($i = 0; $i < WORKERS; $i++) {
    $pipes = [];
    $proc = proc_open($args, [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, ['ZDBF_DASHBOARD_DATA' => $data] + getenv());
    $procs[] = [$proc, $pipes];
}
$allowed = 0;
foreach ($procs as [$proc, $pipes]) {
    $out = stream_get_contents($pipes[1]);
    $err = stream_get_contents($pipes[2]);
    $code = proc_close($proc);
    $check('worker finished cleanly' . ($err !== '' ? ': ' . trim($err) : ''), $code === 0 && $err === '');
    $allowed += (int) $out;
}
$check('parallel hits honour the limit exactly (' . $allowed . ' of ' . MAX . ')', $allowed === MAX);
RateLimit::clear($race);

foreach (glob($data . '/*') ?: [] as $file) {
    @unlink($file);
}
@rmdir($data);
echo $db['driver'] . ' limiter: ' . ($failed === 0 ? 'ok' : $failed . ' failed') . "\n";
exit($failed === 0 ? 0 : 1);
