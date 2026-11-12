<?php
declare(strict_types=1);

namespace Zdbf\Dashboard;

final class OAuth
{
    private const API = 'https://discord.com/api/v10';
    public const STATE_COOKIE = 'zdbf_oauth';

    public static function clientId(): string
    {
        return (string) App::config('oauth.client_id', '');
    }

    private static function clientSecret(): ?string
    {
        $sealed = (string) App::config('oauth.client_secret', '');
        return $sealed === '' ? null : Crypto::open($sealed);
    }

    public static function enabled(): bool
    {
        return App::installed() && (bool) App::config('oauth.enabled', false) && self::clientId() !== ''
            && self::clientSecret() !== null;
    }

    public static function redirectUri(): string
    {
        return Http::url('oauth.php');
    }

    public static function authorizeUrl(string $state): string
    {
        return 'https://discord.com/oauth2/authorize?' . http_build_query([
            'response_type' => 'code',
            'client_id' => self::clientId(),
            'scope' => 'identify',
            'state' => $state,
            'redirect_uri' => self::redirectUri(),
            'prompt' => 'none',
        ]);
    }

    public static function fetchUser(string $code): ?array
    {
        $secret = self::clientSecret();
        if ($secret === null) {
            return null;
        }
        $token = self::http('POST', self::API . '/oauth2/token', ['Content-Type: application/x-www-form-urlencoded'], http_build_query([
            'grant_type' => 'authorization_code',
            'code' => $code,
            'redirect_uri' => self::redirectUri(),
            'client_id' => self::clientId(),
            'client_secret' => $secret,
        ]));
        $access = is_array($token) ? ($token['access_token'] ?? null) : null;
        if (!is_string($access) || $access === '') {
            return null;
        }
        $user = self::http('GET', self::API . '/users/@me', ['Authorization: Bearer ' . $access], null);
        if (!is_array($user) || !isset($user['id']) || preg_match('/^\d{5,25}$/', (string) $user['id']) !== 1) {
            return null;
        }
        return ['id' => (string) $user['id'], 'name' => substr((string) ($user['global_name'] ?? $user['username'] ?? 'Discord user'), 0, 100)];
    }

    private static function http(string $method, string $url, array $headers, ?string $body): ?array
    {
        $headers[] = 'Accept: application/json';
        $headers[] = 'User-Agent: ZDBF-Dashboard/' . App::VERSION;
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_CUSTOMREQUEST => $method,
                CURLOPT_HTTPHEADER => $headers,
                CURLOPT_TIMEOUT => 10,
                CURLOPT_FOLLOWLOCATION => false,
                CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
            ]);
            if ($body !== null) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
            }
            $raw = curl_exec($ch);
            $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            if (!is_string($raw) || $status < 200 || $status >= 300) {
                return null;
            }
        } else {
            $context = stream_context_create(['http' => [
                'method' => $method,
                'header' => implode("\r\n", $headers),
                'content' => $body ?? '',
                'timeout' => 10,
                'follow_location' => 0,
                'ignore_errors' => false,
            ]]);
            $raw = @file_get_contents($url, false, $context);
            if (!is_string($raw)) {
                return null;
            }
        }
        $data = json_decode($raw, true);
        return is_array($data) ? $data : null;
    }
}
