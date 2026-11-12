<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Audit;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Http;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Session;

Http::need('GET', 'POST');
$me = Auth::needCap('users.manage');
$db = App::db();
$t = App::T;

$owners = static fn (): int => (int) $db->val(
    'SELECT COUNT(*) FROM ' . $t . 'users u JOIN ' . $t . 'roles r ON r.id = u.role_id WHERE r.name = ? AND u.disabled = 0',
    [Roles::OWNER]
);

if (Http::method() === 'GET') {
    $rows = $db->all('SELECT u.id, u.username, u.role_id, r.name AS role, u.discord_id, u.discord_name, u.totp_enabled, u.disabled, '
        . 'u.created_at, u.last_login, (u.password_hash IS NOT NULL) AS has_password FROM ' . $t . 'users u JOIN ' . $t
        . 'roles r ON r.id = u.role_id ORDER BY u.id');
    Http::ok(['users' => array_map(static fn (array $r): array => [
        'id' => (int) $r['id'],
        'username' => $r['username'],
        'role_id' => (int) $r['role_id'],
        'role' => $r['role'],
        'discord_id' => $r['discord_id'],
        'discord_name' => $r['discord_name'],
        'totp' => (int) $r['totp_enabled'] === 1,
        'disabled' => (int) $r['disabled'] === 1,
        'has_password' => (int) $r['has_password'] === 1,
        'created_at' => (int) $r['created_at'],
        'last_login' => $r['last_login'] === null ? null : (int) $r['last_login'],
        'self' => (int) $r['id'] === $me['id'],
    ], $rows), 'roles' => Roles::list()]);
}

Auth::csrf();
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';
$isOwner = Auth::isOwner($me);

$roleFor = static function (mixed $id) use ($isOwner): array {
    $role = is_int($id) ? Roles::find($id) : null;
    if ($role === null) {
        Http::fail(400, 'role', 'Choose a role.');
    }
    if ($role['name'] === Roles::OWNER && !$isOwner) {
        Http::fail(403, 'forbidden', 'Only an owner can give the Owner role.');
    }
    return $role;
};
$discord = static function (mixed $value): ?string {
    if ($value === null || $value === '') {
        return null;
    }
    if (!is_string($value) || preg_match('/^\d{5,25}$/', $value) !== 1) {
        Http::fail(400, 'discord', 'A Discord ID is a number of 17 to 20 digits.');
    }
    return $value;
};

if ($action === 'create') {
    $username = is_string($in['username'] ?? null) ? trim($in['username']) : '';
    $password = is_string($in['password'] ?? null) ? $in['password'] : '';
    $discordId = $discord($in['discord_id'] ?? null);
    $role = $roleFor($in['role_id'] ?? null);
    if (($problem = Auth::usernameProblem($username)) !== null) {
        Http::fail(400, 'username', $problem);
    }
    if ($password === '' && $discordId === null) {
        Http::fail(400, 'password', 'Set a password or a Discord ID so the user can log in.');
    }
    if ($password !== '' && ($problem = Auth::passwordProblem($password)) !== null) {
        Http::fail(400, 'password', $problem);
    }
    if ($db->val('SELECT 1 FROM ' . $t . 'users WHERE username = ?', [$username]) !== null) {
        Http::fail(409, 'username', 'That user name is taken.');
    }
    if ($discordId !== null && $db->val('SELECT 1 FROM ' . $t . 'users WHERE discord_id = ?', [$discordId]) !== null) {
        Http::fail(409, 'discord', 'That Discord account is linked to another user.');
    }
    $id = $db->insert($t . 'users', [
        'username' => $username,
        'password_hash' => $password === '' ? null : Auth::hash($password),
        'role_id' => $role['id'],
        'discord_id' => $discordId,
        'created_at' => time(),
    ]);
    Audit::log('user.created', ['user' => $username, 'role' => $role['name']], $me);
    Http::ok(['id' => $id]);
}

$target = is_int($in['id'] ?? null)
    ? $db->one('SELECT u.*, r.name AS role_name FROM ' . $t . 'users u JOIN ' . $t . 'roles r ON r.id = u.role_id WHERE u.id = ?', [$in['id']])
    : null;
if ($target === null) {
    Http::fail(404, 'unknown', 'That user no longer exists.');
}
$targetId = (int) $target['id'];
$targetOwner = $target['role_name'] === Roles::OWNER;
if ($targetOwner && !$isOwner) {
    Http::fail(403, 'forbidden', 'Only an owner can change an owner.');
}
$lastOwner = $targetOwner && (int) $target['disabled'] === 0 && $owners() <= 1;

if ($action === 'update') {
    $set = [];
    $changed = [];
    if (array_key_exists('role_id', $in)) {
        $role = $roleFor($in['role_id']);
        if ($role['id'] !== (int) $target['role_id']) {
            if ($lastOwner) {
                Http::fail(409, 'last_owner', 'This is the only owner. Make someone else an owner first.');
            }
            $set['role_id'] = $role['id'];
            $changed[] = 'role';
        }
    }
    if (array_key_exists('disabled', $in)) {
        $disabled = $in['disabled'] === true;
        if ($disabled && $targetId === $me['id']) {
            Http::fail(409, 'self', 'You cannot disable your own account.');
        }
        if ($disabled && $lastOwner) {
            Http::fail(409, 'last_owner', 'This is the only owner.');
        }
        $set['disabled'] = $disabled ? 1 : 0;
        $changed[] = $disabled ? 'disabled' : 'enabled';
    }
    if (is_string($in['password'] ?? null) && $in['password'] !== '') {
        if (($problem = Auth::passwordProblem($in['password'])) !== null) {
            Http::fail(400, 'password', $problem);
        }
        $set['password_hash'] = Auth::hash($in['password']);
        $changed[] = 'password';
    }
    if (array_key_exists('discord_id', $in)) {
        $discordId = $discord($in['discord_id']);
        if ($discordId !== null && $db->val('SELECT 1 FROM ' . $t . 'users WHERE discord_id = ? AND id <> ?', [$discordId, $targetId]) !== null) {
            Http::fail(409, 'discord', 'That Discord account is linked to another user.');
        }
        if ($discordId === null && $target['password_hash'] === null && !isset($set['password_hash'])) {
            Http::fail(409, 'discord', 'This user has no password. Set one before removing the Discord link.');
        }
        $set['discord_id'] = $discordId;
        $changed[] = 'discord';
    }
    if (($in['reset_totp'] ?? false) === true) {
        $set['totp_enabled'] = 0;
        $set['totp_secret'] = null;
        $set['recovery'] = null;
        $changed[] = 'two-factor reset';
    }
    if ($set !== []) {
        $db->run('UPDATE ' . $t . 'users SET ' . implode(', ', array_map(static fn (string $c): string => $c . ' = ?', array_keys($set)))
            . ' WHERE id = ?', array_merge(array_values($set), [$targetId]));
        if (array_intersect($changed, ['disabled', 'password', 'role', 'two-factor reset']) !== [] && $targetId !== $me['id']) {
            Session::destroyFor($targetId);
        }
        Audit::log('user.updated', ['user' => $target['username'], 'changed' => $changed], $me);
    }
    Http::ok(['changed' => $changed]);
}

if ($action === 'delete') {
    if ($targetId === $me['id']) {
        Http::fail(409, 'self', 'You cannot delete your own account.');
    }
    if ($lastOwner) {
        Http::fail(409, 'last_owner', 'This is the only owner.');
    }
    Session::destroyFor($targetId);
    $db->run('DELETE FROM ' . $t . 'users WHERE id = ?', [$targetId]);
    Audit::log('user.deleted', ['user' => $target['username']], $me);
    Http::ok();
}

Http::fail(400, 'action', 'Unknown action.');
