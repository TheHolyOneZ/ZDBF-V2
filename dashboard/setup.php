<?php
declare(strict_types=1);

require __DIR__ . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Db;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Setup;
use Zdbf\Dashboard\View;

if (App::installed()) {
    View::page('Setup complete', '<h1>Setup is complete</h1>'
        . '<p class="lead">This dashboard is installed. Setup cannot be run again.</p>'
        . '<a class="btn btn-primary" href="' . View::e(Http::base() . '/login.php') . '">Log in</a>'
        . '<p class="hint">Need a new pairing code? Log in and open Settings, then Bot link.</p>');
}

$checks = Setup::checks();
$ready = Setup::ready($checks);
$errors = [];
$e = [View::class, 'e'];

if ($ready && Http::method() === 'POST') {
    if (!View::formValid()) {
        $errors['_form'] = 'The form expired. Try again.';
    } elseif (View::post('probe') !== 'ok') {
        $errors['_form'] = 'The folder check did not pass. Fix the notice below and reload this page.';
    } else {
        $result = Setup::install([
            'setup_key' => View::post('setup_key', 32),
            'username' => View::post('username', 64),
            'password' => is_string($_POST['password'] ?? null) ? $_POST['password'] : '',
            'password2' => is_string($_POST['password2'] ?? null) ? $_POST['password2'] : '',
            'driver' => View::post('driver', 16),
            'db_host' => View::post('db_host'),
            'db_port' => View::post('db_port', 6),
            'db_name' => View::post('db_name'),
            'db_user' => View::post('db_user'),
            'db_pass' => is_string($_POST['db_pass'] ?? null) ? $_POST['db_pass'] : '',
        ]);
        if (isset($result['_pair'])) {
            $pair = $result['_pair'];
            $url = rtrim(Http::url(''), '/');
            View::page('Setup complete', '<h1>Dashboard installed</h1>'
                . '<p class="lead">Last step: connect your bot. Run this command in Discord as the bot owner.</p>'
                . '<div class="codebox"><code id="pair-command">/dashboard pair url:' . $e($url) . ' code:' . $e($pair['code']) . '</code>'
                . '<button class="btn btn-sm" type="button" data-copy="pair-command">Copy</button></div>'
                . '<dl class="facts"><dt>Address</dt><dd>' . $e($url) . '</dd><dt>Pairing code</dt><dd class="mono">' . $e($pair['code'])
                . '</dd><dt>Valid for</dt><dd>10 minutes, one use</dd></dl>'
                . '<p class="hint">The code is shown once. If it expires, log in and create a new one under Settings, then Bot link. '
                . 'The dashboard module must be on: set <code>dashboard = true</code> under <code>[modules]</code> in config.toml.</p>'
                . '<a class="btn btn-primary" href="' . $e(Http::base() . '/login.php') . '">Continue to login</a>',
                ['scripts' => ['setup.js'], 'wide' => true]);
        }
        $errors = $result;
    }
}

$field = static function (string $name, string $label, string $type = 'text', array $attrs = []) use (&$errors, $e): string {
    $value = in_array($type, ['password'], true) ? '' : View::post($name);
    $extra = '';
    foreach ($attrs as $k => $v) {
        $extra .= ' ' . $k . ($v === true ? '' : '="' . $e($v) . '"');
    }
    if ($value === '' && isset($attrs['data-default'])) {
        $value = (string) $attrs['data-default'];
    }
    $error = isset($errors[$name]) ? '<small class="field-error">' . $e($errors[$name]) . '</small>' : '';
    return '<label class="field"><span>' . $e($label) . '</span><input name="' . $e($name) . '" type="' . $e($type) . '" value="'
        . $e($value) . '"' . $extra . '>' . $error . '</label>';
};

$list = '<ul class="checks">';
foreach ($checks as [$label, $ok, $required, $help]) {
    $state = $ok ? 'ok' : ($required ? 'bad' : 'warn');
    $list .= '<li data-state="' . $state . '"><span class="dot"></span><strong>' . $e($label) . '</strong>'
        . ($help !== '' && (!$ok || $label === 'Database driver') ? '<small>' . $e($help) . '</small>' : '') . '</li>';
}
$list .= '<li data-state="wait" id="probe-row"><span class="dot"></span><strong>Private folders protected</strong>'
    . '<small id="probe-text">Checking that "data" and "app" cannot be opened from the web.</small></li></ul>';

$body = '<h1>Set up ZDBF Dashboard</h1><p class="lead">One form, then you pair the bot. Nothing here needs command line access.</p>' . $list;

if (!$ready) {
    $body .= View::notice('bad', 'Fix the items marked in red, then reload this page.');
    View::page('Setup', $body, ['scripts' => ['setup.js'], 'wide' => true]);
}

$keyReady = Setup::key() !== null;
$probe = Setup::probe();
$drivers = Db::drivers();
$chosen = View::post('driver', 16) ?: $drivers[0];
if (isset($errors['_form'])) {
    $body .= View::notice('bad', $errors['_form']);
}
$body .= '<div id="probe-block" class="notice" data-kind="bad" hidden>The "data" or "app" folder can be opened from the web, which would expose '
    . 'passwords and the bot secret. On Apache or LiteSpeed, make sure the .htaccess files were uploaded and AllowOverride is on. '
    . 'On nginx, add the rules from nginx.example.conf. Then reload this page.</div>'
    . '<form method="post" class="form" id="setup-form" data-probe="' . $e($probe) . '" data-base="' . $e(Http::base()) . '">'
    . View::formField() . '<input type="hidden" name="probe" value="">'
    . '<fieldset><legend>1. Setup key</legend>'
    . '<p class="hint">' . ($keyReady
        ? 'The bot showed this key when you ran <code>/dashboard export</code>. It is also in the file <code>data/setup-key.php</code> of this folder, which only you can read through your host\'s file manager or FTP.'
        : 'The data folder is not writable yet.') . '</p>'
    . $field('setup_key', 'Setup key', 'text', ['required' => true, 'autocomplete' => 'off', 'placeholder' => 'XXXX-XXXX-XXXX-XXXX', 'maxlength' => '19'])
    . '</fieldset><fieldset><legend>2. Database</legend><div class="choices">';
foreach ($drivers as $driver) {
    $body .= '<label class="choice"><input type="radio" name="driver" value="' . $driver . '"' . ($driver === $chosen ? ' checked' : '') . '>'
        . '<span><strong>' . ($driver === 'sqlite' ? 'SQLite' : 'MySQL / MariaDB') . '</strong><small>'
        . ($driver === 'sqlite' ? 'Nothing to configure. One file in the protected data folder.' : 'Use a database from your hosting panel.')
        . '</small></span></label>';
}
$body .= '</div>' . (isset($errors['driver']) ? '<small class="field-error">' . $e($errors['driver']) . '</small>' : '')
    . '<div class="grid" id="mysql-fields"' . ($chosen === 'mysql' ? '' : ' hidden') . '>'
    . $field('db_host', 'Host', 'text', ['data-default' => 'localhost', 'maxlength' => '255'])
    . $field('db_port', 'Port', 'text', ['data-default' => '3306', 'inputmode' => 'numeric', 'maxlength' => '5'])
    . $field('db_name', 'Database name', 'text', ['maxlength' => '64'])
    . $field('db_user', 'Database user', 'text', ['maxlength' => '64', 'autocomplete' => 'off'])
    . $field('db_pass', 'Database password', 'password', ['maxlength' => '255', 'autocomplete' => 'new-password'])
    . '</div></fieldset><fieldset><legend>3. Owner account</legend><div class="grid">'
    . $field('username', 'User name', 'text', ['required' => true, 'autocomplete' => 'username', 'maxlength' => '32'])
    . '<span></span>'
    . $field('password', 'Password (12 characters or more)', 'password', ['required' => true, 'autocomplete' => 'new-password', 'minlength' => '12', 'maxlength' => '1024'])
    . $field('password2', 'Repeat password', 'password', ['required' => true, 'autocomplete' => 'new-password', 'maxlength' => '1024'])
    . '</div><p class="hint">You can add two-factor login and Discord login after the first login.</p></fieldset>'
    . '<button class="btn btn-primary" type="submit" id="setup-submit" disabled>Install</button></form>';
View::page('Setup', $body, ['scripts' => ['setup.js'], 'wide' => true]);
