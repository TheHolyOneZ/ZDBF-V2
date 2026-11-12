<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Session;

Http::need('GET', 'POST');
$me = Auth::need();
$db = App::db();
$t = App::T;
$current = (string) Session::current()['id'];
$everyone = Auth::can('users.manage');

if (Http::method() === 'GET') {
    $all = $everyone && Http::query('all') === '1';
    $rows = $all
        ? $db->all('SELECT s.*, u.username FROM ' . $t . 'sessions s JOIN ' . $t . 'users u ON u.id = s.user_id WHERE s.stage = ? AND s.expires_at > ? ORDER BY s.seen_at DESC LIMIT 200', ['full', time()])
        : $db->all('SELECT s.*, u.username FROM ' . $t . 'sessions s JOIN ' . $t . 'users u ON u.id = s.user_id WHERE s.stage = ? AND s.expires_at > ? AND s.user_id = ? ORDER BY s.seen_at DESC', ['full', time(), $me['id']]);
    Http::ok(['sessions' => array_map(static fn (array $r): array => [
        'key' => substr((string) $r['id'], 0, 16),
        'user' => $r['username'],
        'created_at' => (int) $r['created_at'],
        'seen_at' => (int) $r['seen_at'],
        'ip' => $r['ip'],
        'agent' => $r['agent'],
        'current' => $r['id'] === $current,
    ], $rows), 'can_see_all' => $everyone]);
}

Auth::csrf();
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';

if ($action === 'revoke_others') {
    $count = Session::destroyFor($me['id'], $current);
    Audit::log('session.revoked_others', ['count' => $count], $me);
    Http::ok(['count' => $count]);
}

if ($action === 'revoke') {
    $key = is_string($in['key'] ?? null) ? $in['key'] : '';
    if (preg_match('/^[0-9a-f]{16}$/', $key) !== 1) {
        Http::fail(400, 'key', 'Unknown session.');
    }
    $row = $db->one('SELECT id, user_id FROM ' . $t . 'sessions WHERE id LIKE ?', [$key . '%']);
    if ($row === null || ((int) $row['user_id'] !== $me['id'] && !$everyone)) {
        Http::fail(404, 'unknown', 'That session has already ended.');
    }
    $db->run('DELETE FROM ' . $t . 'sessions WHERE id = ?', [$row['id']]);
    $db->run('DELETE FROM ' . $t . 'watch WHERE session_id = ?', [$row['id']]);
    Audit::log('session.revoked', ['user_id' => (int) $row['user_id']], $me);
    Http::ok(['self' => $row['id'] === $current]);
}

Http::fail(400, 'action', 'Unknown action.');
