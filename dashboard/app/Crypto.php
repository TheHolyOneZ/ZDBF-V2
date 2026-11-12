<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class Crypto
{
    private const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

    public static function hex(int $bytes): string
    {
        return bin2hex(random_bytes($bytes));
    }

    public static function base32(int $chars): string
    {
        $out = '';
        foreach (str_split(random_bytes($chars)) as $byte) {
            $out .= self::B32[ord($byte) & 31];
        }
        return $out;
    }

    public static function base32Decode(string $text): string
    {
        $text = strtoupper(preg_replace('/[^A-Za-z2-7]/', '', $text) ?? '');
        $bits = '';
        foreach (str_split($text) as $char) {
            $bits .= str_pad(decbin((int) strpos(self::B32, $char)), 5, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 8) as $chunk) {
            if (strlen($chunk) === 8) {
                $out .= chr((int) bindec($chunk));
            }
        }
        return $out;
    }

    public static function mac(string $key, string ...$parts): string
    {
        return hash_hmac('sha256', implode("\n", $parts), $key);
    }

    private static function key(): string
    {
        $key = base64_decode((string) App::config('app_key', ''), true);
        if ($key === false || strlen($key) !== 32) {
            throw new \RuntimeException('the application key is missing');
        }
        return $key;
    }

    public static function seal(string $plain): string
    {
        $nonce = random_bytes(12);
        $tag = '';
        $cipher = openssl_encrypt($plain, 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, $nonce, $tag);
        if ($cipher === false) {
            throw new \RuntimeException('encryption failed');
        }
        return base64_encode($nonce . $tag . $cipher);
    }

    public static function open(string $sealed): ?string
    {
        $raw = base64_decode($sealed, true);
        if ($raw === false || strlen($raw) < 28) {
            return null;
        }
        $plain = openssl_decrypt(substr($raw, 28), 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, substr($raw, 0, 12), substr($raw, 12, 16));
        return $plain === false ? null : $plain;
    }

    public static function keyed(string $purpose, string $value): string
    {
        return hash_hmac('sha256', $purpose . "\n" . $value, self::key());
    }

    public static function pairCodeId(string $code): string
    {
        return substr(hash('sha256', "zdbf-pair-id\n" . $code), 0, 32);
    }

    public static function pairProof(string $code, string $botNonce, string $botId): string
    {
        return self::mac($code, 'zdbf-pair-proof', $botNonce, $botId);
    }

    public static function pairAck(string $code, string $botNonce, string $serverNonce, string $installId): string
    {
        return self::mac($code, 'zdbf-pair-ack', $botNonce, $serverNonce, $installId);
    }

    public static function pairSecret(string $code, string $botNonce, string $serverNonce, string $installId): string
    {
        return self::mac($code, 'zdbf-dashboard-secret-v1', $botNonce, $serverNonce, $installId);
    }

    public static function requestSignature(string $secret, string $path, string $timestamp, string $nonce, string $body): string
    {
        return self::mac((string) hex2bin($secret), 'POST', $path, $timestamp, $nonce, hash('sha256', $body));
    }

    public static function responseSignature(string $secret, string $path, string $nonce, string $timestamp, string $body): string
    {
        return self::mac((string) hex2bin($secret), 'RESP', $path, $nonce, $timestamp, hash('sha256', $body));
    }
}
