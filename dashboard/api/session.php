<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\OAuth;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Session;

Http::need('GET');
$user = Auth::need();
Http::ok([
    'user' => Auth::describe($user),
    'csrf' => Session::current()['csrf'],
    'version' => App::VERSION,
    'bot' => Feed::botStatus(),
    'hold' => Http::hold(),
    'oauth' => OAuth::enabled(),
    'capabilities' => ['bot' => Roles::BOT, 'web' => Roles::WEB],
    'now' => time(),
]);
