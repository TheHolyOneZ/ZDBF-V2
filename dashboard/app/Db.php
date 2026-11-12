<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

use PDO;
use PDOException;
use PDOStatement;

final class Db
{
    private int $depth = 0;

    private function __construct(public readonly string $driver, private PDO $pdo)
    {
    }

    public static function open(array $cfg): self
    {
        $options = [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_STRINGIFY_FETCHES => false,
        ];
        $driver = (string) ($cfg['driver'] ?? '');
        if ($driver === 'sqlite') {
            $pdo = new PDO('sqlite:' . $cfg['path'], null, null, $options);
            foreach (['journal_mode=WAL', 'synchronous=NORMAL', 'busy_timeout=5000', 'foreign_keys=ON'] as $pragma) {
                $pdo->exec('PRAGMA ' . $pragma);
            }
            return new self('sqlite', $pdo);
        }
        if ($driver === 'mysql') {
            $name = (string) ($cfg['name'] ?? '');
            $socket = (string) ($cfg['socket'] ?? '');
            $dsn = $socket !== ''
                ? sprintf('mysql:unix_socket=%s;dbname=%s;charset=utf8mb4', $socket, $name)
                : sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', (string) ($cfg['host'] ?? 'localhost'), (int) ($cfg['port'] ?? 3306), $name);
            $pdo = new PDO($dsn, (string) ($cfg['user'] ?? ''), (string) ($cfg['pass'] ?? ''), $options + [
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);
            $pdo->exec("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION', time_zone = '+00:00'");
            return new self('mysql', $pdo);
        }
        throw new \RuntimeException('unknown database driver');
    }

    public static function drivers(): array
    {
        $have = PDO::getAvailableDrivers();
        return array_values(array_intersect(['sqlite', 'mysql'], $have));
    }

    public static function marks(int $count): string
    {
        return implode(',', array_fill(0, max(1, $count), '?'));
    }

    public function run(string $sql, array $params = []): PDOStatement
    {
        for ($attempt = 1; ; $attempt++) {
            try {
                return $this->execute($sql, $params);
            } catch (\PDOException $e) {
                if ($this->depth > 0 || $attempt >= 4 || !$this->retryable($e)) {
                    throw $e;
                }
                usleep(random_int(5000, 30000) * $attempt);
            }
        }
    }

    private function execute(string $sql, array $params): PDOStatement
    {
        $stmt = $this->pdo->prepare($sql);
        $i = 0;
        foreach ($params as $value) {
            $i++;
            if (is_int($value)) {
                $stmt->bindValue($i, $value, PDO::PARAM_INT);
            } elseif (is_bool($value)) {
                $stmt->bindValue($i, $value ? 1 : 0, PDO::PARAM_INT);
            } elseif ($value === null) {
                $stmt->bindValue($i, null, PDO::PARAM_NULL);
            } else {
                $stmt->bindValue($i, (string) $value, PDO::PARAM_STR);
            }
        }
        $stmt->execute();
        return $stmt;
    }

    public function one(string $sql, array $params = []): ?array
    {
        $row = $this->run($sql, $params)->fetch();
        return $row === false ? null : $row;
    }

    public function all(string $sql, array $params = []): array
    {
        return $this->run($sql, $params)->fetchAll();
    }

    public function val(string $sql, array $params = []): mixed
    {
        $value = $this->run($sql, $params)->fetchColumn();
        return $value === false ? null : $value;
    }

    public function insert(string $table, array $row): int
    {
        $cols = array_keys($row);
        $this->run(
            'INSERT INTO ' . $table . ' (' . implode(', ', $cols) . ') VALUES (' . self::marks(count($cols)) . ')',
            array_values($row)
        );
        return (int) $this->pdo->lastInsertId();
    }

    public function tryInsert(string $table, array $row): bool
    {
        try {
            $this->insert($table, $row);
            return true;
        } catch (PDOException $e) {
            if (str_starts_with((string) $e->getCode(), '23')) {
                return false;
            }
            throw $e;
        }
    }

    public function upsert(string $table, array $key, array $values): void
    {
        $row = $key + $values;
        $cols = array_keys($row);
        $sql = 'INSERT INTO ' . $table . ' (' . implode(', ', $cols) . ') VALUES (' . self::marks(count($cols)) . ')';
        if ($this->driver === 'sqlite') {
            $set = implode(', ', array_map(static fn (string $c): string => $c . ' = excluded.' . $c, array_keys($values)));
            $sql .= ' ON CONFLICT(' . implode(', ', array_keys($key)) . ') DO UPDATE SET ' . $set;
        } else {
            $set = implode(', ', array_map(static fn (string $c): string => $c . ' = VALUES(' . $c . ')', array_keys($values)));
            $sql .= ' ON DUPLICATE KEY UPDATE ' . $set;
        }
        $this->run($sql, array_values($row));
    }

    public function tx(callable $fn): mixed
    {
        if ($this->depth > 0) {
            return $fn($this);
        }
        for ($attempt = 1; ; $attempt++) {
            try {
                return $this->attempt($fn);
            } catch (\PDOException $e) {
                if ($attempt >= 4 || !$this->retryable($e)) {
                    throw $e;
                }
                usleep(random_int(5000, 40000) * $attempt);
            }
        }
    }

    private function retryable(\PDOException $e): bool
    {
        $code = (int) ($e->errorInfo[1] ?? 0);
        if ($this->driver === 'sqlite') {
            return $code === 5 || $code === 6;
        }
        return $e->getCode() === '40001' || $code === 1213 || $code === 1205 || $code === 1020;
    }

    private function attempt(callable $fn): mixed
    {
        $this->depth++;
        if ($this->driver === 'sqlite') {
            $this->pdo->exec('BEGIN IMMEDIATE');
        } else {
            $this->pdo->beginTransaction();
        }
        try {
            $result = $fn($this);
            if ($this->driver === 'sqlite') {
                $this->pdo->exec('COMMIT');
            } else {
                $this->pdo->commit();
            }
            return $result;
        } catch (\Throwable $e) {
            try {
                if ($this->driver === 'sqlite') {
                    $this->pdo->exec('ROLLBACK');
                } elseif ($this->pdo->inTransaction()) {
                    $this->pdo->rollBack();
                }
            } catch (\Throwable) {
            }
            throw $e;
        } finally {
            $this->depth--;
        }
    }

    public function exec(string $sql): void
    {
        $this->pdo->exec($sql);
    }
}
