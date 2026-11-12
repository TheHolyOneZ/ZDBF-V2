<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Queue;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Roles;

Http::need('POST');
$user = Auth::need();
Auth::csrf();
$in = Http::input();
$type = is_string($in['type'] ?? null) ? $in['type'] : '';
$args = is_array($in['args'] ?? null) ? $in['args'] : [];
if (preg_match('/^[a-z0-9][a-z0-9_.-]{0,99}$/', $type) !== 1) {
    Http::fail(400, 'type', 'Unknown action.');
}
$status = Feed::botStatus();
if (!$status['paired']) {
    Http::fail(409, 'unpaired', 'No bot is paired with this dashboard yet.');
}
$meta = Feed::state('meta');
$actions = is_array($meta) && is_array($meta['actions'] ?? null) ? $meta['actions'] : [];
if (!isset($actions[$type]) || !is_string($actions[$type])) {
    Http::fail(404, 'unknown', $actions === [] ? 'The bot has not reported in yet.' : 'The bot does not offer this action.');
}
$capability = $actions[$type];
if (!Roles::allows($user['caps'], $capability)) {
    Http::fail(403, 'forbidden', 'Your role does not allow this.');
}
foreach ((is_array($meta['capabilities'] ?? null) ? $meta['capabilities'] : []) as $entry) {
    if (is_array($entry) && ($entry['name'] ?? '') === $capability && empty($entry['active'])) {
        $why = !empty($meta['locked']) && !empty($entry['enabled'])
            ? 'The bot owner locked the dashboard to view-only.'
            : 'This is switched off on the bot. The bot owner can enable "' . $capability . '" with /dashboard capabilities.';
        Http::fail(409, 'disabled', $why);
    }
}
if (!$status['online']) {
    Http::fail(503, 'offline', 'The bot is offline.');
}
if (!RateLimit::hit('cmd:' . $user['id'], 240, 60)) {
    Http::fail(429, 'rate', 'Too many actions. Wait a moment.');
}
$id = Queue::push($type, $args, $user);
if ($capability !== 'view') {
    Audit::log('command', ['type' => $type, 'id' => $id], $user);
}
Http::ok(['id' => $id, 'capability' => $capability]);
