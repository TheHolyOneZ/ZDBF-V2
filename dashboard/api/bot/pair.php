<?php
declare(strict_types=1);

require dirname(__DIR__, 2) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Crypto;
use Zdbf\Dashboard\Db;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\RateLimit;

Http::need('POST');
if (!App::installed()) {
    Http::fail(409, 'setup');
}
if (!RateLimit::hit('pair:' . Http::ip(), 10, 600)) {
    Http::fail(429, 'rate');
}
$in = Http::input();
$codeId = is_string($in['code_id'] ?? null) ? $in['code_id'] : '';
$botNonce = is_string($in['bot_nonce'] ?? null) ? $in['bot_nonce'] : '';
$botId = is_string($in['bot_id'] ?? null) ? $in['bot_id'] : '';
$proof = is_string($in['proof'] ?? null) ? strtolower($in['proof']) : '';
$version = is_string($in['version'] ?? null) ? substr($in['version'], 0, 32) : '';
if (preg_match('/^[0-9a-f]{32}$/', $codeId) !== 1 || preg_match('/^[0-9a-f]{32}$/', $botNonce) !== 1
    || preg_match('/^\d{5,25}$/', $botId) !== 1 || preg_match('/^[0-9a-f]{64}$/', $proof) !== 1) {
    Http::fail(400, 'code');
}

$db = App::db();
$t = App::T;
$row = $db->one('SELECT * FROM ' . $t . 'pairing WHERE code_id = ?', [$codeId]);
if ($row === null || (int) $row['expires_at'] <= time() || (int) $row['attempts'] >= 5) {
    Http::fail(403, 'code');
}
$code = Crypto::open((string) $row['code']);
if ($code === null || !hash_equals(Crypto::pairProof($code, $botNonce, $botId), $proof)) {
    $db->run('UPDATE ' . $t . 'pairing SET attempts = attempts + 1 WHERE code_id = ?', [$codeId]);
    Http::fail(403, 'code');
}

$installId = (string) App::config('install_id');
$serverNonce = Crypto::hex(16);
$secret = Crypto::pairSecret($code, $botNonce, $serverNonce, $installId);
$db->tx(static function (Db $db) use ($t, $botId, $secret, $version): void {
    foreach (['pairing', 'bot', 'state', 'events', 'commands', 'nonces', 'watch'] as $table) {
        $db->run('DELETE FROM ' . $t . $table);
    }
    $db->insert($t . 'bot', ['id' => 1, 'bot_id' => $botId, 'secret' => Crypto::seal($secret), 'paired_at' => time(),
        'seen_at' => 0, 'version' => $version]);
});
Audit::log('link.paired', ['bot_id' => $botId, 'version' => $version], null);
Http::ok([
    'install_id' => $installId,
    'server_nonce' => $serverNonce,
    'proof' => Crypto::pairAck($code, $botNonce, $serverNonce, $installId),
]);
