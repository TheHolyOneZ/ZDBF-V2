<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;

Http::need('GET');
Auth::needCap('audit.view');
$entries = Audit::recent((int) Http::query('limit', '50'), max(0, (int) Http::query('before', '0')));
Http::ok(['entries' => $entries, 'more' => count($entries) >= max(1, min((int) Http::query('limit', '50'), 200))]);
