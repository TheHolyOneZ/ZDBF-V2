<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class View
{
    public const FORM_COOKIE = 'zdbf_form';

    public static function e(mixed $value): string
    {
        return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    private static ?string $modules = null;

    private static function stamped(string $path): string
    {
        $changed = @filemtime(dirname(__DIR__) . '/assets/' . $path);
        $stamp = $changed === false ? '' : '-' . base_convert((string) $changed, 10, 36);
        return Http::base() . '/assets/' . $path . '?v=' . App::VERSION . $stamp;
    }

    public static function asset(string $path): string
    {
        return self::e(self::stamped(ltrim($path, '/')));
    }

    private static function moduleMap(): string
    {
        if (self::$modules === null) {
            $root = dirname(__DIR__) . '/assets';
            $imports = [];
            foreach (['js', 'vendor'] as $folder) {
                if (!is_dir($root . '/' . $folder)) {
                    continue;
                }
                $files = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($root . '/' . $folder, \FilesystemIterator::SKIP_DOTS));
                foreach ($files as $file) {
                    if ($file->isFile() && $file->getExtension() === 'js') {
                        $path = str_replace('\\', '/', substr($file->getPathname(), strlen($root) + 1));
                        $imports[Http::base() . '/assets/' . $path] = self::stamped($path);
                    }
                }
            }
            ksort($imports);
            self::$modules = (string) json_encode(['imports' => $imports], JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP);
        }
        return self::$modules;
    }

    public static function modules(): string
    {
        $map = self::moduleMap();
        if (!headers_sent()) {
            header('Content-Security-Policy: ' . Http::policy(base64_encode(hash('sha256', $map, true))));
        }
        return '<script type="importmap">' . $map . '</script>' . "\n";
    }

    public static function formToken(): string
    {
        $token = $_COOKIE[self::FORM_COOKIE] ?? '';
        if (!is_string($token) || preg_match('/^[0-9a-f]{32}$/', $token) !== 1) {
            $token = Crypto::hex(16);
            Session::cookie(self::FORM_COOKIE, $token, 0);
            $_COOKIE[self::FORM_COOKIE] = $token;
        }
        return $token;
    }

    public static function formField(): string
    {
        return '<input type="hidden" name="_token" value="' . self::e(self::formToken()) . '">';
    }

    public static function formValid(): bool
    {
        $cookie = $_COOKIE[self::FORM_COOKIE] ?? '';
        $field = $_POST['_token'] ?? '';
        return is_string($cookie) && is_string($field) && $cookie !== '' && hash_equals($cookie, $field) && Auth::sameOrigin();
    }

    public static function post(string $name, int $max = 255): string
    {
        $value = $_POST[$name] ?? '';
        return is_string($value) ? substr(trim($value), 0, $max) : '';
    }

    public static function mark(): string
    {
        return '<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="currentColor" opacity=".14"/>'
            . '<path d="M9 10h14l-9.5 12H23" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }

    public static function notice(string $kind, string $text): string
    {
        return '<p class="notice" data-kind="' . self::e($kind) . '" role="' . ($kind === 'bad' ? 'alert' : 'status') . '">' . self::e($text) . '</p>';
    }

    public static function page(string $title, string $body, array $options = []): never
    {
        $scripts = '';
        foreach (($options['scripts'] ?? []) as $script) {
            $scripts .= '<script type="module" src="' . self::asset('js/' . $script) . '"></script>' . "\n";
        }
        $wide = !empty($options['wide']) ? ' auth-wide' : '';
        $roomy = !empty($options['wide']) ? ' auth-roomy' : '';
        $scripts .= '<script type="module" src="' . self::asset('js/auth.js') . '"></script>' . "\n";
        if (isset($options['refresh'])) {
            $scripts .= '<meta http-equiv="refresh" content="0;url=' . self::e($options['refresh']) . '">' . "\n";
        }
        header('Content-Type: text/html; charset=utf-8');
        echo '<!doctype html>' . "\n" . '<html lang="en" data-theme="dark">' . "\n" . '<head>' . "\n"
            . '<meta charset="utf-8">' . "\n"
            . '<meta name="viewport" content="width=device-width, initial-scale=1">' . "\n"
            . '<meta name="robots" content="noindex, nofollow">' . "\n"
            . '<meta name="color-scheme" content="dark light">' . "\n"
            . '<title>' . self::e($title) . ' · ZDBF Dashboard</title>' . "\n"
            . '<link rel="icon" type="image/svg+xml" href="' . self::asset('img/mark.svg') . '">' . "\n"
            . '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . self::asset('fonts/zdbf-grotesk-latin.woff2') . '">' . "\n"
            . '<link rel="stylesheet" href="' . self::asset('css/tokens.css') . '">' . "\n"
            . '<link rel="stylesheet" href="' . self::asset('css/auth.css') . '">' . "\n"
            . self::modules()
            . '<script src="' . self::asset('js/theme.js') . '"></script>' . "\n"
            . $scripts
            . '</head>' . "\n" . '<body class="auth' . $roomy . '">' . "\n"
            . '<svg class="auth-mark" viewBox="-1.2 -1.5 2.4 3" aria-hidden="true"><path d="M-1 -1.3H1V-.8L-.39 .8H1V1.3H-1V.8L.39 -.8H-1Z" vector-effect="non-scaling-stroke"/></svg>' . "\n"
            . '<canvas class="scene" id="scene" aria-hidden="true"></canvas>' . "\n"
            . '<main class="auth-card' . $wide . '">' . "\n"
            . '<a class="brand" href="' . self::e(Http::base() . '/') . '">' . self::mark() . '<span>ZDBF</span><small>Dashboard</small></a>' . "\n"
            . $body . "\n"
            . '</main>' . "\n"
            . '<p class="auth-foot">ZDBF Dashboard ' . self::e(App::VERSION) . '</p>' . "\n"
            . '</body>' . "\n" . '</html>';
        exit;
    }
}
