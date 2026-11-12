import { get, run } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { stamp } from '../core/format.js';
import { can, session } from '../core/store.js';
import { card, empty, pageHead, pill, segmented, skeleton, table } from '../ui/parts.js';

const OUTCOMES = { ok: 'ok', denied: 'bad', refused: 'bad', failed: 'bad', expired: 'warn', timeout: 'warn', unknown: 'warn' };

function detail(value) {
  if (value == null || value === '') {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  return Object.entries(value).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ');
}

export default function audit(page) {
  let source = 'web';
  let entries = [];
  let more = false;
  let alive = true;
  const box = card(null);
  const mode = segmented([{ value: 'web', label: 'Website' }, { value: 'bot', label: 'Bot' }], source, (next) => {
    source = next;
    entries = [];
    load();
  }, 'Log source');
  page.append(pageHead('Audit log', 'Who did what. The website and the bot keep separate logs.', mode.el), box.el);

  function render() {
    if (source === 'web') {
      mount(box.body, entries.length ? table([
        { label: 'When', render: (e) => stamp(e.at) },
        { label: 'User', render: (e) => e.user || h('span', { class: 'muted', text: 'system' }) },
        { label: 'Action', render: (e) => h('code', { text: e.action }) },
        { label: 'Details', class: 'wrap', render: (e) => detail(e.detail) },
        { label: 'Address', render: (e) => h('span', { class: 'muted', text: e.ip || '' }) },
      ], entries) : h('p', { class: 'muted', text: 'Nothing has been logged yet.' }),
      more ? h('div', { class: 'card-foot' }, button('Load older entries', { onClick: () => load(entries[entries.length - 1].id) })) : null);
      return;
    }
    mount(box.body, entries.length ? table([
      { label: 'When', render: (e) => stamp(Date.parse(e.at) / 1000) },
      { label: 'User', render: (e) => e.user_name || h('span', { class: 'muted', text: 'unknown' }) },
      { label: 'Action', render: (e) => h('code', { text: e.action }) },
      { label: 'Needs', render: (e) => (e.capability && e.capability !== '-' ? h('code', { text: e.capability }) : '') },
      { label: 'Outcome', render: (e) => pill(e.outcome, OUTCOMES[e.outcome] || '') },
      { label: 'Details', class: 'wrap', render: (e) => e.detail || '' },
    ], entries) : h('p', { class: 'muted', text: 'The bot has not run or refused anything yet.' }));
  }

  async function load(before = 0) {
    if (!before) {
      mount(box.body, skeleton(6));
    }
    try {
      if (source === 'web') {
        const data = await get('api/audit.php', { limit: 50, before: before || null });
        entries = before ? entries.concat(data.entries) : data.entries;
        more = data.more;
      } else {
        if (!session.bot.paired) {
          throw new Error('No bot is paired.');
        }
        const data = await run('system.audit', { limit: 200 });
        entries = data.entries;
        more = false;
      }
    } catch (error) {
      if (alive) {
        mount(box.body, empty('alert', 'The log could not be loaded', error.message));
      }
      return;
    }
    if (alive) {
      render();
    }
  }

  if (!can('view')) {
    mode.button('bot').disabled = true;
  }
  load();
  return () => { alive = false; };
}
