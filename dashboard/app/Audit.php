<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Audit
{
    public const KEEP = 5000;

    public static function log(string $action, array $detail = [], ?array $user = null): void
    {
        $user ??= Auth::user();
        $db = App::db();
        $id = $db->insert(App::T . 'audit', [
            'at' => time(),
            'user_id' => $user['id'] ?? null,
            'user_name' => isset($user['username']) ? substr((string) $user['username'], 0, 64) : null,
            'action' => substr($action, 0, 100),
            'detail' => $detail === [] ? null : substr((string) json_encode($detail, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE), 0, 4000),
            'ip' => substr(Http::ip(), 0, 64),
        ]);
        if ($id % 200 === 0) {
            $db->run('DELETE FROM ' . App::T . 'audit WHERE id <= ?', [$id - self::KEEP]);
        }
    }

    public static function recent(int $limit, int $before = 0): array
    {
        $limit = max(1, min($limit, 200));
        $rows = $before > 0
            ? App::db()->all('SELECT * FROM ' . App::T . 'audit WHERE id < ? ORDER BY id DESC LIMIT ?', [$before, $limit])
            : App::db()->all('SELECT * FROM ' . App::T . 'audit ORDER BY id DESC LIMIT ?', [$limit]);
        return array_map(static fn (array $r): array => [
            'id' => (int) $r['id'],
            'at' => (int) $r['at'],
            'user' => $r['user_name'],
            'action' => $r['action'],
            'detail' => $r['detail'] === null ? null : json_decode((string) $r['detail'], true),
            'ip' => $r['ip'],
        ], $rows);
    }
}
