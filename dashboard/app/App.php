<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class App
{
    public const VERSION = ZDBF_DASHBOARD;
    public const T = 'zd_';

    public static string $root = '';
    public static string $data = '';
    private static array $config = [];
    private static ?Db $db = null;

    public static function boot(): void
    {
        self::$root = dirname(__DIR__);
        $env = getenv('ZDBF_DASHBOARD_DATA');
        self::$data = is_string($env) && $env !== '' ? rtrim($env, '/\\') : self::$root . '/data';

        spl_autoload_register(static function (string $class): void {
            $prefix = __NAMESPACE__ . '\\';
            if (!str_starts_with($class, $prefix)) {
                return;
            }
            $name = substr($class, strlen($prefix));
            if (preg_match('/^[A-Za-z]+$/', $name) === 1 && is_file(__DIR__ . '/' . $name . '.php')) {
                require __DIR__ . '/' . $name . '.php';
            }
        });

        error_reporting(E_ALL);
        ini_set('display_errors', '0');
        ini_set('html_errors', '0');
        set_error_handler(static function (int $level, string $message, string $file, int $line): bool {
            if ((error_reporting() & $level) === 0) {
                return false;
            }
            if (($level & (E_DEPRECATED | E_USER_DEPRECATED)) !== 0) {
                self::log('deprecated: ' . $message . ' @ ' . $file . ':' . $line);
                return true;
            }
            throw new \ErrorException($message, 0, $level, $file, $line);
        });
        set_exception_handler([self::class, 'crash']);

        self::$config = Config::load();
        Http::headers();
    }

    public static function installed(): bool
    {
        return (bool) (self::$config['installed'] ?? false);
    }

    public static function config(string $key, mixed $default = null): mixed
    {
        $cur = self::$config;
        foreach (explode('.', $key) as $part) {
            if (!is_array($cur) || !array_key_exists($part, $cur)) {
                return $default;
            }
            $cur = $cur[$part];
        }
        return $cur;
    }

    public static function setConfig(array $changes): void
    {
        self::$config = array_replace_recursive(self::$config, $changes);
        Config::save(self::$config);
    }

    public static function db(): Db
    {
        if (self::$db === null) {
            $cfg = self::$config['db'] ?? null;
            if (!is_array($cfg)) {
                throw new \RuntimeException('database is not configured');
            }
            self::$db = Db::open($cfg);
        }
        return self::$db;
    }

    public static function useDb(Db $db): void
    {
        self::$db = $db;
    }

    public static function log(string $message): void
    {
        $file = self::$data . '/error.log';
        if (!is_dir(self::$data)) {
            return;
        }
        if (is_file($file) && filesize($file) > 2 * 1024 * 1024) {
            @rename($file, $file . '.1');
        }
        @file_put_contents($file, '[' . gmdate('Y-m-d H:i:s') . '] ' . $message . "\n", FILE_APPEND | LOCK_EX);
    }

    public static function crash(\Throwable $e): void
    {
        $ref = bin2hex(random_bytes(4));
        self::log($ref . ' ' . get_class($e) . ': ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine());
        if (PHP_SAPI === 'cli') {
            fwrite(STDERR, get_class($e) . ': ' . $e->getMessage() . "\n" . $e->getTraceAsString() . "\n");
            exit(1);
        }
        if (!headers_sent()) {
            http_response_code(500);
            if (str_starts_with(Http::path(), 'api/')) {
                header('Content-Type: application/json; charset=utf-8');
                echo json_encode(['ok' => false, 'error' => 'server', 'message' => 'Something went wrong on the website.', 'ref' => $ref]);
            } else {
                header('Content-Type: text/plain; charset=utf-8');
                echo 'Something went wrong. Reference: ' . $ref;
            }
        }
        exit(1);
    }
}
