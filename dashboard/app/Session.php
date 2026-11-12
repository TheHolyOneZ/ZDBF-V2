<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Session
{
    public const IDLE = 43200;
    public const LIFE = 604800;
    public const PENDING = 300;

    private static bool $loaded = false;
    private static ?array $current = null;

    public static function cookieName(): string
    {
        return Http::https() ? '__Secure-zdbf_dash' : 'zdbf_dash';
    }

    public static function cookie(string $name, string $value, int $expires, string $sameSite = 'Strict'): void
    {
        setcookie($name, $value, [
            'expires' => $expires,
            'path' => Http::base() . '/',
            'secure' => Http::https(),
            'httponly' => true,
            'samesite' => $sameSite,
        ]);
    }

    private static function hash(string $token): string
    {
        return hash('sha256', $token);
    }

    public static function create(int $userId, string $stage = 'full'): array
    {
        $token = Crypto::hex(32);
        $now = time();
        $row = [
            'id' => self::hash($token),
            'user_id' => $userId,
            'csrf' => Crypto::hex(32),
            'stage' => $stage,
            'created_at' => $now,
            'seen_at' => $now,
            'expires_at' => $now + ($stage === 'full' ? self::LIFE : self::PENDING),
            'ip' => substr(Http::ip(), 0, 64),
            'agent' => Http::agent(),
        ];
        App::db()->insert(App::T . 'sessions', $row);
        self::cookie(self::cookieName(), $token, $stage === 'full' ? 0 : $now + self::PENDING);
        self::$current = $row;
        self::$loaded = true;
        return $row;
    }

    public static function current(): ?array
    {
        if (self::$loaded) {
            return self::$current;
        }
        self::$loaded = true;
        $token = $_COOKIE[self::cookieName()] ?? '';
        if (!is_string($token) || preg_match('/^[0-9a-f]{64}$/', $token) !== 1) {
            return null;
        }
        $db = App::db();
        $row = $db->one('SELECT * FROM ' . App::T . 'sessions WHERE id = ?', [self::hash($token)]);
        $now = time();
        if ($row === null) {
            return null;
        }
        if ((int) $row['expires_at'] <= $now || ($row['stage'] === 'full' && (int) $row['seen_at'] + self::IDLE <= $now)) {
            $db->run('DELETE FROM ' . App::T . 'sessions WHERE id = ?', [$row['id']]);
            return null;
        }
        if ((int) $row['seen_at'] + 60 <= $now) {
            $db->run('UPDATE ' . App::T . 'sessions SET seen_at = ? WHERE id = ?', [$now, $row['id']]);
        }
        return self::$current = $row;
    }

    public static function destroy(): void
    {
        $row = self::current();
        if ($row !== null) {
            App::db()->run('DELETE FROM ' . App::T . 'sessions WHERE id = ?', [$row['id']]);
            App::db()->run('DELETE FROM ' . App::T . 'watch WHERE session_id = ?', [$row['id']]);
        }
        self::cookie(self::cookieName(), '', time() - 86400);
        self::$current = null;
    }

    public static function destroyFor(int $userId, ?string $except = null): int
    {
        $db = App::db();
        if ($except === null) {
            return $db->run('DELETE FROM ' . App::T . 'sessions WHERE user_id = ?', [$userId])->rowCount();
        }
        return $db->run('DELETE FROM ' . App::T . 'sessions WHERE user_id = ? AND id <> ?', [$userId, $except])->rowCount();
    }

    public static function prune(): void
    {
        $now = time();
        App::db()->run('DELETE FROM ' . App::T . 'sessions WHERE expires_at <= ? OR seen_at <= ?', [$now, $now - self::IDLE]);
    }
}
