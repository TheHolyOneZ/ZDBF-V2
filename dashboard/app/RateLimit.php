<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class RateLimit
{
    public static function hit(string $key, int $max, int $window): bool
    {
        $db = App::db();
        $key = substr($key, 0, 128);
        $now = time();
        $table = App::T . 'limits';
        $update = 'hits = CASE WHEN reset_at <= ? THEN 1 ELSE hits + 1 END, '
            . 'reset_at = CASE WHEN reset_at <= ? THEN ? ELSE reset_at END';
        $conflict = $db->driver === 'sqlite' ? ' ON CONFLICT(k) DO UPDATE SET ' : ' ON DUPLICATE KEY UPDATE ';
        return (bool) $db->tx(static function (Db $db) use ($table, $update, $conflict, $key, $max, $window, $now): bool {
            $db->run(
                'INSERT INTO ' . $table . ' (k, hits, reset_at) VALUES (?, 1, ?)' . $conflict . $update,
                [$key, $now + $window, $now, $now, $now + $window]
            );
            return (int) $db->val('SELECT hits FROM ' . $table . ' WHERE k = ?', [$key]) <= $max;
        });
    }

    public static function blocked(string $key, int $max): bool
    {
        $row = App::db()->one('SELECT hits, reset_at FROM ' . App::T . 'limits WHERE k = ?', [substr($key, 0, 128)]);
        return $row !== null && (int) $row['reset_at'] > time() && (int) $row['hits'] >= $max;
    }

    public static function retryAfter(string $key): int
    {
        $reset = (int) (App::db()->val('SELECT reset_at FROM ' . App::T . 'limits WHERE k = ?', [substr($key, 0, 128)]) ?? 0);
        return max(1, $reset - time());
    }

    public static function clear(string $key): void
    {
        App::db()->run('DELETE FROM ' . App::T . 'limits WHERE k = ?', [substr($key, 0, 128)]);
    }

    public static function prune(): void
    {
        App::db()->run('DELETE FROM ' . App::T . 'limits WHERE reset_at <= ?', [time()]);
    }
}
