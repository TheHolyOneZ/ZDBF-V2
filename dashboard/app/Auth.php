<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Auth
{
    public const MIN_PASSWORD = 12;
    private const DUMMY = '$2y$10$QTPRhqrIEYFJZOVU4PAmmenkM5l5SjV2HGLNjfJd9as7Mi5Pw1NBq';

    private static bool $loaded = false;
    private static ?array $user = null;

    public static function hash(string $password): string
    {
        return password_hash($password, defined('PASSWORD_ARGON2ID') ? PASSWORD_ARGON2ID : PASSWORD_BCRYPT);
    }

    public static function passwordProblem(string $password): ?string
    {
        if (strlen($password) < self::MIN_PASSWORD) {
            return 'Use at least ' . self::MIN_PASSWORD . ' characters.';
        }
        if (strlen($password) > 1024) {
            return 'That password is too long.';
        }
        return null;
    }

    public static function usernameProblem(string $name): ?string
    {
        return preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$/', $name) === 1
            ? null
            : 'Use 3 to 32 letters, digits, dots, dashes or underscores.';
    }

    private static function load(int $id): ?array
    {
        $row = App::db()->one(
            'SELECT u.*, r.name AS role_name, r.capabilities AS role_caps FROM ' . App::T . 'users u JOIN '
            . App::T . 'roles r ON r.id = u.role_id WHERE u.id = ?',
            [$id]
        );
        if ($row === null) {
            return null;
        }
        $row['id'] = (int) $row['id'];
        $row['caps'] = Roles::decode($row['role_caps']);
        return $row;
    }

    public static function user(): ?array
    {
        if (self::$loaded) {
            return self::$user;
        }
        self::$loaded = true;
        if (!App::installed()) {
            return null;
        }
        $session = Session::current();
        if ($session === null || $session['stage'] !== 'full') {
            return null;
        }
        $user = self::load((int) $session['user_id']);
        if ($user === null || (int) $user['disabled'] === 1) {
            return null;
        }
        return self::$user = $user;
    }

    public static function need(): array
    {
        $user = self::user();
        if ($user === null) {
            Http::fail(401, 'auth', 'Log in to continue.');
        }
        return $user;
    }

    public static function can(string $capability): bool
    {
        $user = self::user();
        return $user !== null && Roles::allows($user['caps'], $capability);
    }

    public static function needCap(string $capability): array
    {
        $user = self::need();
        if (!Roles::allows($user['caps'], $capability)) {
            Http::fail(403, 'forbidden', 'Your role does not allow this.');
        }
        return $user;
    }

    public static function isOwner(?array $user = null): bool
    {
        $user ??= self::user();
        return $user !== null && in_array('*', $user['caps'], true);
    }

    public static function sameOrigin(): bool
    {
        $site = strtolower(Http::header('Sec-Fetch-Site'));
        if ($site !== '') {
            return $site === 'same-origin';
        }
        $origin = Http::header('Origin');
        if ($origin === '') {
            return true;
        }
        $host = parse_url($origin, PHP_URL_HOST);
        if (!is_string($host) || $host === '') {
            return false;
        }
        $port = parse_url($origin, PHP_URL_PORT);
        $given = strtolower($host . ($port ? ':' . $port : ''));
        $own = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));
        return $given === $own || $given === preg_replace('/:(?:80|443)$/', '', $own);
    }

    public static function csrf(): void
    {
        if (in_array(Http::method(), ['GET', 'HEAD'], true)) {
            return;
        }
        $session = Session::current();
        $token = Http::header('X-CSRF-Token');
        if ($session === null || $token === '' || !hash_equals((string) $session['csrf'], $token) || !self::sameOrigin()) {
            Http::fail(403, 'csrf', 'The request could not be verified. Reload the page and try again.');
        }
    }

    public static function attempt(string $username, string $password): array
    {
        $db = App::db();
        $ipKey = 'login:ip:' . Http::ip();
        $userKey = 'login:user:' . strtolower(substr($username, 0, 64));
        if (RateLimit::blocked($ipKey, 20) || RateLimit::blocked($userKey, 8)) {
            return ['status' => 'locked', 'retry' => max(RateLimit::retryAfter($ipKey), 60)];
        }
        $row = $db->one('SELECT id, password_hash, disabled, totp_enabled FROM ' . App::T . 'users WHERE username = ?', [$username]);
        $hash = $row !== null && is_string($row['password_hash']) && $row['password_hash'] !== '' ? $row['password_hash'] : self::DUMMY;
        $valid = password_verify($password, $hash) && $row !== null && $hash !== self::DUMMY && (int) $row['disabled'] === 0;
        if (!$valid) {
            RateLimit::hit($ipKey, 20, 900);
            RateLimit::hit($userKey, 8, 900);
            Audit::log('login.failed', ['username' => substr($username, 0, 64)], null);
            return ['status' => 'fail'];
        }
        if (password_needs_rehash($hash, defined('PASSWORD_ARGON2ID') ? PASSWORD_ARGON2ID : PASSWORD_BCRYPT)) {
            $db->run('UPDATE ' . App::T . 'users SET password_hash = ? WHERE id = ?', [self::hash($password), (int) $row['id']]);
        }
        if ((int) $row['totp_enabled'] === 1) {
            Session::create((int) $row['id'], 'totp');
            return ['status' => 'totp'];
        }
        RateLimit::clear($userKey);
        self::finish((int) $row['id'], 'password');
        return ['status' => 'ok'];
    }

    public static function pendingUser(): ?array
    {
        $session = Session::current();
        if ($session === null || $session['stage'] !== 'totp') {
            return null;
        }
        return self::load((int) $session['user_id']);
    }

    public static function secondFactor(string $code): bool
    {
        $user = self::pendingUser();
        if ($user === null) {
            return false;
        }
        $db = App::db();
        $key = 'totp:' . $user['id'];
        if (RateLimit::blocked($key, 6)) {
            return false;
        }
        $secret = Crypto::open((string) $user['totp_secret']);
        $step = $secret === null ? null : Totp::verify($secret, $code, (int) $user['totp_step']);
        if ($step !== null) {
            $db->run('UPDATE ' . App::T . 'users SET totp_step = ? WHERE id = ?', [$step, $user['id']]);
        } else {
            $codes = Roles::decode($user['recovery']);
            $hashed = Totp::hashRecovery($code);
            $index = array_search($hashed, $codes, true);
            if ($index === false || strlen(preg_replace('/[^A-Za-z2-7]/', '', $code) ?? '') !== 10) {
                RateLimit::hit($key, 6, 900);
                Audit::log('login.totp_failed', [], $user);
                return false;
            }
            unset($codes[$index]);
            $db->run('UPDATE ' . App::T . 'users SET recovery = ? WHERE id = ?', [json_encode(array_values($codes)), $user['id']]);
            Audit::log('login.recovery_code', ['left' => count($codes)], $user);
        }
        RateLimit::clear($key);
        RateLimit::clear('login:user:' . strtolower((string) $user['username']));
        Session::destroy();
        self::finish($user['id'], 'password+totp');
        return true;
    }

    public static function finish(int $userId, string $method): void
    {
        Session::create($userId, 'full');
        App::db()->run('UPDATE ' . App::T . 'users SET last_login = ? WHERE id = ?', [time(), $userId]);
        self::$loaded = false;
        self::$user = null;
        Audit::log('login', ['method' => $method], self::load($userId));
    }

    public static function describe(array $user): array
    {
        return [
            'id' => (int) $user['id'],
            'username' => $user['username'],
            'role' => $user['role_name'],
            'capabilities' => $user['caps'],
            'owner' => in_array('*', $user['caps'], true),
            'totp' => (int) $user['totp_enabled'] === 1,
            'has_password' => is_string($user['password_hash']) && $user['password_hash'] !== '',
            'discord' => $user['discord_id'] ? ['id' => $user['discord_id'], 'name' => $user['discord_name']] : null,
        ];
    }
}
