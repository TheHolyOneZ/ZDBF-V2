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
if (Http::method() === 'GET') {
    Http::ok(['roles' => Roles::list(), 'capabilities' => ['bot' => Roles::BOT, 'web' => Roles::WEB]]);
}

Auth::csrf();
if (!Auth::isOwner($me)) {
    Http::fail(403, 'forbidden', 'Only an owner can change roles.');
}
$db = App::db();
$t = App::T;
$in = Http::input();
$action = is_string($in['action'] ?? null) ? $in['action'] : '';
$name = is_string($in['name'] ?? null) ? trim($in['name']) : '';
$caps = Roles::clean(is_array($in['capabilities'] ?? null) ? $in['capabilities'] : []);
$nameOk = preg_match('/^[A-Za-z0-9][A-Za-z0-9 _-]{1,31}$/', $name) === 1;

if ($action === 'create') {
    if (!$nameOk) {
        Http::fail(400, 'name', 'Use 2 to 32 letters, digits, spaces, dashes or underscores.');
    }
    if ($db->val('SELECT 1 FROM ' . $t . 'roles WHERE name = ?', [$name]) !== null) {
        Http::fail(409, 'name', 'A role with that name exists.');
    }
    $id = $db->insert($t . 'roles', ['name' => $name, 'capabilities' => json_encode($caps), 'builtin' => 0]);
    Audit::log('role.created', ['role' => $name, 'capabilities' => $caps], $me);
    Http::ok(['id' => $id]);
}

$role = is_int($in['id'] ?? null) ? Roles::find($in['id']) : null;
if ($role === null) {
    Http::fail(404, 'unknown', 'That role no longer exists.');
}
if ($role['name'] === Roles::OWNER) {
    Http::fail(409, 'owner', 'The Owner role always has every permission.');
}

if ($action === 'update') {
    $set = ['capabilities' => json_encode($caps)];
    if (!$role['builtin'] && $name !== '' && $name !== $role['name']) {
        if (!$nameOk) {
            Http::fail(400, 'name', 'Use 2 to 32 letters, digits, spaces, dashes or underscores.');
        }
        if ($db->val('SELECT 1 FROM ' . $t . 'roles WHERE name = ? AND id <> ?', [$name, $role['id']]) !== null) {
            Http::fail(409, 'name', 'A role with that name exists.');
        }
        $set['name'] = $name;
    }
    $db->run('UPDATE ' . $t . 'roles SET ' . implode(', ', array_map(static fn (string $c): string => $c . ' = ?', array_keys($set)))
        . ' WHERE id = ?', array_merge(array_values($set), [$role['id']]));
    Audit::log('role.updated', ['role' => $set['name'] ?? $role['name'], 'capabilities' => $caps], $me);
    Http::ok();
}

if ($action === 'delete') {
    if ($role['builtin']) {
        Http::fail(409, 'builtin', 'Built-in roles cannot be deleted.');
    }
    if ((int) $db->val('SELECT COUNT(*) FROM ' . $t . 'users WHERE role_id = ?', [$role['id']]) > 0) {
        Http::fail(409, 'in_use', 'Move its users to another role first.');
    }
    $db->run('DELETE FROM ' . $t . 'roles WHERE id = ?', [$role['id']]);
    Audit::log('role.deleted', ['role' => $role['name']], $me);
    Http::ok();
}

Http::fail(400, 'action', 'Unknown action.');
