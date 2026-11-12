<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Crypto;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Session;
use Zdbf\Dashboard\Totp;

Http::need('GET', 'POST');
$me = Auth::need();
$db = App::db();
$t = App::T;

if (Http::method() === 'GET') {
    Http::ok(['user' => Auth::describe($me), 'recovery_left' => count(Roles::decode($me['recovery']))]);
}

Auth::csrf();
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';

if ($action === 'logout') {
    Audit::log('logout', [], $me);
    Session::destroy();
    Http::ok();
}

$confirm = static function () use ($in, $me): void {
    $password = is_string($in['current'] ?? null) ? $in['current'] : '';
    $key = 'confirm:' . $me['id'];
    if (RateLimit::blocked($key, 8)) {
        Http::fail(429, 'rate', 'Too many attempts. Wait a few minutes.');
    }
    if (is_string($me['password_hash']) && $me['password_hash'] !== '' && !password_verify($password, $me['password_hash'])) {
        RateLimit::hit($key, 8, 900);
        Http::fail(403, 'password', 'The current password is wrong.');
    }
};

if ($action === 'password') {
    $confirm();
    $new = is_string($in['new'] ?? null) ? $in['new'] : '';
    if (($problem = Auth::passwordProblem($new)) !== null) {
        Http::fail(400, 'password', $problem);
    }
    $db->run('UPDATE ' . $t . 'users SET password_hash = ? WHERE id = ?', [Auth::hash($new), $me['id']]);
    $ended = Session::destroyFor($me['id'], (string) Session::current()['id']);
    Audit::log('account.password', ['sessions_ended' => $ended], $me);
    Http::ok(['sessions_ended' => $ended]);
}

if ($action === 'totp_begin') {
    $confirm();
    if ((int) $me['totp_enabled'] === 1) {
        Http::fail(409, 'totp', 'Two-factor login is already on.');
    }
    $secret = Totp::secret();
    $db->run('UPDATE ' . $t . 'users SET totp_secret = ?, totp_step = 0 WHERE id = ?', [Crypto::seal($secret), $me['id']]);
    Http::ok(['secret' => $secret, 'uri' => Totp::uri($secret, (string) $me['username'], 'ZDBF Dashboard')]);
}

if ($action === 'totp_confirm') {
    $secret = is_string($me['totp_secret']) ? Crypto::open($me['totp_secret']) : null;
    $code = is_string($in['code'] ?? null) ? $in['code'] : '';
    if ($secret === null || (int) $me['totp_enabled'] === 1) {
        Http::fail(409, 'totp', 'Start the two-factor setup again.');
    }
    $step = Totp::verify($secret, $code, 0);
    if ($step === null) {
        Http::fail(400, 'code', 'That code is not correct. Check the time on your phone.');
    }
    $codes = Totp::recoveryCodes();
    $db->run('UPDATE ' . $t . 'users SET totp_enabled = 1, totp_step = ?, recovery = ? WHERE id = ?',
        [$step, json_encode(array_map([Totp::class, 'hashRecovery'], $codes)), $me['id']]);
    Audit::log('account.totp_enabled', [], $me);
    Http::ok(['recovery' => $codes]);
}

if ($action === 'totp_disable') {
    $confirm();
    $db->run('UPDATE ' . $t . 'users SET totp_enabled = 0, totp_secret = NULL, recovery = NULL, totp_step = 0 WHERE id = ?', [$me['id']]);
    Audit::log('account.totp_disabled', [], $me);
    Http::ok();
}

if ($action === 'recovery') {
    $confirm();
    if ((int) $me['totp_enabled'] !== 1) {
        Http::fail(409, 'totp', 'Two-factor login is off.');
    }
    $codes = Totp::recoveryCodes();
    $db->run('UPDATE ' . $t . 'users SET recovery = ? WHERE id = ?',
        [json_encode(array_map([Totp::class, 'hashRecovery'], $codes)), $me['id']]);
    Audit::log('account.recovery_regenerated', [], $me);
    Http::ok(['recovery' => $codes]);
}

Http::fail(400, 'action', 'Unknown action.');
