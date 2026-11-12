<?php
declare(strict_types=1);

$data = sys_get_temp_dir() . '/zdbf-dashboard-test-' . bin2hex(random_bytes(4));
mkdir($data, 0700, true);
putenv('ZDBF_DASHBOARD_DATA=' . $data);
require dirname(__DIR__, 3) . '/dashboard/app/bootstrap.php';

use Zdbf\Dashboard\App;
use Zdbf\Dashboard\Auth;
use Zdbf\Dashboard\Crypto;
use Zdbf\Dashboard\Feed;
use Zdbf\Dashboard\Roles;
use Zdbf\Dashboard\Totp;

$count = 0;
$failed = 0;
$check = static function (string $name, bool $ok) use (&$count, &$failed): void {
    $count++;
    if (!$ok) {
        $failed++;
        fwrite(STDERR, 'FAIL ' . $name . "\n");
    }
};

App::setConfig(['app_key' => base64_encode(random_bytes(32))]);

$code = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
$botNonce = str_repeat('0', 32);
$serverNonce = str_repeat('f', 32);
$secret = Crypto::pairSecret($code, $botNonce, $serverNonce, 'abcdef0123456789');
$check('pair code id', Crypto::pairCodeId($code) === '22441069e6aff07212be7b63fcb0b7db');
$check('pair proof', Crypto::pairProof($code, $botNonce, '123456789012345678') === 'c4eb2303459e663a0346b9edd86a57ca11d1b6383b0bf40a9dbf66cfe90bd704');
$check('pair ack', Crypto::pairAck($code, $botNonce, $serverNonce, 'abcdef0123456789') === '568ad9ec6910ab12d93acdcee9486b260b65a5402ffbb1e8cb2c4246094a3419');
$check('pair secret', $secret === '42d4c70c07d1fccfce84044dc8df5c2dee43e90c58f50a14e8249ec01c5a8397');
$check('request signature', Crypto::requestSignature($secret, 'api/bot/push.php', '1700000000', str_repeat('a', 32), '{"v":1}')
    === '058b8b37fe609f3092b1f2ca32ce22a83cb3e2c412bfe73d069440dbfa2c0d14');
$check('response signature', Crypto::responseSignature($secret, 'api/bot/push.php', str_repeat('a', 32), '1700000001', '{"ok":true}')
    === '8cf4038a225aee62451b29a80495d35374bccc972f7d491ce9e0dfdfce62a989');

$sealed = Crypto::seal('the bot secret');
$check('seal hides the text', !str_contains($sealed, 'bot secret') && $sealed !== Crypto::seal('the bot secret'));
$check('open returns the text', Crypto::open($sealed) === 'the bot secret');
$raw = base64_decode($sealed);
$raw[strlen($raw) - 1] = chr(ord($raw[strlen($raw) - 1]) ^ 1);
$check('tampered seal is refused', Crypto::open(base64_encode($raw)) === null);
$check('garbage seal is refused', Crypto::open('not-base64!') === null && Crypto::open('') === null);
$check('base32 length and alphabet', preg_match('/^[A-Z2-7]{32}$/', Crypto::base32(32)) === 1);
$check('base32 decode', Crypto::base32Decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ') === '12345678901234567890');

$rfc = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
$check('totp rfc 6238 t=59', Totp::code($rfc, intdiv(59, 30)) === '287082');
$check('totp rfc 6238 t=1111111109', Totp::code($rfc, intdiv(1111111109, 30)) === '081804');
$check('totp rfc 6238 t=1234567890', Totp::code($rfc, intdiv(1234567890, 30)) === '005924');
$now = 1234567890;
$step = Totp::verify($rfc, '005924', 0, $now);
$check('totp verify accepts the current code', $step === intdiv($now, 30));
$check('totp verify refuses a reused code', Totp::verify($rfc, '005924', (int) $step, $now) === null);
$check('totp verify accepts one step of drift', Totp::verify($rfc, Totp::code($rfc, intdiv($now, 30) - 1), 0, $now) !== null);
$check('totp verify refuses older codes', Totp::verify($rfc, Totp::code($rfc, intdiv($now, 30) - 3), 0, $now) === null);
$check('totp verify refuses junk', Totp::verify($rfc, 'abcdef', 0, $now) === null && Totp::verify($rfc, '12345', 0, $now) === null);
$codes = Totp::recoveryCodes();
$check('recovery codes', count($codes) === 8 && count(array_unique($codes)) === 8 && preg_match('/^[A-Z2-7]{5}-[A-Z2-7]{5}$/', $codes[0]) === 1);
$check('recovery hash ignores case and dashes', Totp::hashRecovery($codes[0]) === Totp::hashRecovery(strtolower(str_replace('-', ' ', $codes[0]))));

$check('roles clean drops unknown names', Roles::clean(['view', 'root', 5, 'users.manage', '*']) === ['view', 'users.manage']);
$check('owner wildcard allows everything', Roles::allows(['*'], 'system') && !Roles::allows(['view'], 'system'));
$check('topic capability', Roles::topicCapability('logs.tail') === 'logs' && Roles::topicCapability('chat.123') === 'chat.read'
    && Roles::topicCapability('overview') === 'view' && Roles::topicCapability('files.tree') === 'files.read');
$check('topic names', Feed::topicOk('chat.123-a_b:c') && !Feed::topicOk('Bad Topic') && !Feed::topicOk('') && !Feed::topicOk(['x'])
    && !Feed::topicOk(str_repeat('a', 101)) && !Feed::topicOk("a\nb"));
$check('topics list is deduplicated and capped', Feed::topics('a,b,a,,B!,c') === ['a', 'b', 'c']
    && count(Feed::topics(implode(',', array_map(static fn (int $i): string => 't' . $i, range(1, 80))))) === Feed::MAX_TOPICS);

$check('password rules', Auth::passwordProblem('short') !== null && Auth::passwordProblem('long enough password') === null
    && Auth::passwordProblem(str_repeat('x', 2000)) !== null);
$check('username rules', Auth::usernameProblem('ok.name-1') === null && Auth::usernameProblem('a') !== null
    && Auth::usernameProblem('has space') !== null && Auth::usernameProblem('<script>') !== null);
$hash = Auth::hash('long enough password');
$check('password hash verifies', password_verify('long enough password', $hash) && !password_verify('other password!!', $hash));

foreach (glob($data . '/*') ?: [] as $file) {
    @unlink($file);
}
@rmdir($data);
echo $count . ' checks, ' . $failed . " failed\n";
exit($failed === 0 ? 0 : 1);
