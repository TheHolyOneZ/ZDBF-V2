<?php
declare(strict_types=1);

require __DIR__ . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Crypto;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\OAuth;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Session;
use Zdbf\Dashboard\View;

Http::need('GET');
if (!OAuth::enabled()) {
    Http::redirect('login.php');
}
if (!RateLimit::hit('oauth:' . Http::ip(), 20, 600)) {
    Http::redirect('login.php?e=discord');
}

if (Http::query('start') !== '') {
    $state = Crypto::hex(16);
    Session::cookie(OAuth::STATE_COOKIE, $state, time() + 600, 'Lax');
    header('Location: ' . OAuth::authorizeUrl($state), true, 303);
    exit;
}

$cookie = $_COOKIE[OAuth::STATE_COOKIE] ?? '';
$state = Http::query('state');
Session::cookie(OAuth::STATE_COOKIE, '', time() - 86400, 'Lax');
if (!is_string($cookie) || $cookie === '' || !hash_equals($cookie, $state)) {
    Http::redirect('login.php?e=state');
}
$code = Http::query('code');
$discord = $code === '' ? null : OAuth::fetchUser($code);
if ($discord === null) {
    Http::redirect('login.php?e=discord');
}

$db = App::db();
$t = App::T;
$user = $db->one('SELECT id, disabled FROM ' . $t . 'users WHERE discord_id = ?', [$discord['id']]);
if ($user === null) {
    $meta = Feed::state('meta');
    $owners = is_array($meta) && is_array($meta['owners'] ?? null) ? $meta['owners'] : [];
    if (!in_array($discord['id'], $owners, true)) {
        Audit::log('login.discord_denied', ['discord_id' => $discord['id']], null);
        Http::redirect('login.php?e=access');
    }
    $name = 'discord-' . substr($discord['id'], -8);
    $suffix = 0;
    while ($db->val('SELECT 1 FROM ' . $t . 'users WHERE username = ?', [$name . ($suffix ? '-' . $suffix : '')]) !== null) {
        $suffix++;
    }
    $id = $db->insert($t . 'users', [
        'username' => $name . ($suffix ? '-' . $suffix : ''),
        'role_id' => Roles::idOf(Roles::OWNER),
        'discord_id' => $discord['id'],
        'discord_name' => $discord['name'],
        'created_at' => time(),
    ]);
    Audit::log('user.created', ['user' => $name, 'role' => Roles::OWNER, 'via' => 'bot owner on Discord'], null);
    $user = ['id' => $id, 'disabled' => 0];
}
if ((int) $user['disabled'] === 1) {
    Http::redirect('login.php?e=access');
}
$db->run('UPDATE ' . $t . 'users SET discord_name = ? WHERE id = ?', [$discord['name'], (int) $user['id']]);
Auth::finish((int) $user['id'], 'discord');
$home = Http::base() . '/';
View::page('Signing in', '<h1>Signing in</h1><p class="lead">One moment.</p><a class="btn btn-primary" href="'
    . View::e($home) . '">Continue</a>', ['refresh' => $home]);
