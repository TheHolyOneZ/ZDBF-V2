<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Queue
{
    public const FINAL = ['done', 'error', 'denied', 'expired'];
    public const INTERIM = ['awaiting_approval', 'running'];
    public const UNCOLLECTED = 90;
    public const REDELIVER = 10;
    public const MAX_RESULT = 4 * 1024 * 1024;
    public const PULL_BYTES = 6 * 1024 * 1024;

    public static function push(string $type, array $args, array $user): string
    {
        $id = Crypto::hex(16);
        App::db()->insert(App::T . 'commands', [
            'id' => $id,
            'type' => $type,
            'args' => (string) json_encode((object) $args, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE),
            'user_id' => (int) $user['id'],
            'user_name' => substr((string) $user['username'], 0, 64),
            'user_role' => substr((string) $user['role_name'], 0, 64),
            'status' => 'queued',
            'created_at' => time(),
        ]);
        return $id;
    }

    public static function waiting(): bool
    {
        $now = time();
        return App::db()->val(
            'SELECT 1 FROM ' . App::T . 'commands WHERE status = ? OR (status = ? AND acked = 0 AND sent_at < ?) LIMIT 1',
            ['queued', 'sent', $now - self::REDELIVER]
        ) !== null;
    }

    public static function deliver(): array
    {
        $db = App::db();
        $now = time();
        $rows = $db->all(
            'SELECT id, type, args, user_id, user_name, user_role, created_at FROM ' . App::T . 'commands '
            . 'WHERE status = ? OR (status = ? AND acked = 0 AND sent_at < ?) ORDER BY created_at LIMIT 20',
            ['queued', 'sent', $now - self::REDELIVER]
        );
        $out = [];
        $bytes = 0;
        foreach ($rows as $row) {
            $bytes += strlen((string) $row['args']);
            if ($out !== [] && $bytes > self::PULL_BYTES) {
                break;
            }
            $db->run('UPDATE ' . App::T . 'commands SET status = ?, sent_at = ? WHERE id = ? AND status IN (?, ?)',
                ['sent', $now, $row['id'], 'queued', 'sent']);
            $args = json_decode((string) $row['args'], true);
            $out[] = [
                'id' => $row['id'],
                'type' => $row['type'],
                'args' => is_array($args) && $args !== [] ? $args : new \stdClass(),
                'user' => ['id' => (string) $row['user_id'], 'name' => $row['user_name'], 'role' => $row['user_role']],
                'issued_at' => (int) $row['created_at'],
            ];
        }
        return $out;
    }

    public static function ack(array $ids): void
    {
        $ids = array_values(array_filter($ids, static fn ($id): bool => is_string($id) && preg_match('/^[0-9a-f]{32}$/', $id) === 1));
        if ($ids === []) {
            return;
        }
        App::db()->run('UPDATE ' . App::T . 'commands SET acked = 1 WHERE id IN (' . Db::marks(count($ids)) . ')', $ids);
    }

    public static function result(array $result): void
    {
        $id = $result['id'] ?? null;
        $status = $result['status'] ?? null;
        if (!is_string($id) || preg_match('/^[0-9a-f]{32}$/', $id) !== 1 || !is_string($status)) {
            return;
        }
        $db = App::db();
        $final = Db::marks(count(self::FINAL));
        if (in_array($status, self::INTERIM, true)) {
            $note = is_string($result['note'] ?? null) ? mb_substr($result['note'], 0, 200) : '';
            $db->run('UPDATE ' . App::T . 'commands SET status = ?, acked = 1, result = ? WHERE id = ? AND status NOT IN (' . $final . ')',
                array_merge([$status, $note === '' ? null : (string) json_encode(['note' => $note], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE), $id], self::FINAL));
            return;
        }
        if (!in_array($status, self::FINAL, true)) {
            return;
        }
        $payload = (string) json_encode(
            ['data' => $result['data'] ?? null, 'error' => isset($result['error']) ? (string) $result['error'] : null],
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE
        );
        if (strlen($payload) > self::MAX_RESULT) {
            $status = 'error';
            $payload = (string) json_encode(['data' => null, 'error' => 'The result was too large to store.']);
        }
        $db->run('UPDATE ' . App::T . 'commands SET status = ?, acked = 1, done_at = ?, result = ? WHERE id = ? AND status NOT IN (' . $final . ')',
            array_merge([$status, time(), $payload, $id], self::FINAL));
    }

    public static function get(string $id): ?array
    {
        if (preg_match('/^[0-9a-f]{32}$/', $id) !== 1) {
            return null;
        }
        return App::db()->one('SELECT * FROM ' . App::T . 'commands WHERE id = ?', [$id]);
    }

    public static function expire(): void
    {
        App::db()->run(
            'UPDATE ' . App::T . 'commands SET status = ?, done_at = ?, result = ? WHERE status = ? AND created_at < ?',
            ['expired', time(), (string) json_encode(['data' => null, 'error' => 'The bot did not collect this in time. Check that it is running.']),
                'queued', time() - self::UNCOLLECTED]
        );
    }

    public static function prune(): void
    {
        App::db()->run('DELETE FROM ' . App::T . 'commands WHERE created_at < ?', [time() - 3600]);
    }
}
