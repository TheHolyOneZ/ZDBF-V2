import { get, post } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { ago } from '../core/format.js';
import { session, topic } from '../core/store.js';
import { confirm, field, modal } from '../ui/modal.js';
import { card, copyButton, facts, pageHead, pill, segmented, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

const WEB_LABELS = {
  'users.manage': 'Manage dashboard users and roles',
  'audit.view': 'Read the audit logs',
  'link.manage': 'Pair and unpair the bot',
};

export default function access(page) {
  let tab = 'users';
  let alive = true;
  let users = [];
  let roles = [];
  const owner = session.user.owner;
  const box = card(null);
  const actions = h('div', { class: 'page-actions' });
  const tabs = segmented([
    { value: 'users', label: 'Users' }, { value: 'roles', label: 'Roles' },
    ...(owner ? [{ value: 'discord', label: 'Login and website' }] : []),
  ], tab, (next) => { tab = next; render(); }, 'Section');
  page.append(pageHead('Users and roles', 'Who can log in to this dashboard and what they may do.', actions), h('div', { class: 'tabs-row' }, tabs.el), box.el);

  function roleOptions() {
    return roles.filter((r) => owner || r.name !== 'Owner').map((r) => ({ value: String(r.id), label: r.name }));
  }

  function userForm(user) {
    const editing = Boolean(user);
    const body = [
      editing ? null : field('User name', { name: 'username', required: true, maxlength: '32', autocomplete: 'off', pattern: '[A-Za-z0-9][A-Za-z0-9._-]{2,31}' },
        '3 to 32 letters, digits, dots, dashes or underscores.'),
      field('Role', { name: 'role_id', options: roleOptions(), value: String(user?.role_id ?? roles.find((r) => r.name === 'Viewer')?.id ?? '') }),
      field(editing ? 'New password' : 'Password', { name: 'password', type: 'password', minlength: '12', maxlength: '1024', autocomplete: 'new-password' },
        editing ? 'Leave empty to keep the current one.' : '12 characters or more. Leave empty if they only log in with Discord.'),
      field('Discord user ID', { name: 'discord_id', inputmode: 'numeric', maxlength: '25', value: user?.discord_id || '', autocomplete: 'off' },
        'Lets this user log in with Discord. Right-click a user in Discord with Developer Mode on to copy the ID.'),
      editing && !user.self ? h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'disabled', checked: user.disabled || null }), h('span', { text: 'Disabled (cannot log in)' })) : null,
      editing && user.totp ? h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'reset_totp' }), h('span', { text: 'Turn off their two-factor login (lost phone)' })) : null,
    ];
    modal({
      title: editing ? `Edit ${user.username}` : 'Add a user',
      body,
      actions: [{ label: 'Cancel' }, { label: editing ? 'Save' : 'Add user', primary: true, submit: true, run: async (data) => {
        const payload = {
          action: editing ? 'update' : 'create',
          role_id: Number(data.get('role_id')),
          discord_id: String(data.get('discord_id') || '').trim() || null,
        };
        const password = String(data.get('password') || '');
        if (password) {
          payload.password = password;
        }
        if (editing) {
          payload.id = user.id;
          if (!user.self) {
            payload.disabled = data.get('disabled') === 'on';
          }
          if (data.get('reset_totp') === 'on') {
            payload.reset_totp = true;
          }
        } else {
          payload.username = String(data.get('username') || '').trim();
        }
        await post('api/users.php', payload);
        toast(editing ? 'The user was updated.' : 'The user was added.', { kind: 'ok' });
        load();
      } }],
    });
  }

  async function removeUser(user) {
    if (!(await confirm(`Delete ${user.username}?`, 'The account and its sessions are removed. This cannot be undone.', { label: 'Delete', danger: true }))) {
      return;
    }
    try {
      await post('api/users.php', { action: 'delete', id: user.id });
      toast('The user was deleted.', { kind: 'ok' });
      load();
    } catch (error) {
      failure(error);
    }
  }

  function roleForm(role) {
    const editing = Boolean(role);
    const have = new Set(role?.capabilities || []);
    const meta = Object.fromEntries((topic('meta')?.capabilities || []).map((c) => [c.name, c.description]));
    const group = (title, names) => h('fieldset', { class: 'checks-group' }, h('legend', { text: title }),
      names.map((name) => h('label', { class: 'check' },
        h('input', { type: 'checkbox', name: 'cap', value: name, checked: have.has(name) || null }),
        h('span', null, h('code', { text: name }), h('small', { text: WEB_LABELS[name] || meta[name] || '' })))));
    modal({
      title: editing ? `Edit role ${role.name}` : 'Add a role',
      wide: true,
      body: [
        field('Name', { name: 'name', required: true, maxlength: '32', value: role?.name || '', disabled: role?.builtin || null, autocomplete: 'off' }),
        h('p', { class: 'muted', text: 'A role can never do more than the bot itself allows.' }),
        group('Bot', session.capabilities.bot),
        group('Website', session.capabilities.web),
      ],
      actions: [{ label: 'Cancel' }, { label: editing ? 'Save' : 'Add role', primary: true, submit: true, run: async (data) => {
        await post('api/roles.php', {
          action: editing ? 'update' : 'create', id: role?.id, name: String(data.get('name') || role?.name || '').trim(),
          capabilities: data.getAll('cap'),
        });
        toast(editing ? 'The role was updated.' : 'The role was added.', { kind: 'ok' });
        load();
      } }],
    });
  }

  async function removeRole(role) {
    if (!(await confirm(`Delete the role ${role.name}?`, 'This cannot be undone.', { label: 'Delete', danger: true }))) {
      return;
    }
    try {
      await post('api/roles.php', { action: 'delete', id: role.id });
      toast('The role was deleted.', { kind: 'ok' });
      load();
    } catch (error) {
      failure(error);
    }
  }

  function renderUsers() {
    mount(actions, button('Add user', { class: 'btn btn-primary', onClick: () => userForm(null) }, 'plus'));
    mount(box.body, table([
      { label: 'User', render: (u) => h('span', null, h('strong', { text: u.username }), u.self ? h('span', { class: 'gap' }, pill('You', 'info')) : null) },
      { label: 'Role', render: (u) => u.role },
      { label: 'Logs in with', render: (u) => h('span', { class: 'pills' },
        u.has_password ? pill('Password') : null, u.totp ? pill('Two-factor', 'ok') : null,
        u.discord_id ? pill(u.discord_name ? `Discord: ${u.discord_name}` : 'Discord') : null) },
      { label: 'Last login', render: (u) => (u.last_login ? ago(u.last_login) : 'never') },
      { label: 'State', render: (u) => (u.disabled ? pill('Disabled', 'bad') : pill('Active', 'ok')) },
      { label: '', class: 'actions', render: (u) => {
        const locked = u.role === 'Owner' && !owner;
        return h('span', { class: 'row-actions' },
          button('Edit', { class: 'btn btn-sm', disabled: locked || null, onClick: () => userForm(u) }),
          u.self ? null : button('Delete', { class: 'btn btn-sm btn-danger', disabled: locked || null, onClick: () => removeUser(u) }));
      } },
    ], users));
  }

  function renderRoles() {
    mount(actions, owner ? button('Add role', { class: 'btn btn-primary', onClick: () => roleForm(null) }, 'plus') : null);
    mount(box.body, h('div', { class: 'role-list' }, roles.map((role) => h('article', { class: 'role' },
      h('header', null,
        h('div', null, h('h3', { text: role.name }), h('small', { text: `${role.users} user${role.users === 1 ? '' : 's'}${role.builtin ? ' · built-in' : ''}` })),
        owner && role.name !== 'Owner' ? h('span', { class: 'row-actions' },
          button('Edit', { class: 'btn btn-sm', onClick: () => roleForm(role) }),
          role.builtin ? null : button('Delete', { class: 'btn btn-sm btn-danger', onClick: () => removeRole(role) })) : null),
      h('div', { class: 'pills' }, role.capabilities.includes('*')
        ? pill('Everything', 'ok')
        : role.capabilities.length ? role.capabilities.map((c) => pill(c)) : h('span', { class: 'muted', text: 'No permissions' }))))));
  }

  async function renderDiscord() {
    mount(actions);
    mount(box.body, skeleton(4));
    let data;
    try {
      data = await get('api/settings.php');
    } catch (error) {
      failure(error);
      return;
    }
    if (!alive || tab !== 'discord') {
      return;
    }
    const o = data.oauth;
    const form = h('form', { class: 'form-grid' },
      h('p', { class: 'muted span-all' }, 'Optional. Create an application at discord.com/developers, add the redirect address below under OAuth2, then paste its client ID and secret here. Only users you added with a Discord ID, and the bot\'s owners, can log in this way.'),
      h('div', { class: 'span-all' }, facts([
        ['Redirect address', h('span', { class: 'inline' }, h('code', { text: o.redirect_uri }), copyButton(() => o.redirect_uri))],
        ['State', o.active ? pill('On', 'ok') : pill('Off')],
        o.can_request ? null : ['Problem', pill('This host blocks outgoing requests, so Discord login cannot work', 'bad')],
      ])),
      field('Client ID', { name: 'client_id', value: o.client_id, inputmode: 'numeric', maxlength: '25', autocomplete: 'off' }),
      field('Client secret', { name: 'client_secret', type: 'password', maxlength: '128', autocomplete: 'off', placeholder: o.has_secret ? 'Saved. Leave empty to keep it.' : '' }),
      h('label', { class: 'check span-all' }, h('input', { type: 'checkbox', name: 'enabled', checked: o.enabled || null }), h('span', { text: 'Show "Log in with Discord" on the login page' })),
      h('div', { class: 'span-all' }, button('Save', { class: 'btn btn-primary', type: 'submit' })));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = new FormData(form);
      try {
        await post('api/settings.php', {
          action: 'oauth', client_id: String(values.get('client_id') || '').trim(),
          client_secret: String(values.get('client_secret') || '').trim(), enabled: values.get('enabled') === 'on',
        });
        toast('Discord login settings saved.', { kind: 'ok' });
        renderDiscord();
      } catch (error) {
        failure(error);
      }
    });
    const s = data.system;
    const headers = [['', 'The address of the connection (no proxy)'], ['HTTP_CF_CONNECTING_IP', 'Cloudflare (CF-Connecting-IP)'],
      ['HTTP_X_FORWARDED_FOR', 'A reverse proxy (X-Forwarded-For)'], ['HTTP_X_REAL_IP', 'A reverse proxy (X-Real-IP)']];
    const site = h('form', { class: 'form-grid' },
      h('h3', { class: 'span-all form-title', text: 'Website' }),
      h('p', { class: 'muted span-all', text: 'How long the website holds a request open while it waits for news, and where it reads the visitor address used for rate limits and the session list.' }),
      field('Hold requests for (seconds)', { name: 'hold', type: 'number', min: '0', max: '50', value: String(s.hold_setting ?? s.hold) },
        `0 turns holding off and the dashboard asks every few seconds instead. In effect now: ${s.hold} s.`),
      field('Visitor address comes from', { name: 'ip_header', value: s.ip_header || '', options: headers.map(([value, label]) => ({ value, label })) },
        'Only pick a proxy header if the site really is behind that proxy, or visitors could fake their address.'),
      h('div', { class: 'span-all' }, button('Save', { class: 'btn btn-primary', type: 'submit' })));
    site.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = new FormData(site);
      try {
        await post('api/settings.php', { action: 'system', hold: Number(values.get('hold')), ip_header: String(values.get('ip_header') || '') });
        toast('Website settings saved.', { kind: 'ok' });
        renderDiscord();
      } catch (error) {
        failure(error);
      }
    });
    mount(box.body, form, h('hr', { class: 'sep' }), site);
  }

  function render() {
    if (tab === 'users') {
      renderUsers();
    } else if (tab === 'roles') {
      renderRoles();
    } else {
      renderDiscord();
    }
  }

  async function load() {
    try {
      const data = await get('api/users.php');
      users = data.users;
      roles = data.roles;
    } catch (error) {
      failure(error);
      return;
    }
    if (alive) {
      render();
    }
  }

  mount(box.body, skeleton(5));
  load();
  return () => { alive = false; };
}
