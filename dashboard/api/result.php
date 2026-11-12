<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Queue;
use Zdbf\Dashboard\Roles;

Http::need('GET');
$user = Auth::need();
$id = Http::query('id');
$since = Http::query('since');
$seen = Http::query('note');
$note = static function (array $row): string {
    $stored = is_string($row['result']) ? json_decode($row['result'], true) : null;
    return is_array($stored) && is_string($stored['note'] ?? null) ? $stored['note'] : '';
};
$row = Queue::get($id);
if ($row === null) {
    Http::fail(404, 'unknown', 'That action is no longer stored.');
}
if ((int) $row['user_id'] !== $user['id'] && !Roles::allows($user['caps'], 'audit.view')) {
    Http::fail(403, 'forbidden', 'That action belongs to someone else.');
}
$hold = min(Http::hold(), 15);
if ($hold > 0 && function_exists('set_time_limit')) {
    @set_time_limit($hold + 15);
}
$deadline = microtime(true) + $hold;
while (!in_array($row['status'], Queue::FINAL, true)) {
    $moved = $row['status'] !== $since || $note($row) !== $seen;
    if (($since !== '' && $moved && in_array($row['status'], Queue::INTERIM, true)) || microtime(true) >= $deadline) {
        break;
    }
    usleep(200000);
    $row = Queue::get($id) ?? $row;
}
$result = is_string($row['result']) ? json_decode($row['result'], true) : null;
Http::ok([
    'id' => $row['id'],
    'type' => $row['type'],
    'status' => $row['status'],
    'final' => in_array($row['status'], Queue::FINAL, true),
    'note' => in_array($row['status'], Queue::FINAL, true) ? '' : $note($row),
    'data' => is_array($result) ? ($result['data'] ?? null) : null,
    'message' => is_array($result) ? ($result['error'] ?? null) : null,
]);
