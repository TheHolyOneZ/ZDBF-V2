<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\BotAuth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Pairing;

Http::need('GET', 'POST');
$me = Auth::needCap('link.manage');

if (Http::method() === 'GET') {
    $bot = BotAuth::bot();
    Http::ok([
        'bot' => Feed::botStatus() + ['bot_id' => $bot['bot_id'] ?? null, 'version' => $bot['version'] ?? null],
        'pairing_expires' => Pairing::pending(),
        'url' => rtrim(Http::url(''), '/'),
        'https' => Http::https(),
    ]);
}

Auth::csrf();
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';

if ($action === 'code') {
    $pair = Pairing::create();
    Audit::log('link.code_created', [], $me);
    Http::ok($pair + ['url' => rtrim(Http::url(''), '/')]);
}

if ($action === 'unpair') {
    $db = App::db();
    foreach (['bot', 'commands', 'nonces', 'pairing'] as $table) {
        $db->run('DELETE FROM ' . App::T . $table);
    }
    Audit::log('link.unpaired', ['by' => 'website'], $me);
    Http::ok();
}

Http::fail(400, 'action', 'Unknown action.');
