<?php
declare(strict_types=1);

require dirname(__DIR__, 2) . '/app/bootstrap.php';

use Zdbf\Dashboard\BotAuth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Queue;

$in = BotAuth::verify();
Queue::ack(is_array($in['ack'] ?? null) ? $in['ack'] : []);
Queue::expire();

$wait = ($in['wait'] ?? false) === true;
$botActive = ($in['active'] ?? false) === true;
$botTopics = is_string($in['topics'] ?? null) ? $in['topics'] : null;
$hold = $wait ? Http::hold() : 0;
if ($hold > 0 && function_exists('set_time_limit')) {
    @set_time_limit($hold + 15);
}
$deadline = microtime(true) + $hold;
$commands = [];
while (true) {
    $watch = Feed::watching();
    if (Queue::waiting()) {
        $commands = Queue::deliver();
        break;
    }
    $changed = $watch['active'] !== $botActive || ($botTopics !== null && $watch['active'] && $botTopics !== $watch['digest']);
    if ($changed || microtime(true) >= $deadline) {
        break;
    }
    usleep($watch['active'] ? 250000 : 1000000);
}
BotAuth::reply(['commands' => $commands, 'watch' => $watch, 'features' => BotAuth::features(), 'time' => time()]);
