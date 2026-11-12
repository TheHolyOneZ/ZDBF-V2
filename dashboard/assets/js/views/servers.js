import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { bytes, compact, num, shortStamp, stamp } from '../core/format.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session } from '../core/store.js';
import { confirm, modal } from '../ui/modal.js';
import { empty, facts, pill, segmented, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

export function blockedReason(capability, what) {
  if (!can(capability)) {
    return `Your role cannot ${what}.`;
  }
  if (!botAllows(capability)) {
    return `This is switched off on the bot. The bot owner can enable "${capability}" with /dashboard capabilities.`;
  }
  if (!session.bot.online) {
    return 'The bot is offline.';
  }
  return '';
}

export function approvalToast(text) {
  const note = toast(text, { timeout: 0 });
  return {
    note,
    onStatus: (state, step) => {
      if (state === 'awaiting_approval') {
        note.update('Waiting for the bot owner to approve in Discord');
      } else if (step) {
        note.update(`${text}: ${step}`);
      }
    },
  };
}

function iconOf(server, size = 'md') {
  const node = h('span', { class: `srv-icon srv-${size}`, 'aria-hidden': 'true' }, server.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 3));
  if (server.icon) {
    const img = h('img', { alt: '', src: server.icon, referrerpolicy: 'no-referrer' });
    img.addEventListener('load', () => mount(node, img));
  }
  return node;
}

function isoTime(value) {
  return value ? Date.parse(value) / 1000 : null;
}

export default function serversView(page, context) {
  let alive = true;
  const stops = [];
  let servers = null;
  let selected = context.params[0] || null;
  let tab = context.params[1] || 'overview';
  let detail = null;
  let filter = '';

  const content = h('div', { class: 'srv-content' });
  page.append(content);

  function renderList() {
    const q = filter.trim().toLowerCase();
    const shown = (servers || []).filter((s) => !q || s.name.toLowerCase().includes(q) || s.id.includes(q));
    const search = h('input', { type: 'search', class: 'market-search', placeholder: 'Find a server', value: filter, 'aria-label': 'Find a server' });
    search.addEventListener('input', () => {
      filter = search.value;
      const grid = content.querySelector('.srv-grid');
      const words = filter.trim().toLowerCase();
      mount(grid, servers.filter((s) => !words || s.name.toLowerCase().includes(words) || s.id.includes(words)).map(card));
    });
    const card = (s) => h('button', { type: 'button', class: 'srv-card', onClick: () => open(s.id) },
      iconOf(s), h('div', { class: 'srv-card-text' }, h('strong', { text: s.name }),
        h('small', { text: `${num(s.members)} members · shard ${s.shard ?? 0}` })), icon('right'));
    mount(content,
      h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Servers' }),
        h('p', { text: servers ? `The bot is in ${servers.length} server${servers.length === 1 ? '' : 's'}.` : 'The servers the bot is in.' }))),
      servers ? h('div', { class: 'market-bar' }, search) : null,
      servers ? h('div', { class: 'srv-grid' }, shown.length ? shown.map(card) : h('p', { class: 'muted', text: 'No server matches.' }))
        : h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6))));
  }

  function open(id) {
    selected = id;
    tab = 'overview';
    replace(`servers/${id}`);
    loadDetail();
  }

  function head() {
    const tabs = segmented([
      { value: 'overview', label: 'Overview' }, { value: 'settings', label: 'Settings' },
      { value: 'backups', label: 'Backups' },
    ], tab, (value) => {
      tab = value;
      replace(`servers/${selected}/${value}`);
      renderDetail();
    }, 'Server section');
    return h('header', { class: 'page-head srv-head' },
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'All servers', onClick: () => { selected = null; detail = null; replace('servers'); renderList(); } }, icon('left')),
      iconOf(detail, 'lg'),
      h('div', { class: 'page-title' }, h('h1', { text: detail.name }), h('p', { text: `${num(detail.members)} members · ID ${detail.id}` })),
      h('div', { class: 'page-actions' }, tabs.el));
  }

  function overview() {
    const reason = blockedReason('guilds.leave', 'make the bot leave servers');
    const p = detail.bot_permissions;
    return [
      h('section', { class: 'card' }, h('div', { class: 'card-body' }, facts([
        ['Owner', detail.owner.name ? `${detail.owner.name} (${detail.owner.id})` : detail.owner.id],
        ['Created', stamp(detail.created_at)],
        ['Bot joined', stamp(detail.joined_at)],
        ['Shard', String(detail.shard ?? 0)],
        ['Channels', String(detail.channels.length)],
        ['Roles', String(detail.roles.length)],
        ['Prefix', h('code', { text: detail.prefix })],
        ['Bot permissions', h('span', { class: 'pills' }, p.administrator ? pill('Administrator', 'ok')
          : [p.manage_guild ? pill('Manage server', 'ok') : pill('No Manage server', 'warn'),
            p.manage_roles ? pill('Manage roles', 'ok') : pill('No Manage roles', 'warn'),
            p.manage_channels ? pill('Manage channels', 'ok') : pill('No Manage channels', 'warn')])],
        detail.description ? ['Description', detail.description] : null,
      ]))),
      h('section', { class: 'card danger-zone' }, h('div', { class: 'card-body' },
        h('div', { class: 'danger-row' },
          h('div', null, h('strong', { text: 'Leave this server' }), h('p', { class: 'muted', text: 'The bot leaves at once. It can only come back with a new invite.' })),
          button('Leave server', { class: 'btn btn-danger', disabled: reason ? true : null, title: reason || null, onClick: () => leave() }, 'logout')),
        reason && can('guilds.leave') ? h('p', { class: 'muted', text: reason }) : null)),
    ];
  }

  async function leave() {
    const result = await modal({
      title: `Leave ${detail.name}`,
      body: [h('p', { class: 'modal-text', text: 'Type the server name to confirm.' }),
        h('label', { class: 'field' }, h('span', { text: 'Server name' }), h('input', { name: 'confirm', required: true, autocomplete: 'off' }))],
      actions: [{ label: 'Cancel', value: null }, {
        label: 'Leave', danger: true, submit: true,
        run: async (form) => {
          const t = approvalToast(`Leaving ${detail.name}`);
          try {
            return await run('servers.leave', { guild_id: detail.id, confirm: String(form.get('confirm')) }, { onStatus: t.onStatus });
          } finally {
            t.note.close();
          }
        },
      }],
    }).done;
    if (result) {
      toast(`The bot left ${detail.name}.`, { kind: 'ok' });
      selected = null;
      detail = null;
      replace('servers');
      loadList();
    }
  }

  function settings() {
    const reason = blockedReason('settings', 'change server settings');
    const prefix = h('input', { type: 'text', maxlength: '10', value: detail.custom_prefix ? detail.prefix : '', placeholder: `Default: ${detail.default_prefix}`, disabled: reason ? true : null });
    const mention = h('input', { type: 'checkbox', checked: detail.mention_prefix || null, disabled: reason ? true : null });
    const save = button('Save', { class: 'btn btn-primary btn-sm', disabled: reason ? true : null }, 'check');
    save.addEventListener('click', async () => {
      try {
        await run('servers.prefix', { guild_id: detail.id, prefix: prefix.value.trim(), mention_prefix: mention.checked });
        toast('Prefix saved.', { kind: 'ok' });
        loadDetail();
      } catch (error) {
        failure(error);
      }
    });
    const roleName = (id) => detail.roles.find((r) => r.id === id)?.name || id;
    const rows = Object.entries(detail.restrictions);
    const cmdSelect = h('select', { 'aria-label': 'Command', disabled: reason ? true : null }, detail.commands.map((c) => h('option', { value: c, text: c })));
    const roleSelect = h('select', { 'aria-label': 'Role', disabled: reason ? true : null }, detail.roles.map((r) => h('option', { value: r.id, text: r.name })));
    const add = button('Require role', { class: 'btn btn-sm', disabled: reason ? true : null }, 'plus');
    const restrict = async (args, text) => {
      try {
        await run('servers.restrict', { guild_id: detail.id, ...args });
        toast(text, { kind: 'ok' });
        loadDetail();
      } catch (error) {
        failure(error);
      }
    };
    add.addEventListener('click', () => restrict({ command: cmdSelect.value, role_id: roleSelect.value }, 'Restriction added.'));
    const stored = Object.entries(detail.settings);
    return [
      reason ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null,
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Prefix' }), h('p', { text: 'Slash commands always work.' }))),
        h('div', { class: 'card-body srv-prefix' },
          h('label', { class: 'field' }, h('span', { text: 'Command prefix' }), prefix, h('small', { text: 'Up to 10 characters, no spaces. Empty uses the default.' })),
          h('label', { class: 'check' }, mention, h('span', { text: 'Allow @bot as a prefix' })), save)),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Command restrictions' }),
          h('p', { text: 'A restricted command only runs for members with one of its roles.' }))),
        h('div', { class: 'card-body' },
          h('div', { class: 'srv-restrict' }, cmdSelect, roleSelect, add),
          rows.length ? table([
            { label: 'Command', render: ([name]) => h('code', { text: name }) },
            { label: 'Roles', render: ([name, ids]) => h('span', { class: 'pills' }, ids.map((id) => h('span', { class: 'pill' }, roleName(id),
              reason ? null : h('button', { type: 'button', class: 'pill-x', 'aria-label': `Remove ${roleName(id)}`, onClick: () => restrict({ command: name, role_id: id, remove: true }, 'Role removed.') }, icon('x'))))) },
            { label: '', class: 'num', render: ([name]) => reason ? null : button('Clear', { class: 'btn btn-sm', onClick: () => restrict({ command: name, clear: true }, 'Restrictions cleared.') }) },
          ], rows) : h('p', { class: 'muted', text: 'No command is restricted in this server.' }))),
      stored.length ? h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Stored settings' }))),
        h('div', { class: 'card-body' }, table([
          { label: 'Key', render: ([k]) => h('code', { text: k }) },
          { label: 'Value', render: ([, v]) => h('span', { class: 'mono', text: typeof v === 'string' ? v : JSON.stringify(v) }) },
        ], stored))) : null,
    ];
  }

  function backups() {
    const box = h('div', { class: 'srv-backups' }, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(4))));
    loadBackups(box);
    return box;
  }

  async function loadBackups(box) {
    let data;
    try {
      data = await run('backups.list', { guild_id: detail.id });
    } catch (error) {
      mount(box, h('section', { class: 'card' }, empty('alert', 'Backups could not be loaded', error.message)));
      return;
    }
    const reason = blockedReason('backups', 'create or change backups');
    const create = button('Back up now', { class: 'btn btn-primary btn-sm', disabled: reason || data.busy ? true : null, title: reason || null }, 'plus');
    create.addEventListener('click', () => createBackup(data, box));
    mount(box,
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Backups' }),
          h('p', { text: `${data.backups.length} of ${data.max} kept · ${data.retention_days ? `older than ${data.retention_days} days are removed unless pinned` : 'kept until deleted'}` })),
        h('div', { class: 'card-tools' }, create)),
        h('div', { class: 'card-body' }, data.backups.length ? table([
          { label: 'Backup', render: (b) => h('div', { class: 'bk-name' }, h('strong', { text: b.label }), b.pinned ? pill('Pinned', 'info') : null, b.automatic ? pill('Automatic') : null) },
          { label: 'Made', render: (b) => shortStamp(isoTime(b.created_at)) },
          { label: 'Contents', render: (b) => `${b.counts.roles ?? 0} roles · ${(b.counts.channels ?? 0) + (b.counts.categories ?? 0)} channels` },
          { label: 'Size', class: 'num', render: (b) => bytes(b.size) },
          { label: '', class: 'num', render: (b) => h('div', { class: 'row-actions' },
            button('Open', { class: 'btn btn-sm', onClick: () => openBackup(b, data, box) })) },
        ], data.backups) : empty('shield', 'No backups yet', 'A backup keeps roles, channels, permissions, emojis and settings of this server.'))));
  }

  async function createBackup(data, box) {
    const parts = Object.entries(data.components);
    const result = await modal({
      title: 'Back up this server',
      body: [
        h('label', { class: 'field' }, h('span', { text: 'Label' }), h('input', { name: 'label', maxlength: '100', placeholder: 'Dashboard backup' })),
        h('fieldset', { class: 'checks-group' }, h('legend', { text: 'Include' }),
          parts.map(([key, label]) => h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'c', value: key, checked: true }), h('span', { text: label })))),
      ],
      actions: [{ label: 'Cancel', value: null }, {
        label: 'Back up', primary: true, submit: true,
        run: (form) => run('backups.create', { guild_id: detail.id, label: String(form.get('label') || ''), components: form.getAll('c') }, { timeout: 6 * 60 * 1000 }),
      }],
    }).done;
    if (result) {
      toast('Backup created.', { kind: 'ok' });
      loadBackups(box);
    }
  }

  function reportView(report) {
    return h('div', { class: 'bk-report' },
      h('div', { class: 'ext-stats' },
        [['Created', report.created], ['Updated', report.updated], ['Skipped', report.skipped], ['Failed', report.failed]]
          .map(([label, value]) => h('div', { dataset: { kind: label === 'Failed' && value ? 'bad' : '' } }, h('strong', { text: String(value) }), h('span', { text: label })))),
      report.planned.length ? h('details', { class: 'market-changelog', open: report.dry_run || null }, h('summary', { text: `${report.planned.length} planned change${report.planned.length === 1 ? '' : 's'}` }),
        h('pre', { text: report.planned.join('\n') })) : null,
      report.limited ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: `Discord rate limited ${report.limited} change${report.limited === 1 ? '' : 's'}, so ${report.limited === 1 ? 'it was' : 'they were'} skipped instead of waiting. Discord allows two name or topic changes per channel in ten minutes. Run the restore again later for the rest.` }) : null,
      report.errors.length ? h('details', { class: 'ext-error', open: true }, h('summary', { text: `${report.errors.length} problem${report.errors.length === 1 ? '' : 's'}` }),
        h('pre', { text: report.errors.join('\n') })) : null);
  }

  async function openBackup(b, data, box) {
    const reason = blockedReason('backups', 'change backups');
    const restoreReason = blockedReason('backups.restore', 'restore backups');
    const out = h('div', { class: 'bk-out' });
    const comps = h('fieldset', { class: 'checks-group' }, h('legend', { text: 'Parts to restore' }),
      b.components.map((key) => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: key, checked: key !== 'member_roles' && key !== 'bot_settings' ? true : null }),
        h('span', { text: data.components[key] || key }))));
    const update = h('input', { type: 'checkbox' });
    const sync = h('input', { type: 'checkbox' });
    const options = () => ({
      guild_id: detail.id, backup_id: b.id, update_existing: update.checked, sync_member_roles: sync.checked,
      components: [...comps.querySelectorAll('input:checked')].map((i) => i.value),
    });
    const busy = async (btn, work) => {
      btn.disabled = true;
      mount(out, skeleton(4));
      try {
        await work();
      } catch (error) {
        mount(out, h('p', { class: 'note', dataset: { kind: 'bad' }, text: error.message }));
      } finally {
        btn.disabled = false;
      }
    };
    const compareBtn = button('Compare with the server', { class: 'btn btn-sm' }, 'diff');
    compareBtn.addEventListener('click', () => busy(compareBtn, async () => {
      const result = await run('backups.diff', { guild_id: detail.id, backup_id: b.id }, { timeout: 180000 });
      const sections = Object.entries(result.sections).filter(([, c]) => c.added.length + c.removed.length + c.changed.length);
      mount(out, sections.length ? sections.map(([name, c]) => h('div', { class: 'bk-diff' }, h('h4', { text: name[0].toUpperCase() + name.slice(1) }),
        h('ul', null, c.added.map((n) => h('li', { dataset: { kind: 'ok' }, text: `added since: ${n}` })),
          c.removed.map((n) => h('li', { dataset: { kind: 'bad' }, text: `gone since: ${n}` })),
          c.changed.map((n) => h('li', { dataset: { kind: 'warn' }, text: `changed: ${n}` })))))
        : h('p', { class: 'note', dataset: { kind: 'ok' }, text: 'The server matches this backup.' }));
    }));
    const previewBtn = button('Preview a restore', { class: 'btn btn-sm' }, 'search');
    previewBtn.addEventListener('click', () => busy(previewBtn, async () => {
      mount(out, reportView(await run('backups.preview', options(), { timeout: 6 * 60 * 1000 })));
    }));
    const restoreBtn = button('Restore', { class: 'btn btn-danger btn-sm', disabled: restoreReason ? true : null, title: restoreReason || null }, 'undo');
    restoreBtn.addEventListener('click', async () => {
      const args = options();
      if (!args.components.length) {
        toast('Pick at least one part.', { kind: 'warn' });
        return;
      }
      if (!await confirm('Restore this backup', `This changes ${detail.name} to match "${b.label}" for: ${args.components.map((c) => data.components[c] || c).join(', ')}. Run a preview first if you are not sure.`, { label: 'Restore', danger: true })) {
        return;
      }
      busy(restoreBtn, async () => {
        const t = approvalToast('Restoring');
        try {
          mount(out, reportView(await run('backups.restore', args, { timeout: 31 * 60 * 1000, onStatus: t.onStatus })));
          toast('Restore finished.', { kind: 'ok' });
        } finally {
          t.note.close();
        }
      });
    });
    const pinBtn = button(b.pinned ? 'Unpin' : 'Pin', { class: 'btn btn-sm', disabled: reason ? true : null }, 'pin');
    pinBtn.addEventListener('click', async () => {
      try {
        await run('backups.update', { guild_id: detail.id, backup_id: b.id, pinned: !b.pinned });
        dialog.close();
        loadBackups(box);
      } catch (error) {
        failure(error);
      }
    });
    const deleteBtn = button('Delete', { class: 'btn btn-sm', disabled: reason || b.pinned ? true : null, title: b.pinned ? 'Unpin it first' : null }, 'trash');
    deleteBtn.addEventListener('click', async () => {
      if (!await confirm('Delete backup', `"${b.label}" is removed for good.`, { label: 'Delete', danger: true })) {
        return;
      }
      try {
        await run('backups.delete', { guild_id: detail.id, backup_id: b.id });
        dialog.close();
        loadBackups(box);
      } catch (error) {
        failure(error);
      }
    });
    const dialog = modal({
      title: b.label,
      wide: true,
      body: [
        facts([['Made', stamp(isoTime(b.created_at))], ['Size', bytes(b.size)], ['Version', b.version || '-'],
          ['Contents', Object.entries(b.counts).map(([k, v]) => `${compact(v)} ${k.replace(/_/g, ' ')}`).join(', ')]]),
        h('div', { class: 'bk-actions' }, compareBtn, previewBtn, pinBtn, deleteBtn),
        h('details', { class: 'bk-restore' }, h('summary', { text: 'Restore' }),
          comps,
          h('label', { class: 'check' }, update, h('span', null, 'Update existing items', h('small', { text: 'Roles and channels that still exist get the backed-up settings again.' }))),
          h('label', { class: 'check' }, sync, h('span', null, 'Sync member roles', h('small', { text: 'Members lose roles that were not in the backup. Needs "Member roles".' }))),
          h('div', { class: 'bk-actions' }, restoreBtn), restoreReason && can('backups.restore') ? h('p', { class: 'muted', text: restoreReason }) : null),
        out,
      ],
    });
  }

  function renderDetail() {
    if (!detail) {
      mount(content, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6))));
      return;
    }
    mount(content, head(), h('div', { class: 'srv-body' }, tab === 'settings' ? settings() : tab === 'backups' ? backups() : overview()));
  }

  async function loadDetail() {
    detail = null;
    renderDetail();
    try {
      const data = await run('servers.detail', { guild_id: selected });
      if (alive && data.id === selected) {
        detail = data;
        renderDetail();
      }
    } catch (error) {
      if (alive) {
        mount(content, h('section', { class: 'card' }, empty('alert', 'The server could not be loaded', error.message,
          button('All servers', { class: 'btn', onClick: () => { selected = null; replace('servers'); loadList(); } }, 'left'))));
      }
    }
  }

  async function loadList() {
    renderList();
    try {
      servers = (await run('servers.list')).servers;
    } catch (error) {
      if (alive) {
        mount(content, h('section', { class: 'card' }, empty('alert', 'Servers could not be loaded', error.message)));
      }
      return;
    }
    if (alive && !selected) {
      renderList();
    }
  }

  stops.push(on('bot', () => { if (detail) { renderDetail(); } }));
  if (selected) {
    loadDetail();
  } else {
    loadList();
  }

  return {
    update(params) {
      if (params[0] && params[0] !== selected) {
        selected = params[0];
        tab = params[1] || 'overview';
        loadDetail();
      } else if (!params[0] && selected) {
        selected = null;
        detail = null;
        loadList();
      }
    },
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}

