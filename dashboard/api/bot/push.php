<?php
declare(strict_types=1);

require dirname(__DIR__, 2) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\BotAuth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Queue;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Session;

$in = BotAuth::verify();

if (($in['unpair'] ?? false) === true) {
    $db = App::db();
    foreach (['bot', 'commands', 'nonces', 'watch'] as $table) {
        $db->run('DELETE FROM ' . App::T . $table);
    }
    Audit::log('link.unpaired', ['by' => 'bot'], null);
    BotAuth::reply(['unpaired' => true]);
}

$recover = $in['recover'] ?? null;
if (is_array($recover) && is_string($recover['hash'] ?? null) && preg_match('/^[0-9a-f]{64}$/', $recover['hash']) === 1) {
    $ttl = max(60, min(3600, (int) ($recover['ttl'] ?? 900)));
    App::db()->upsert(App::T . 'meta', ['k' => 'recover'], ['v' => (string) json_encode(['hash' => $recover['hash'], 'expires' => time() + $ttl])]);
    Audit::log('account.recovery_started', ['by' => 'bot'], null);
}
if (is_array($in['state'] ?? null)) {
    Feed::putState($in['state']);
}
if (is_array($in['events'] ?? null)) {
    Feed::addEvents($in['events']);
}
if (is_array($in['results'] ?? null)) {
    foreach (array_slice($in['results'], 0, 200) as $result) {
        if (is_array($result)) {
            Queue::result($result);
        }
    }
}
if (random_int(1, 25) === 1) {
    Feed::prune();
    Queue::prune();
    Session::prune();
    RateLimit::prune();
}
BotAuth::reply(['watch' => Feed::watching(), 'features' => BotAuth::features(), 'time' => time()]);
