<?php
declare(strict_types=1);

require __DIR__ . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Setup;
use Zdbf\Dashboard\View;

if (!App::installed()) {
    Http::redirect('setup.php');
}
if (Auth::user() === null) {
    Http::redirect('login.php');
}
if (is_file(Setup::keyFile())) {
    @unlink(Setup::keyFile());
}
header('Content-Type: text/html; charset=utf-8');
$styles = '';
foreach (['tokens', 'base', 'shell', 'components', 'views', 'chat', 'tools'] as $sheet) {
    $styles .= '<link rel="stylesheet" href="' . View::asset('css/' . $sheet . '.css') . '">' . "\n";
}
echo '<!doctype html>' . "\n" . '<html lang="en" data-theme="dark">' . "\n" . '<head>' . "\n"
    . '<meta charset="utf-8">' . "\n"
    . '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' . "\n"
    . '<meta name="robots" content="noindex, nofollow">' . "\n"
    . '<meta name="color-scheme" content="dark light">' . "\n"
    . '<meta name="zdbf-base" content="' . View::e(Http::base()) . '">' . "\n"
    . '<meta name="zdbf-version" content="' . View::e(App::VERSION) . '">' . "\n"
    . '<title>ZDBF Dashboard</title>' . "\n"
    . '<link rel="icon" type="image/svg+xml" href="' . View::asset('img/mark.svg') . '">' . "\n"
    . '<link rel="preload" as="font" type="font/woff2" crossorigin href="' . View::asset('fonts/zdbf-grotesk-latin.woff2') . '">' . "\n"
    . $styles
    . View::modules()
    . '<script src="' . View::asset('js/theme.js') . '"></script>' . "\n"
    . '<script type="module" src="' . View::asset('js/app.js') . '"></script>' . "\n"
    . '</head>' . "\n" . '<body>' . "\n"
    . '<div id="app" class="boot" aria-busy="true"><div class="boot-mark">' . View::mark() . '</div></div>' . "\n"
    . '<noscript><p class="noscript">ZDBF Dashboard needs JavaScript.</p></noscript>' . "\n"
    . '</body>' . "\n" . '</html>';
