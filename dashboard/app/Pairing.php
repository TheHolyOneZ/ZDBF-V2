<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Pairing
{
    public const TTL = 600;

    public static function create(): array
    {
        $code = Crypto::base32(32);
        $expires = time() + self::TTL;
        $db = App::db();
        $db->run('DELETE FROM ' . App::T . 'pairing');
        $db->insert(App::T . 'pairing', [
            'code_id' => Crypto::pairCodeId($code),
            'code' => Crypto::seal($code),
            'expires_at' => $expires,
            'attempts' => 0,
        ]);
        return ['code' => implode('-', str_split($code, 4)), 'expires_at' => $expires];
    }

    public static function pending(): ?int
    {
        $expires = App::db()->val('SELECT MAX(expires_at) FROM ' . App::T . 'pairing WHERE expires_at > ? AND attempts < 5', [time()]);
        return $expires === null ? null : (int) $expires;
    }
}
