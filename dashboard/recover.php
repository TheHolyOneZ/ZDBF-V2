<?php
declare(strict_types=1);

require __DIR__ . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\RateLimit;
use Zdbf\Dashboard\Session;
use Zdbf\Dashboard\View;

if (!App::installed()) {
    Http::redirect('setup.php');
}

function recovery(): ?array
{
    $raw = App::db()->val('SELECT v FROM ' . App::T . 'meta WHERE k = ?', ['recover']);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($data) || !is_string($data['hash'] ?? null) || (int) ($data['expires'] ?? 0) < time()) {
        return null;
    }
    return $data;
}

$error = '';
$done = false;
$username = '';
if (Http::method() === 'POST') {
    $ipKey = 'recover:' . Http::ip();
    if (!View::formValid()) {
        $error = 'The form expired. Try again.';
    } elseif (RateLimit::blocked($ipKey, 6)) {
        $error = 'Too many attempts. Wait a few minutes.';
    } else {
        $username = View::post('username', 64);
        $code = strtoupper(preg_replace('/[^A-Za-z0-9]/', '', View::post('code', 64)) ?? '');
        $password = View::post('password', 1024);
        $entry = recovery();
        $db = App::db();
        $user = $db->one('SELECT u.id, u.username, r.capabilities FROM ' . App::T . 'users u JOIN ' . App::T
            . 'roles r ON r.id = u.role_id WHERE u.username = ?', [$username]);
        $caps = is_array($user) ? json_decode((string) $user['capabilities'], true) : null;
        if ($entry === null || $code === '' || !hash_equals($entry['hash'], hash('sha256', $code))) {
            RateLimit::hit($ipKey, 6, 900);
            $error = 'That code is not valid or has expired. Run /dashboard recover again.';
        } elseif (!is_array($caps) || !in_array('*', $caps, true)) {
            RateLimit::hit($ipKey, 6, 900);
            $error = 'Only an account with the Owner role can be recovered here.';
        } elseif (($problem = Auth::passwordProblem($password)) !== null) {
            $error = $problem;
        } elseif ($password !== View::post('confirm', 1024)) {
            $error = 'The two passwords are not the same.';
        } else {
            $fields = 'password_hash = ?, disabled = 0';
            $params = [Auth::hash($password)];
            if (View::post('totp') === '1') {
                $fields .= ', totp_enabled = 0, totp_secret = NULL, recovery = NULL';
            }
            $db->run('UPDATE ' . App::T . 'users SET ' . $fields . ' WHERE id = ?', [...$params, (int) $user['id']]);
            $db->run('DELETE FROM ' . App::T . 'meta WHERE k = ?', ['recover']);
            Session::destroyFor((int) $user['id']);
            RateLimit::clear($ipKey);
            Audit::log('account.recovered', ['user' => $user['username'], 'totp_off' => View::post('totp') === '1'], null);
            $done = true;
        }
    }
}

if ($done) {
    View::page('Account recovered', '<h1>Account recovered</h1>'
        . View::notice('ok', 'The new password is set and every session of this account was ended.')
        . '<a class="btn btn-primary" href="' . View::e(Http::base() . '/login.php') . '">Log in</a>');
}

$active = recovery() !== null;
$body = '<h1>Recover an owner account</h1>'
    . '<p class="lead">Run <code>/dashboard recover</code> in Discord as the bot owner. The bot sends you a code that works for 15 minutes.</p>';
if ($error !== '') {
    $body .= View::notice('bad', $error);
} elseif (!$active) {
    $body .= View::notice('bad', 'No recovery is waiting right now. Run /dashboard recover first.');
}
$body .= '<form method="post" class="form" autocomplete="off">' . View::formField()
    . '<label class="field"><span>Code from the bot</span><input name="code" maxlength="64" required autofocus autocomplete="one-time-code"></label>'
    . '<label class="field"><span>User name of the owner account</span><input name="username" maxlength="64" required autocomplete="username" value="' . View::e($username) . '"></label>'
    . '<label class="field"><span>New password</span><input name="password" type="password" maxlength="1024" required autocomplete="new-password"></label>'
    . '<label class="field"><span>New password again</span><input name="confirm" type="password" maxlength="1024" required autocomplete="new-password"></label>'
    . '<label class="check"><input type="checkbox" name="totp" value="1"><span>Also turn off two-factor login for this account<small>Use this if the authenticator app is lost too. Set it up again after logging in.</small></span></label>'
    . '<button class="btn btn-primary" type="submit">Set the new password</button></form>'
    . '<p class="form-quiet"><a class="link" href="' . View::e(Http::base() . '/login.php') . '">Back to the login</a></p>';
View::page('Recover an owner account', $body);
