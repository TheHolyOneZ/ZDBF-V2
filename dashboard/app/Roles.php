<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Roles
{
    public const BOT = [
        'view', 'logs', 'chat.read', 'chat.send', 'chat.moderate', 'commands.run', 'commands.owner', 'extensions',
        'marketplace', 'files.read', 'files.write', 'config', 'automations', 'scheduler', 'settings', 'backups',
        'backups.restore', 'presence', 'database', 'guilds.leave', 'system',
    ];
    public const WEB = ['users.manage', 'audit.view', 'link.manage'];
    public const OWNER = 'Owner';

    private const BUILTIN = [
        'Owner' => ['*'],
        'Admin' => [
            'view', 'logs', 'chat.read', 'chat.send', 'chat.moderate', 'commands.run', 'commands.owner', 'extensions',
            'marketplace', 'files.read', 'files.write', 'config', 'automations', 'scheduler', 'settings', 'backups',
            'backups.restore', 'presence', 'database', 'guilds.leave', 'audit.view',
        ],
        'Operator' => [
            'view', 'logs', 'chat.read', 'chat.send', 'commands.run', 'extensions', 'files.read', 'automations',
            'scheduler', 'settings', 'backups', 'presence',
        ],
        'Viewer' => ['view', 'logs'],
    ];

    public static function all(): array
    {
        return array_merge(self::BOT, self::WEB);
    }

    public static function seed(Db $db): void
    {
        foreach (self::BUILTIN as $name => $caps) {
            if ($db->val('SELECT COUNT(*) FROM ' . App::T . 'roles WHERE name = ?', [$name]) == 0) {
                $db->insert(App::T . 'roles', ['name' => $name, 'capabilities' => json_encode($caps), 'builtin' => 1]);
            }
        }
    }

    public static function clean(array $caps): array
    {
        return array_values(array_intersect(self::all(), array_filter($caps, 'is_string')));
    }

    public static function decode(?string $json): array
    {
        $caps = json_decode((string) $json, true);
        return is_array($caps) ? array_values(array_filter($caps, 'is_string')) : [];
    }

    public static function topicCapability(string $topic): string
    {
        return match (true) {
            str_starts_with($topic, 'logs') => 'logs',
            str_starts_with($topic, 'chat') => 'chat.read',
            str_starts_with($topic, 'files') => 'files.read',
            str_starts_with($topic, 'database') => 'database',
            default => 'view',
        };
    }

    public static function allows(array $caps, string $capability): bool
    {
        return in_array('*', $caps, true) || in_array($capability, $caps, true);
    }

    public static function list(): array
    {
        $rows = App::db()->all('SELECT r.id, r.name, r.capabilities, r.builtin, (SELECT COUNT(*) FROM ' . App::T
            . 'users u WHERE u.role_id = r.id) AS users FROM ' . App::T . 'roles r ORDER BY r.builtin DESC, r.id');
        return array_map(static fn (array $r): array => [
            'id' => (int) $r['id'],
            'name' => $r['name'],
            'capabilities' => self::decode($r['capabilities']),
            'builtin' => (bool) $r['builtin'],
            'users' => (int) $r['users'],
        ], $rows);
    }

    public static function find(int $id): ?array
    {
        $row = App::db()->one('SELECT id, name, capabilities, builtin FROM ' . App::T . 'roles WHERE id = ?', [$id]);
        if ($row === null) {
            return null;
        }
        return ['id' => (int) $row['id'], 'name' => $row['name'], 'capabilities' => self::decode($row['capabilities']),
            'builtin' => (bool) $row['builtin']];
    }

    public static function idOf(string $name): int
    {
        return (int) (App::db()->val('SELECT id FROM ' . App::T . 'roles WHERE name = ?', [$name]) ?? 0);
    }
}
