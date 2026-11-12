<?php
declare(strict_types=1);

require __DIR__ . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\OAuth;
use Zdbf\Dashboard\Session;
use Zdbf\Dashboard\View;

if (!App::installed()) {
    Http::redirect('setup.php');
}
if (Auth::user() !== null) {
    Http::redirect('');
}

$error = '';
$step = Auth::pendingUser() !== null ? 'totp' : 'password';
$username = '';

if (Http::method() === 'POST') {
    if (!View::formValid()) {
        $error = 'The form expired. Try again.';
    } elseif (View::post('step') === 'cancel') {
        Session::destroy();
        $step = 'password';
    } elseif (View::post('step') === 'totp') {
        if (Auth::secondFactor(View::post('code', 32))) {
            Http::redirect('');
        }
        $step = Auth::pendingUser() !== null ? 'totp' : 'password';
        $error = $step === 'totp' ? 'That code is not correct.' : 'The login expired. Start again.';
    } else {
        $username = View::post('username', 64);
        $password = is_string($_POST['password'] ?? null) ? $_POST['password'] : '';
        $result = Auth::attempt($username, $password);
        if ($result['status'] === 'ok') {
            Http::redirect('');
        }
        if ($result['status'] === 'totp') {
            $step = 'totp';
        } elseif ($result['status'] === 'locked') {
            $error = 'Too many attempts. Try again in ' . max(1, (int) ceil($result['retry'] / 60)) . ' min.';
        } else {
            $error = 'Wrong user name or password.';
        }
    }
}

$notice = Http::query('e');
$notices = [
    'discord' => 'Discord login failed. Try again.',
    'access' => 'That Discord account has no access to this dashboard.',
    'state' => 'The Discord login expired. Try again.',
    'out' => 'You are logged out.',
];
$body = '<h1>' . ($step === 'totp' ? 'Two-factor code' : 'Log in') . '</h1>';
if ($error !== '') {
    $body .= View::notice('bad', $error);
} elseif (isset($notices[$notice])) {
    $body .= View::notice($notice === 'out' ? 'ok' : 'bad', $notices[$notice]);
}

if ($step === 'totp') {
    $body .= '<p class="lead">Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>'
        . '<form method="post" class="form" autocomplete="off">' . View::formField()
        . '<input type="hidden" name="step" value="totp">'
        . '<label class="field"><span>Code</span><input name="code" inputmode="text" autocomplete="one-time-code" maxlength="16" required autofocus></label>'
        . '<button class="btn btn-primary" type="submit">Verify</button></form>'
        . '<form method="post" class="form-quiet">' . View::formField()
        . '<input type="hidden" name="step" value="cancel"><button class="link" type="submit">Use another account</button></form>';
} else {
    $body .= '<form method="post" class="form">' . View::formField()
        . '<input type="hidden" name="step" value="password">'
        . '<label class="field"><span>User name</span><input name="username" autocomplete="username" maxlength="64" required autofocus value="' . View::e($username) . '"></label>'
        . '<label class="field"><span>Password</span><input name="password" type="password" autocomplete="current-password" maxlength="1024" required></label>'
        . '<button class="btn btn-primary" type="submit">Log in</button></form>';
    $after = '<p class="form-quiet"><a class="link" href="' . View::e(Http::base() . '/recover.php') . '">Lost the owner password? Recover it with the bot</a></p>';
    if (OAuth::enabled()) {
        $body .= '<div class="or"><span>or</span></div>'
            . '<a class="btn btn-discord" href="' . View::e(Http::base() . '/oauth.php?start=1') . '">Log in with Discord</a>';
    }
    $body .= $after;
}
View::page($step === 'totp' ? 'Two-factor code' : 'Log in', $body);
