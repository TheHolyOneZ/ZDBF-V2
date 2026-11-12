<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Crypto;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\OAuth;

Http::need('GET', 'POST');
$me = Auth::need();
if (!Auth::isOwner($me)) {
    Http::fail(403, 'forbidden', 'Only an owner can change these settings.');
}

if (Http::method() === 'GET') {
    Http::ok([
        'oauth' => [
            'enabled' => (bool) App::config('oauth.enabled', false),
            'active' => OAuth::enabled(),
            'client_id' => OAuth::clientId(),
            'has_secret' => (string) App::config('oauth.client_secret', '') !== '',
            'redirect_uri' => OAuth::redirectUri(),
            'can_request' => function_exists('curl_init') || (bool) ini_get('allow_url_fopen'),
        ],
        'system' => [
            'version' => App::VERSION,
            'php' => PHP_VERSION,
            'database' => App::db()->driver,
            'hold' => Http::hold(),
            'hold_setting' => (int) App::config('hold', 20),
            'ip_header' => (string) App::config('ip_header', ''),
            'https' => Http::https(),
            'argon2' => defined('PASSWORD_ARGON2ID'),
            'gzip' => function_exists('gzdecode'),
        ],
    ]);
}

Auth::csrf();
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';

if ($action === 'oauth') {
    $clientId = is_string($in['client_id'] ?? null) ? trim($in['client_id']) : '';
    $secret = is_string($in['client_secret'] ?? null) ? trim($in['client_secret']) : '';
    $enabled = ($in['enabled'] ?? false) === true;
    if ($clientId !== '' && preg_match('/^\d{5,25}$/', $clientId) !== 1) {
        Http::fail(400, 'client_id', 'The client ID is the application ID, a number.');
    }
    if ($secret !== '' && preg_match('/^[A-Za-z0-9_.-]{16,128}$/', $secret) !== 1) {
        Http::fail(400, 'client_secret', 'That does not look like a Discord client secret.');
    }
    $changes = ['oauth' => ['enabled' => $enabled, 'client_id' => $clientId]];
    if ($secret !== '') {
        $changes['oauth']['client_secret'] = Crypto::seal($secret);
    }
    if ($enabled && ($clientId === '' || ($secret === '' && (string) App::config('oauth.client_secret', '') === ''))) {
        Http::fail(400, 'oauth', 'Enter the client ID and the client secret first.');
    }
    App::setConfig($changes);
    Audit::log('settings.oauth', ['enabled' => $enabled], $me);
    Http::ok(['active' => OAuth::enabled()]);
}

if ($action === 'system') {
    $hold = $in['hold'] ?? null;
    $header = $in['ip_header'] ?? '';
    if (!is_int($hold) || $hold < 0 || $hold > 50) {
        Http::fail(400, 'hold', 'Hold requests for 0 to 50 seconds.');
    }
    if (!in_array($header, ['', 'HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP'], true)) {
        Http::fail(400, 'ip_header', 'Unknown address source.');
    }
    App::setConfig(['hold' => $hold, 'ip_header' => $header]);
    Audit::log('settings.system', ['hold' => $hold, 'ip_header' => $header], $me);
    Http::ok(['hold' => Http::hold()]);
}

Http::fail(400, 'action', 'Unknown action.');
