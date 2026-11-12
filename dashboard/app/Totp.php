<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Totp
{
    public const PERIOD = 30;
    public const DIGITS = 6;

    public static function secret(): string
    {
        return Crypto::base32(32);
    }

    public static function code(string $secret, int $step): string
    {
        $key = Crypto::base32Decode($secret);
        $hash = hash_hmac('sha1', pack('J', $step), $key, true);
        $offset = ord($hash[19]) & 0x0f;
        $value = ((ord($hash[$offset]) & 0x7f) << 24)
            | (ord($hash[$offset + 1]) << 16)
            | (ord($hash[$offset + 2]) << 8)
            | ord($hash[$offset + 3]);
        return str_pad((string) ($value % (10 ** self::DIGITS)), self::DIGITS, '0', STR_PAD_LEFT);
    }

    public static function verify(string $secret, string $code, int $lastStep, ?int $now = null): ?int
    {
        $code = preg_replace('/\D/', '', $code) ?? '';
        if (strlen($code) !== self::DIGITS) {
            return null;
        }
        $current = intdiv($now ?? time(), self::PERIOD);
        foreach ([0, -1, 1] as $drift) {
            $step = $current + $drift;
            if ($step > $lastStep && hash_equals(self::code($secret, $step), $code)) {
                return $step;
            }
        }
        return null;
    }

    public static function uri(string $secret, string $account, string $issuer): string
    {
        return 'otpauth://totp/' . rawurlencode($issuer . ':' . $account) . '?secret=' . $secret
            . '&issuer=' . rawurlencode($issuer) . '&algorithm=SHA1&digits=' . self::DIGITS . '&period=' . self::PERIOD;
    }

    public static function recoveryCodes(int $count = 8): array
    {
        $codes = [];
        for ($i = 0; $i < $count; $i++) {
            $raw = Crypto::base32(10);
            $codes[] = substr($raw, 0, 5) . '-' . substr($raw, 5);
        }
        return $codes;
    }

    public static function hashRecovery(string $code): string
    {
        return Crypto::keyed('recovery', strtoupper(preg_replace('/[^A-Za-z2-7]/', '', $code) ?? ''));
    }
}
