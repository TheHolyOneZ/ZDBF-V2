<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Config
{
    public static function file(): string
    {
        return App::$data . '/config.php';
    }

    public static function load(): array
    {
        $file = self::file();
        if (!is_file($file)) {
            return [];
        }
        $data = require $file;
        return is_array($data) ? $data : [];
    }

    public static function save(array $config): void
    {
        if (!is_dir(App::$data) && !@mkdir(App::$data, 0700, true) && !is_dir(App::$data)) {
            throw new \RuntimeException('the data folder cannot be created');
        }
        $code = "<?php\nif (!defined('ZDBF_DASHBOARD')) {\n    http_response_code(404);\n    exit;\n}\nreturn "
            . var_export($config, true) . ";\n";
        self::write(self::file(), $code);
    }

    public static function write(string $file, string $content): void
    {
        $tmp = $file . '.' . bin2hex(random_bytes(6)) . '.tmp';
        if (file_put_contents($tmp, $content, LOCK_EX) === false) {
            throw new \RuntimeException('the data folder is not writable');
        }
        @chmod($tmp, 0600);
        if (!rename($tmp, $file)) {
            @unlink($tmp);
            throw new \RuntimeException('the data folder is not writable');
        }
        if (function_exists('opcache_invalidate')) {
            @opcache_invalidate($file, true);
        }
    }
}
