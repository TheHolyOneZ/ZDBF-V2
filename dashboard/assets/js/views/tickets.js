import { run } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { ago, shortStamp, stamp } from '../core/format.js';
import { can } from '../core/store.js';
import { confirm, modal } from '../ui/modal.js';
import { empty, pill, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';
import { blockedReason } from './servers.js';

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    return false;
  }
  return true;
}

export default function ticketsView(page) {
  let alive = true;
  let servers = null;
  let guildId = recall('zdbf-auto-guild') || '';
  let data = null;
  const picker = h('select', { class: 'auto-guild', 'aria-label': 'Server' });
  const body = h('div', { class: 'auto-body' });
  page.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Tickets' }),
      h('p', { text: 'Open support tickets and the transcripts of closed ones.' }))),
    h('div', { class: 'market-bar' }, h('label', { class: 'auto-pick' }, h('span', { class: 'muted', text: 'Server' }), picker)),
    body);

  picker.addEventListener('change', () => {
    guildId = picker.value;
    remember('zdbf-auto-guild', guildId);
    load();
  });

  async function show(t) {
    const box = h('div', { class: 'tk-transcript' }, skeleton(6));
    let text = '';
    const download = button('Download as text', { class: 'btn btn-sm', disabled: true, onClick: () => {
      const link = h('a', { download: `${t.channel_name}-transcript.txt`, href: URL.createObjectURL(new Blob([text], { type: 'text/plain' })) });
      document.body.appendChild(link);
      link.click();
      setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    } }, 'download');
    modal({ title: `#${t.channel_name}`, wide: true, body: [
      h('p', { class: 'modal-text', text: `Opened by ${t.owner.name || t.owner.id || 'unknown'} ${stamp(t.opened_at)}, closed by ${t.closed_by} ${stamp(t.closed_at)}.` }),
      h('div', { class: 'bk-actions' }, download), box] });
    try {
      const result = await run('tickets.transcript', { guild_id: guildId, id: t.id });
      text = result.text;
      download.disabled = false;
      const messages = result.transcript.messages;
      mount(box, messages.length ? messages.map((m) => h('div', { class: 'tk-msg' },
        h('div', { class: 'tk-meta' }, h('strong', { text: m.author.name }), m.author.bot ? pill('Bot') : null, h('time', { text: shortStamp(m.at) })),
        m.content ? h('p', { class: 'tk-text', text: m.content }) : null,
        m.embeds.filter(Boolean).map((e) => h('p', { class: 'tk-card', text: e })),
        m.attachments.map((a) => h('a', { class: 'tk-file', href: a.url, target: '_blank', rel: 'noopener noreferrer', text: a.name }))))
        : h('p', { class: 'muted', text: 'The ticket had no messages.' }));
    } catch (error) {
      mount(box, h('p', { class: 'note', dataset: { kind: 'bad' }, text: error.message }));
    }
  }

  function render() {
    if (!data) {
      mount(body, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(5))));
      return;
    }
    const reason = blockedReason('automations', 'close tickets');
    const canRead = can('chat.read');
    mount(body,
      !data.automations.length ? h('p', { class: 'note', dataset: { kind: 'info' }, text: 'This server has no ticket automation. Create one under Automations with the "Support tickets" type.' }) : null,
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: `Open tickets (${data.open.length})` }))),
        h('div', { class: 'card-body' }, data.open.length ? table([
          { label: 'Ticket', render: (t) => h('a', { href: `#/chat/${t.channel_id}`, text: `#${t.name}` }) },
          { label: 'Opened by', render: (t) => t.owner.name || t.owner.id },
          { label: 'Opened', render: (t) => ago(t.opened_at) },
          { label: 'Last message', render: (t) => (t.last_activity ? ago(t.last_activity) : '-') },
          { label: '', class: 'num', render: (t) => button('Close', { class: 'btn btn-sm', disabled: reason ? true : null, title: reason || null, onClick: async () => {
            if (!await confirm('Close ticket', `#${t.name} is closed${data.automations.find((a) => a.id === t.automation)?.transcripts ? ', its transcript saved,' : ''} and the channel deleted.`, { label: 'Close', danger: true })) {
              return;
            }
            try {
              await run('tickets.close', { guild_id: guildId, channel_id: t.channel_id });
              toast(`#${t.name} is closing.`, { kind: 'ok' });
              setTimeout(load, 6000);
            } catch (error) {
              failure(error);
            }
          } }) },
        ], data.open) : h('p', { class: 'muted', text: 'No ticket is open.' }))),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: `Transcripts (${data.transcripts.length})` }),
          h('p', { text: canRead ? 'Saved when a ticket closes. The newest 500 per server are kept.' : 'Reading transcripts needs the chat.read permission.' }))),
        h('div', { class: 'card-body' }, data.transcripts.length ? table([
          { label: 'Ticket', render: (t) => `#${t.channel_name}` },
          { label: 'Opened by', render: (t) => t.owner.name || t.owner.id || '-' },
          { label: 'Closed', render: (t) => shortStamp(t.closed_at) },
          { label: 'Closed by', render: (t) => t.closed_by },
          { label: 'Messages', class: 'num', render: (t) => String(t.messages) },
          { label: '', class: 'num', render: (t) => h('div', { class: 'row-actions' },
            button('Read', { class: 'btn btn-sm', disabled: canRead ? null : true, onClick: () => show(t) }),
            button('', { class: 'btn btn-sm', 'aria-label': 'Delete transcript', title: 'Delete', disabled: reason ? true : null, onClick: async () => {
              if (await confirm('Delete transcript', `The transcript of #${t.channel_name} is removed for good.`, { label: 'Delete', danger: true })) {
                try {
                  await run('tickets.delete', { guild_id: guildId, id: t.id });
                  load();
                } catch (error) {
                  failure(error);
                }
              }
            } }, 'trash')) },
        ], data.transcripts) : empty('list', 'No transcripts yet', 'They appear here when a ticket is closed.'))));
  }

  async function load() {
    data = null;
    render();
    try {
      const result = await run('tickets.list', { guild_id: guildId });
      if (alive) {
        data = result;
        render();
      }
    } catch (error) {
      if (alive) {
        mount(body, h('section', { class: 'card' }, empty('alert', 'Tickets could not be loaded', error.message)));
      }
    }
  }

  async function start() {
    render();
    try {
      servers = (await run('servers.list')).servers;
    } catch (error) {
      mount(body, h('section', { class: 'card' }, empty('alert', 'Tickets could not be loaded', error.message)));
      return;
    }
    if (!servers.some((s) => s.id === guildId)) {
      guildId = servers[0]?.id || '';
    }
    mount(picker, servers.map((s) => h('option', { value: s.id, text: s.name, selected: s.id === guildId || null })));
    if (guildId) {
      load();
    } else {
      mount(body, h('section', { class: 'card' }, empty('server', 'No servers', 'Invite the bot to a server first.')));
    }
  }

  start();
  return () => { alive = false; };
}
