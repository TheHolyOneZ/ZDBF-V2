<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Session;

Http::need('GET');
$user = Auth::need();
$session = Session::current();
$topics = array_values(array_filter(
    Feed::topics(Http::query('topics')),
    static fn (string $t): bool => Roles::allows($user['caps'], Roles::topicCapability($t))
));
$rev = max(0, (int) Http::query('rev', '0'));
$ev = (int) Http::query('ev', '-1');
$known = Http::query('online');
$hold = Http::query('wait', '1') === '0' ? 0 : Http::hold();
if ($hold > 0 && function_exists('set_time_limit')) {
    @set_time_limit($hold + 15);
}
Feed::watch((string) $session['id'], $topics, $hold + 15);
if ($ev < 0) {
    $ev = Feed::lastEventId();
}
$deadline = microtime(true) + $hold;
while (true) {
    $state = Feed::stateSince($topics, $rev);
    $events = Feed::eventsSince($topics, $ev);
    $bot = Feed::botStatus();
    $changed = $known !== '' && $known !== ($bot['online'] ? '1' : '0');
    if ($state !== [] || $events !== [] || $changed || microtime(true) >= $deadline) {
        break;
    }
    usleep(300000);
}
foreach ($state as $entry) {
    $rev = max($rev, $entry['rev']);
}
if ($events !== []) {
    $ev = $events[count($events) - 1]['id'];
}
Http::ok(['state' => (object) $state, 'events' => $events, 'rev' => $rev, 'ev' => $ev, 'bot' => $bot, 'now' => time()]);
