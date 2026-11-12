<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Feed
{
    public const MAX_TOPICS = 40;
    public const EVENT_KEEP = 3600;
    public const EVENT_MAX = 5000;
    public const ONLINE_WINDOW = 75;

    public static function topicOk(mixed $topic): bool
    {
        return is_string($topic) && preg_match('/^[a-z0-9][a-z0-9_.:-]{0,99}$/', $topic) === 1;
    }

    public static function topics(string $csv): array
    {
        $out = [];
        foreach (explode(',', $csv) as $topic) {
            if (self::topicOk($topic)) {
                $out[$topic] = true;
            }
        }
        return array_slice(array_keys($out), 0, self::MAX_TOPICS);
    }

    public static function putState(array $topics): void
    {
        $db = App::db();
        $db->tx(static function (Db $db) use ($topics): void {
            $rev = (int) ($db->val('SELECT COALESCE(MAX(rev), 0) FROM ' . App::T . 'state') ?? 0);
            foreach ($topics as $topic => $data) {
                if (!self::topicOk($topic)) {
                    continue;
                }
                $json = json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
                if ($json === false) {
                    continue;
                }
                $db->upsert(App::T . 'state', ['topic' => $topic], ['rev' => ++$rev, 'data' => $json, 'updated_at' => time()]);
            }
        });
    }

    public static function state(string $topic): mixed
    {
        $json = App::db()->val('SELECT data FROM ' . App::T . 'state WHERE topic = ?', [$topic]);
        return is_string($json) ? json_decode($json, true) : null;
    }

    public static function stateSince(array $topics, int $rev): array
    {
        if ($topics === []) {
            return [];
        }
        $rows = App::db()->all(
            'SELECT topic, rev, data, updated_at FROM ' . App::T . 'state WHERE rev > ? AND topic IN (' . Db::marks(count($topics)) . ')',
            array_merge([$rev], $topics)
        );
        $out = [];
        foreach ($rows as $row) {
            $out[$row['topic']] = ['rev' => (int) $row['rev'], 'at' => (int) $row['updated_at'], 'data' => json_decode((string) $row['data'], true)];
        }
        return $out;
    }

    public static function addEvents(array $events): void
    {
        $db = App::db();
        foreach (array_slice($events, 0, 500) as $event) {
            if (!is_array($event) || !self::topicOk($event['topic'] ?? null)) {
                continue;
            }
            $json = json_encode($event['data'] ?? null, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
            if ($json === false || strlen($json) > 262144) {
                continue;
            }
            $db->insert(App::T . 'events', ['topic' => $event['topic'], 'data' => $json, 'at' => (float) ($event['at'] ?? microtime(true))]);
        }
    }

    public static function lastEventId(): int
    {
        return (int) (App::db()->val('SELECT COALESCE(MAX(id), 0) FROM ' . App::T . 'events') ?? 0);
    }

    public static function eventsSince(array $topics, int $id, int $limit = 300): array
    {
        if ($topics === []) {
            return [];
        }
        $rows = App::db()->all(
            'SELECT id, topic, data, at FROM ' . App::T . 'events WHERE id > ? AND topic IN (' . Db::marks(count($topics)) . ') ORDER BY id LIMIT ?',
            array_merge([$id], $topics, [$limit])
        );
        return array_map(static fn (array $r): array => [
            'id' => (int) $r['id'], 'topic' => $r['topic'], 'at' => (float) $r['at'], 'data' => json_decode((string) $r['data'], true),
        ], $rows);
    }

    public static function watch(string $sessionId, array $topics, int $ttl): void
    {
        $db = App::db();
        $expires = time() + $ttl;
        foreach ($topics as $topic) {
            $db->upsert(App::T . 'watch', ['session_id' => $sessionId, 'kind' => 'topic', 'k' => $topic], ['expires_at' => $expires]);
        }
        if ($topics === []) {
            $db->upsert(App::T . 'watch', ['session_id' => $sessionId, 'kind' => 'open', 'k' => '-'], ['expires_at' => $expires]);
        }
    }

    public static function watching(): array
    {
        $rows = App::db()->all('SELECT DISTINCT kind, k FROM ' . App::T . 'watch WHERE expires_at > ?', [time()]);
        $topics = [];
        foreach ($rows as $row) {
            if ($row['kind'] === 'topic') {
                $topics[] = $row['k'];
            }
        }
        sort($topics, SORT_STRING);
        return ['active' => $rows !== [], 'topics' => $topics, 'digest' => sha1(implode(',', $topics))];
    }

    public static function botStatus(): array
    {
        $bot = BotAuth::bot();
        if ($bot === null) {
            return ['paired' => false, 'online' => false, 'seen_at' => null];
        }
        $seen = (int) $bot['seen_at'];
        return ['paired' => true, 'online' => $seen > 0 && time() - $seen <= self::ONLINE_WINDOW, 'seen_at' => $seen ?: null,
            'paired_at' => (int) $bot['paired_at']];
    }

    public static function prune(): void
    {
        $db = App::db();
        $db->run('DELETE FROM ' . App::T . 'watch WHERE expires_at <= ?', [time()]);
        $db->run('DELETE FROM ' . App::T . 'events WHERE at < ?', [microtime(true) - self::EVENT_KEEP]);
        $last = self::lastEventId();
        if ($last > self::EVENT_MAX) {
            $db->run('DELETE FROM ' . App::T . 'events WHERE id <= ?', [$last - self::EVENT_MAX]);
        }
    }
}
