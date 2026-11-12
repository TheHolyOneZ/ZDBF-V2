<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class BotAuth
{
    public const SKEW = 60;
    public const MAX_DECODED = 16 * 1024 * 1024;

    private static string $secret = '';
    private static string $nonce = '';

    public static function bot(): ?array
    {
        return App::db()->one('SELECT * FROM ' . App::T . 'bot WHERE id = 1');
    }

    private static function reject(string $code, bool $count = true, array $extra = []): never
    {
        if ($count) {
            RateLimit::hit('botauth:' . Http::ip(), 30, 300);
        }
        Http::fail(401, $code, '', $extra);
    }

    public static function verify(): array
    {
        Http::need('POST');
        if (!App::installed()) {
            Http::fail(401, 'setup');
        }
        if (RateLimit::blocked('botauth:' . Http::ip(), 30)) {
            Http::fail(429, 'rate');
        }
        $install = Http::header('X-ZDBF-Install');
        $timestamp = Http::header('X-ZDBF-Timestamp');
        $nonce = strtolower(Http::header('X-ZDBF-Nonce'));
        $signature = strtolower(Http::header('X-ZDBF-Signature'));
        $encoding = strtolower(Http::header('X-ZDBF-Encoding'));
        if (preg_match('/^[0-9a-f]{32}$/', $nonce) !== 1 || preg_match('/^[0-9a-f]{64}$/', $signature) !== 1
            || preg_match('/^\d{9,11}$/', $timestamp) !== 1) {
            self::reject('auth');
        }
        $bot = self::bot();
        if ($bot === null || !hash_equals((string) App::config('install_id', ''), $install)) {
            self::reject('auth');
        }
        if (abs(time() - (int) $timestamp) > self::SKEW) {
            self::reject('skew', false, ['server_time' => time()]);
        }
        $secret = Crypto::open((string) $bot['secret']);
        if ($secret === null || preg_match('/^[0-9a-f]{64}$/', $secret) !== 1) {
            self::reject('auth');
        }
        $body = Http::raw();
        $expected = Crypto::requestSignature($secret, Http::path(), $timestamp, $nonce, $body);
        if (!hash_equals($expected, $signature)) {
            self::reject('auth');
        }
        $db = App::db();
        if (!$db->tryInsert(App::T . 'nonces', ['nonce' => $nonce, 'expires_at' => time() + self::SKEW * 3])) {
            self::reject('replay');
        }
        if (random_int(1, 50) === 1) {
            $db->run('DELETE FROM ' . App::T . 'nonces WHERE expires_at <= ?', [time()]);
        }
        $db->run('UPDATE ' . App::T . 'bot SET seen_at = ? WHERE id = 1', [time()]);
        self::$secret = $secret;
        self::$nonce = $nonce;

        if ($encoding === 'gzip') {
            if (!function_exists('gzdecode')) {
                Http::fail(400, 'encoding');
            }
            $decoded = @gzdecode($body, self::MAX_DECODED);
            if ($decoded === false) {
                Http::fail(400, 'encoding');
            }
            $body = $decoded;
        }
        $data = json_decode($body, true, 64);
        if (!is_array($data)) {
            Http::fail(400, 'json');
        }
        return $data;
    }

    public static function features(): array
    {
        return ['gzip' => function_exists('gzdecode'), 'hold' => Http::hold(), 'max_body' => Http::MAX_BODY];
    }

    public static function reply(array $data): never
    {
        $body = (string) json_encode(['ok' => true] + $data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
        $timestamp = (string) time();
        header('Content-Type: application/json; charset=utf-8');
        header('X-ZDBF-Timestamp: ' . $timestamp);
        header('X-ZDBF-Signature: ' . Crypto::responseSignature(self::$secret, Http::path(), self::$nonce, $timestamp, $body));
        echo $body;
        exit;
    }
}
