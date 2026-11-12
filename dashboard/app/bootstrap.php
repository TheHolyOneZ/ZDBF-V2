<?php
declare(strict_types=1);

if (PHP_VERSION_ID < 80100) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'ZDBF Dashboard needs PHP 8.1 or newer. This server runs PHP ' . PHP_VERSION . '.';
    exit;
}

define('ZDBF_DASHBOARD', '1.0.0');
require __DIR__ . '/App.php';
\Zdbf\Dashboard\App::boot();
