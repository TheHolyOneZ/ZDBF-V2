<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Setup
{
    public static function keyFile(): string
    {
        return App::$data . '/setup-key.php';
    }

    public static function probeFile(): string
    {
        return App::$data . '/probe.txt';
    }

    public static function writable(): bool
    {
        if (!is_dir(App::$data) && !@mkdir(App::$data, 0700, true) && !is_dir(App::$data)) {
            return false;
        }
        return is_writable(App::$data);
    }

    public static function key(): ?string
    {
        $file = self::keyFile();
        if (is_file($file)) {
            $key = require $file;
            if (is_string($key) && preg_match('/^[A-Z2-7]{4}(-[A-Z2-7]{4}){3}$/', $key) === 1) {
                return $key;
            }
        }
        if (!self::writable()) {
            return null;
        }
        $key = implode('-', str_split(Crypto::base32(16), 4));
        Config::write($file, "<?php\nif (!defined('ZDBF_DASHBOARD')) {\n    http_response_code(404);\n    exit;\n}\nreturn '" . $key . "';\n");
        return $key;
    }

    public static function probe(): string
    {
        $file = self::probeFile();
        $token = is_file($file) ? trim((string) file_get_contents($file)) : '';
        if (preg_match('/^zdbf-probe-[0-9a-f]{24}$/', $token) !== 1) {
            $token = 'zdbf-probe-' . Crypto::hex(12);
            @file_put_contents($file, $token, LOCK_EX);
        }
        return $token;
    }

    public static function checks(): array
    {
        $drivers = Db::drivers();
        $secure = Http::https() || Http::loopback();
        return [
            ['PHP ' . PHP_VERSION, true, true, ''],
            ['Database driver', $drivers !== [], true, $drivers === []
                ? 'Enable the pdo_sqlite or pdo_mysql PHP extension in your hosting panel.'
                : implode(' and ', array_map(static fn (string $d): string => $d === 'sqlite' ? 'SQLite' : 'MySQL/MariaDB', $drivers)) . ' available'],
            ['OpenSSL', function_exists('openssl_encrypt'), true, 'Enable the openssl PHP extension.'],
            ['Data folder writable', self::writable(), true, 'Give the web server write access to the "data" folder (permission 755 or 775).'],
            ['HTTPS', $secure, true, 'Open this page over https://. The bot refuses plain HTTP.'],
            ['Compression', function_exists('gzdecode'), false, 'The zlib extension is missing. The link works without it, with larger requests.'],
            ['Outgoing requests', function_exists('curl_init') || (bool) ini_get('allow_url_fopen'), false, 'Needed only for Discord login (curl extension or allow_url_fopen).'],
        ];
    }

    public static function ready(array $checks): bool
    {
        foreach ($checks as [, $ok, $required]) {
            if ($required && !$ok) {
                return false;
            }
        }
        return true;
    }

    public static function install(array $input): array
    {
        $errors = [];
        $key = self::key();
        if ($key === null || !hash_equals($key, strtoupper(trim((string) ($input['setup_key'] ?? ''))))) {
            $errors['setup_key'] = 'That is not the setup key.';
        }
        $username = (string) ($input['username'] ?? '');
        $password = (string) ($input['password'] ?? '');
        if (($problem = Auth::usernameProblem($username)) !== null) {
            $errors['username'] = $problem;
        }
        if (($problem = Auth::passwordProblem($password)) !== null) {
            $errors['password'] = $problem;
        } elseif ($password !== (string) ($input['password2'] ?? '')) {
            $errors['password2'] = 'The passwords do not match.';
        }
        $driver = (string) ($input['driver'] ?? '');
        if (!in_array($driver, Db::drivers(), true)) {
            $errors['driver'] = 'Choose a database.';
        }
        if ($errors !== []) {
            return $errors;
        }

        if ($driver === 'sqlite') {
            $existing = App::config('db.driver') === 'sqlite' ? (string) App::config('db.path', '') : '';
            $db = ['driver' => 'sqlite', 'path' => $existing !== '' ? $existing : App::$data . '/db-' . Crypto::hex(8) . '.sqlite'];
        } else {
            $db = [
                'driver' => 'mysql',
                'host' => (string) ($input['db_host'] ?? 'localhost') ?: 'localhost',
                'port' => (int) ($input['db_port'] ?? 3306) ?: 3306,
                'name' => (string) ($input['db_name'] ?? ''),
                'user' => (string) ($input['db_user'] ?? ''),
                'pass' => (string) ($input['db_pass'] ?? ''),
            ];
            if ($db['name'] === '' || $db['user'] === '') {
                return ['db_name' => 'Enter the database name and user.'];
            }
        }
        try {
            $conn = Db::open($db);
            $conn->val('SELECT 1');
        } catch (\Throwable $e) {
            App::log('setup: database connection failed: ' . $e->getMessage());
            return ['driver' => $driver === 'sqlite'
                ? 'The SQLite database could not be created in the data folder.'
                : 'Could not connect to the database. Check the host, name, user and password.'];
        }
        App::useDb($conn);
        try {
            $taken = (int) $conn->val('SELECT COUNT(*) FROM ' . App::T . 'users');
        } catch (\Throwable) {
            $taken = 0;
        }
        if ($taken > 0) {
            return ['driver' => 'This database already holds a dashboard. Use an empty database, or remove the tables that start with "' . App::T . '".'];
        }

        $appKey = (string) App::config('app_key', '');
        App::setConfig([
            'installed' => false,
            'install_id' => (string) App::config('install_id', '') ?: Crypto::hex(8),
            'app_key' => $appKey !== '' ? $appKey : base64_encode(random_bytes(32)),
            'db' => $db,
            'hold' => 20,
            'ip_header' => '',
            'oauth' => ['enabled' => false, 'client_id' => '', 'client_secret' => ''],
            'created_at' => time(),
        ]);
        Schema::migrate($conn);
        $conn->insert(App::T . 'users', [
            'username' => $username,
            'password_hash' => Auth::hash($password),
            'role_id' => Roles::idOf(Roles::OWNER),
            'created_at' => time(),
        ]);
        $pair = Pairing::create();
        App::setConfig(['installed' => true]);
        @unlink(self::keyFile());
        @unlink(self::probeFile());
        Audit::log('setup.completed', ['database' => $driver], ['id' => null, 'username' => $username]);
        return ['_pair' => $pair];
    }
}
