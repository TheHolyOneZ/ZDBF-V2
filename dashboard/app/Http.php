<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Http
{
    public const MAX_BODY = 8 * 1024 * 1024;

    private static ?string $path = null;
    private static ?string $raw = null;

    public static function https(): bool
    {
        $https = strtolower((string) ($_SERVER['HTTPS'] ?? ''));
        if ($https !== '' && $https !== 'off') {
            return true;
        }
        if ((string) ($_SERVER['SERVER_PORT'] ?? '') === '443') {
            return true;
        }
        return strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
    }

    public static function loopback(): bool
    {
        $host = strtolower(preg_replace('/:\d+$/', '', (string) ($_SERVER['HTTP_HOST'] ?? '')) ?? '');
        return in_array($host, ['localhost', '127.0.0.1', '[::1]'], true);
    }

    public static function policy(string $scriptHash = ''): string
    {
        $scripts = $scriptHash === '' ? "'self'" : "'self' 'sha256-" . $scriptHash . "'";
        return "default-src 'none'; script-src " . $scripts . "; style-src 'self'; "
            . "img-src 'self' data: https://cdn.discordapp.com https://*.discordapp.net; font-src 'self'; "
            . "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; manifest-src 'self'";
    }

    public static function headers(): void
    {
        if (PHP_SAPI === 'cli' || headers_sent()) {
            return;
        }
        header_remove('X-Powered-By');
        header('Content-Security-Policy: ' . self::policy());
        header('X-Content-Type-Options: nosniff');
        header('X-Frame-Options: DENY');
        header('Referrer-Policy: same-origin');
        header('Permissions-Policy: accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()');
        header('Cross-Origin-Opener-Policy: same-origin');
        header('Cross-Origin-Resource-Policy: same-origin');
        header('Cache-Control: no-store');
        if (self::https()) {
            header('Strict-Transport-Security: max-age=31536000');
        }
    }

    public static function path(): string
    {
        if (self::$path === null) {
            $script = realpath((string) ($_SERVER['SCRIPT_FILENAME'] ?? '')) ?: '';
            $root = realpath(App::$root) ?: App::$root;
            self::$path = str_starts_with($script, $root)
                ? ltrim(str_replace('\\', '/', substr($script, strlen($root))), '/')
                : basename($script);
        }
        return self::$path;
    }

    public static function base(): string
    {
        $name = str_replace('\\', '/', (string) ($_SERVER['SCRIPT_NAME'] ?? '/'));
        $rel = '/' . self::path();
        $base = str_ends_with($name, $rel) ? substr($name, 0, -strlen($rel)) : dirname($name);
        return rtrim($base, '/');
    }

    public static function origin(): string
    {
        return (self::https() ? 'https' : 'http') . '://' . (string) ($_SERVER['HTTP_HOST'] ?? 'localhost');
    }

    public static function url(string $path = ''): string
    {
        return self::origin() . self::base() . '/' . ltrim($path, '/');
    }

    public static function method(): string
    {
        return strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    }

    public static function need(string ...$methods): void
    {
        if (!in_array(self::method(), $methods, true)) {
            header('Allow: ' . implode(', ', $methods));
            self::fail(405, 'method', 'This endpoint does not accept that request method.');
        }
    }

    public static function ip(): string
    {
        $header = (string) App::config('ip_header', '');
        if ($header !== '' && isset($_SERVER[$header])) {
            $first = trim(explode(',', (string) $_SERVER[$header])[0]);
            if (filter_var($first, FILTER_VALIDATE_IP) !== false) {
                return $first;
            }
        }
        return (string) ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
    }

    public static function agent(): string
    {
        return substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 255);
    }

    public static function header(string $name): string
    {
        return trim((string) ($_SERVER['HTTP_' . strtoupper(str_replace('-', '_', $name))] ?? ''));
    }

    public static function raw(): string
    {
        if (self::$raw === null) {
            $length = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
            if ($length > self::MAX_BODY) {
                self::fail(413, 'size', 'The request is too large.');
            }
            $body = file_get_contents('php://input', false, null, 0, self::MAX_BODY + 1);
            if ($body === false || strlen($body) > self::MAX_BODY) {
                self::fail(413, 'size', 'The request is too large.');
            }
            self::$raw = $body;
        }
        return self::$raw;
    }

    public static function input(): array
    {
        $raw = self::raw();
        if ($raw === '') {
            return [];
        }
        $data = json_decode($raw, true, 64);
        if (!is_array($data)) {
            self::fail(400, 'json', 'The request body is not valid JSON.');
        }
        return $data;
    }

    public static function query(string $name, string $default = ''): string
    {
        $value = $_GET[$name] ?? $default;
        return is_string($value) ? $value : $default;
    }

    public static function json(array $data, int $status = 200): never
    {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
        exit;
    }

    public static function ok(array $data = []): never
    {
        self::json(['ok' => true] + $data);
    }

    public static function fail(int $status, string $code, string $message = '', array $extra = []): never
    {
        self::json(['ok' => false, 'error' => $code, 'message' => $message] + $extra, $status);
    }

    public static function redirect(string $path): never
    {
        header('Location: ' . self::base() . '/' . ltrim($path, '/'), true, 303);
        exit;
    }

    public static function hold(): int
    {
        $want = (int) App::config('hold', 20);
        $env = getenv('ZDBF_DASHBOARD_HOLD');
        if (is_string($env) && ctype_digit($env)) {
            $want = (int) $env;
        }
        $limit = (int) ini_get('max_execution_time');
        if ($limit > 0) {
            $want = min($want, $limit - 6);
        }
        return max(0, min($want, 50));
    }
}
