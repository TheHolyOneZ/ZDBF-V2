<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Schema
{
    private const MIGRATIONS = [
        1 => [
            'CREATE TABLE {t}roles (id {pk}, name VARCHAR(64) NOT NULL UNIQUE, capabilities {text} NOT NULL, builtin INTEGER NOT NULL DEFAULT 0){eng}',
            'CREATE TABLE {t}users (id {pk}, username VARCHAR(64) NOT NULL UNIQUE, password_hash VARCHAR(255), role_id {big} NOT NULL, discord_id VARCHAR(32) UNIQUE, discord_name VARCHAR(100), totp_secret VARCHAR(255), totp_enabled INTEGER NOT NULL DEFAULT 0, totp_step {big} NOT NULL DEFAULT 0, recovery {text}, disabled INTEGER NOT NULL DEFAULT 0, created_at {big} NOT NULL, last_login {big}){eng}',
            'CREATE TABLE {t}sessions (id CHAR(64) PRIMARY KEY, user_id {big} NOT NULL, csrf CHAR(64) NOT NULL, stage VARCHAR(8) NOT NULL, created_at {big} NOT NULL, seen_at {big} NOT NULL, expires_at {big} NOT NULL, ip VARCHAR(64), agent VARCHAR(255)){eng}',
            'CREATE INDEX {t}sessions_user ON {t}sessions (user_id)',
            'CREATE TABLE {t}limits (k VARCHAR(128) PRIMARY KEY, hits INTEGER NOT NULL, reset_at {big} NOT NULL){eng}',
            'CREATE TABLE {t}bot (id INTEGER PRIMARY KEY, bot_id VARCHAR(32), secret {text} NOT NULL, paired_at {big} NOT NULL, seen_at {big} NOT NULL DEFAULT 0, version VARCHAR(32)){eng}',
            'CREATE TABLE {t}pairing (code_id CHAR(32) PRIMARY KEY, code {text} NOT NULL, expires_at {big} NOT NULL, attempts INTEGER NOT NULL DEFAULT 0){eng}',
            'CREATE TABLE {t}nonces (nonce CHAR(32) PRIMARY KEY, expires_at {big} NOT NULL){eng}',
            'CREATE TABLE {t}commands (id CHAR(32) PRIMARY KEY, type VARCHAR(100) NOT NULL, args {text} NOT NULL, user_id {big}, user_name VARCHAR(64), user_role VARCHAR(64), status VARCHAR(24) NOT NULL, created_at {big} NOT NULL, sent_at {big}, acked INTEGER NOT NULL DEFAULT 0, done_at {big}, result {text}){eng}',
            'CREATE INDEX {t}commands_status ON {t}commands (status, created_at)',
            'CREATE TABLE {t}state (topic VARCHAR(100) PRIMARY KEY, rev {big} NOT NULL, data {text} NOT NULL, updated_at {big} NOT NULL){eng}',
            'CREATE TABLE {t}events (id {pk}, topic VARCHAR(100) NOT NULL, data {text} NOT NULL, at DOUBLE NOT NULL){eng}',
            'CREATE INDEX {t}events_topic ON {t}events (topic, id)',
            'CREATE TABLE {t}watch (session_id CHAR(64) NOT NULL, kind VARCHAR(16) NOT NULL, k VARCHAR(100) NOT NULL, expires_at {big} NOT NULL, PRIMARY KEY (session_id, kind, k)){eng}',
            'CREATE TABLE {t}audit (id {pk}, at {big} NOT NULL, user_id {big}, user_name VARCHAR(64), action VARCHAR(100) NOT NULL, detail {text}, ip VARCHAR(64)){eng}',
        ],
    ];

    public static function migrate(Db $db): int
    {
        $mysql = $db->driver === 'mysql';
        $map = [
            '{t}' => App::T,
            '{pk}' => $mysql ? 'BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY' : 'INTEGER PRIMARY KEY AUTOINCREMENT',
            '{big}' => $mysql ? 'BIGINT' : 'INTEGER',
            '{text}' => $mysql ? 'MEDIUMTEXT' : 'TEXT',
            '{eng}' => $mysql ? ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci' : '',
        ];
        $db->exec(strtr('CREATE TABLE IF NOT EXISTS {t}meta (k VARCHAR(64) PRIMARY KEY, v {text} NOT NULL){eng}', $map));
        $current = (int) ($db->val('SELECT v FROM ' . App::T . 'meta WHERE k = ?', ['schema']) ?? 0);
        foreach (self::MIGRATIONS as $version => $statements) {
            if ($version <= $current) {
                continue;
            }
            foreach ($statements as $sql) {
                $db->exec(strtr($sql, $map));
            }
            $db->upsert(App::T . 'meta', ['k' => 'schema'], ['v' => (string) $version]);
            $current = $version;
        }
        Roles::seed($db);
        return $current;
    }

    public static function tables(): array
    {
        return array_map(static fn (string $n): string => App::T . $n, [
            'audit', 'watch', 'events', 'state', 'commands', 'nonces', 'pairing', 'bot', 'limits', 'sessions',
            'users', 'roles', 'meta',
        ]);
    }
}
