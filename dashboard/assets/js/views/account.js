import { get, post, url } from '../core/api.js';
import { button, h, mount, s } from '../core/dom.js';
import { session } from '../core/store.js';
import { field, modal } from '../ui/modal.js';
import { card, copyButton, facts, pageHead, pill, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

function loadQr() {
  if (window.qrcode) {
    return Promise.resolve(window.qrcode);
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `${url('assets/vendor/qrcode.js')}?v=${encodeURIComponent(session.version)}`;
    script.addEventListener('load', () => resolve(window.qrcode));
    script.addEventListener('error', () => reject(new Error('The QR code could not be drawn.')));
    document.head.appendChild(script);
  });
}

async function qrSvg(text) {
  const make = await loadQr();
  const code = make(0, 'M');
  code.addData(text);
  code.make();
  const size = code.getModuleCount();
  let d = '';
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      if (code.isDark(row, col)) {
        d += `M${col} ${row}h1v1h-1z`;
      }
    }
  }
  return s('svg', { class: 'qr', viewBox: `-3 -3 ${size + 6} ${size + 6}`, role: 'img', 'aria-label': 'QR code for your authenticator app' },
    s('rect', { x: -3, y: -3, width: size + 6, height: size + 6, fill: '#ffffff' }), s('path', { d, fill: '#000000' }));
}

function recoveryBox(codes) {
  const text = codes.join('\n');
  return [
    h('p', { class: 'modal-text', text: 'Save these recovery codes somewhere safe. Each one works once if you lose your phone. They are not shown again.' }),
    h('pre', { class: 'codes', text }),
    copyButton(() => text, 'Copy codes'),
  ];
}

export default function account(page) {
  let alive = true;
  const profile = card('Profile');
  const password = card('Password');
  const twoFactor = card('Two-factor login', { sub: 'A code from an authenticator app is asked for after your password.' });
  page.append(pageHead('Account', 'Your login and security settings.'), h('div', { class: 'grid-2' }, h('div', { class: 'stack' }, profile.el, twoFactor.el), password.el));
  profile.body.appendChild(skeleton(3));

  function currentField(user) {
    return user.has_password ? field('Current password', { name: 'current', type: 'password', required: true, autocomplete: 'current-password', maxlength: '1024' }) : null;
  }

  function renderPassword(user) {
    const form = h('form', { class: 'form-stack' },
      currentField(user),
      field('New password', { name: 'new', type: 'password', required: true, minlength: '12', maxlength: '1024', autocomplete: 'new-password' }, '12 characters or more.'),
      field('Repeat new password', { name: 'repeat', type: 'password', required: true, maxlength: '1024', autocomplete: 'new-password' }),
      h('div', null, button(user.has_password ? 'Change password' : 'Set a password', { class: 'btn btn-primary', type: 'submit' })));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = new FormData(form);
      if (values.get('new') !== values.get('repeat')) {
        failure(new Error('The two new passwords do not match.'));
        return;
      }
      try {
        const result = await post('api/account.php', { action: 'password', current: values.get('current') || '', new: values.get('new') });
        toast(result.sessions_ended ? `Password changed. ${result.sessions_ended} other session${result.sessions_ended === 1 ? '' : 's'} logged out.` : 'Password changed.', { kind: 'ok' });
        load();
      } catch (error) {
        failure(error);
      }
    });
    mount(password.body, form);
  }

  function enableTotp(user) {
    const dialog = modal({
      title: 'Turn on two-factor login',
      body: [currentField(user), h('p', { class: 'modal-text', text: user.has_password ? 'Confirm your password to start.' : 'Start the setup.' })],
      actions: [{ label: 'Cancel' }, { label: 'Continue', primary: true, submit: true, run: async (data) => {
        const begin = await post('api/account.php', { action: 'totp_begin', current: data.get('current') || '' });
        const qr = await qrSvg(begin.uri).catch(() => null);
        setTimeout(() => confirmTotp(begin, qr), 160);
      } }],
    });
    return dialog;
  }

  function confirmTotp(begin, qr) {
    modal({
      title: 'Scan and confirm',
      body: [
        h('p', { class: 'modal-text', text: 'Scan this with your authenticator app, or type the key by hand. Then enter the 6-digit code it shows.' }),
        h('div', { class: 'qr-row' }, qr, h('div', { class: 'qr-side' }, h('span', { class: 'muted', text: 'Key' }),
          h('code', { class: 'secret', text: begin.secret.replace(/(.{4})/g, '$1 ').trim() }), copyButton(() => begin.secret, 'Copy key'))),
        field('Code', { name: 'code', required: true, inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '8', pattern: '[0-9 ]{6,8}' }),
      ],
      actions: [{ label: 'Cancel' }, { label: 'Turn on', primary: true, submit: true, run: async (data) => {
        const result = await post('api/account.php', { action: 'totp_confirm', code: data.get('code') });
        setTimeout(() => modal({ title: 'Two-factor login is on', body: recoveryBox(result.recovery), actions: [{ label: 'I saved them', primary: true }] }), 160);
        load();
      } }],
    });
  }

  function passwordPrompt(title, text, label, action, after, danger = false) {
    const user = session.user;
    modal({
      title,
      body: [h('p', { class: 'modal-text', text }), currentField(user)],
      actions: [{ label: 'Cancel' }, { label, primary: !danger, danger, submit: true, run: async (data) => {
        const result = await post('api/account.php', { action, current: data.get('current') || '' });
        after(result);
        load();
      } }],
    });
  }

  function renderTwoFactor(user, recoveryLeft) {
    if (!user.totp) {
      mount(twoFactor.body,
        h('p', { class: 'muted', text: 'Off. Turning it on protects the account even if the password leaks.' }),
        h('div', { class: 'card-foot' }, button('Turn on', { class: 'btn btn-primary', onClick: () => enableTotp(user) }, 'shield')));
      return;
    }
    mount(twoFactor.body,
      facts([['State', pill('On', 'ok')], ['Recovery codes left', recoveryLeft <= 2 ? pill(String(recoveryLeft), 'warn') : String(recoveryLeft)]]),
      h('div', { class: 'card-foot' },
        button('New recovery codes', { onClick: () => passwordPrompt('New recovery codes', 'The old codes stop working.', 'Create codes', 'recovery',
          (result) => setTimeout(() => modal({ title: 'New recovery codes', body: recoveryBox(result.recovery), actions: [{ label: 'I saved them', primary: true }] }), 160)) }),
        button('Turn off', { class: 'btn btn-danger', onClick: () => passwordPrompt('Turn off two-factor login?', 'Your account will only be protected by its password.', 'Turn off', 'totp_disable',
          () => toast('Two-factor login is off.', { kind: 'ok' }), true) })));
  }

  async function load() {
    let data;
    try {
      data = await get('api/account.php');
    } catch (error) {
      failure(error);
      return;
    }
    if (!alive) {
      return;
    }
    const user = data.user;
    session.user = user;
    mount(profile.body, facts([
      ['User name', user.username],
      ['Role', user.role],
      ['Password', user.has_password ? 'Set' : pill('Not set', 'warn')],
      ['Discord', user.discord ? (user.discord.name || user.discord.id) : 'Not linked'],
    ]), h('p', { class: 'muted', text: 'An owner can change your role and Discord link under Users and roles.' }));
    renderPassword(user);
    renderTwoFactor(user, data.recovery_left);
  }

  load();
  return () => { alive = false; };
}
