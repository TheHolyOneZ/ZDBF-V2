import { get, post } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { ago, stamp } from '../core/format.js';
import { on, session, subscribe, topic } from '../core/store.js';
import { confirm } from '../ui/modal.js';
import { card, copyButton, facts, pageHead, pill, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

export default function link(page) {
  const stops = [];
  const status = card('Connection');
  const pair = card('Pair a bot', { sub: 'The bot connects out to this website. Nothing has to be opened on the bot host.' });
  const caps = card('What the bot allows', {
    sub: 'Decided on the bot with /dashboard capabilities or in config.toml. It cannot be changed from this website.',
    class: 'span-all',
  });
  page.append(pageHead('Bot link', 'How this website and your bot are connected.'),
    h('div', { class: 'grid-2' }, status.el, pair.el, caps.el));
  status.body.appendChild(skeleton(4));
  let info = null;
  let code = null;
  let timer = 0;

  async function load() {
    try {
      info = await get('api/link.php');
    } catch (error) {
      failure(error);
      return;
    }
    renderStatus();
    renderPair();
  }

  function renderStatus() {
    if (!info) {
      return;
    }
    const bot = session.bot;
    const meta = topic('meta');
    const state = !bot.paired ? pill('Not paired', '') : bot.online ? pill('Online', 'ok') : pill('Offline', 'bad');
    const unpair = button('Unpair', { class: 'btn btn-danger btn-sm', onClick: async () => {
      const yes = await confirm('Unpair the bot?', 'This website forgets the bot and its secret. Run /dashboard unpair on the bot too, or pair it again.',
        { label: 'Unpair', danger: true });
      if (!yes) {
        return;
      }
      try {
        await post('api/link.php', { action: 'unpair' });
        toast('The bot was unpaired.', { kind: 'ok' });
        session.bot = { paired: false, online: false, seen_at: null };
        await load();
      } catch (error) {
        failure(error);
      }
    } });
    mount(status.body, facts([
      ['State', state],
      ['Bot', bot.paired ? (meta?.bot?.tag || meta?.bot?.name || `ID ${info.bot.bot_id}`) : 'None'],
      bot.paired ? ['Bot ID', h('code', { text: info.bot.bot_id || '-' })] : null,
      bot.paired ? ['ZDBF version', meta?.version || info.bot.version || '-'] : null,
      bot.paired ? ['Paired', stamp(info.bot.paired_at)] : null,
      bot.paired ? ['Last contact', ago(bot.seen_at)] : null,
      ['Address', h('code', { text: info.url })],
      ['Transport', info.https ? 'HTTPS' : pill('Plain HTTP, local testing only', 'warn')],
    ]), bot.paired ? h('div', { class: 'card-foot' }, unpair) : null);
  }

  function renderPair() {
    if (!info) {
      return;
    }
    clearInterval(timer);
    const create = button(code ? 'Create another code' : 'Create a pairing code', { class: `btn ${code ? '' : 'btn-primary'}`.trim(), onClick: async () => {
      try {
        code = await post('api/link.php', { action: 'code' });
        renderPair();
      } catch (error) {
        failure(error);
      }
    } });
    const steps = h('ol', { class: 'steps' },
      h('li', null, 'On the bot, set ', h('code', { text: 'dashboard = true' }), ' under ', h('code', { text: '[modules]' }), ' in config.toml and restart it.'),
      h('li', null, 'Create a pairing code here. It is valid for 10 minutes and works once.'),
      h('li', null, 'Run the command below in Discord as the bot owner.'));
    const parts = [steps];
    if (session.bot.paired) {
      parts.push(h('p', { class: 'note', dataset: { kind: 'warn' }, text: 'A bot is already paired. Pairing again replaces it.' }));
    }
    if (code) {
      const command = `/dashboard pair url:${code.url} code:${code.code}`;
      const left = h('span', { class: 'muted' });
      const tick = () => {
        const seconds = Math.max(0, code.expires_at - Math.floor(Date.now() / 1000));
        left.textContent = seconds ? `Valid for ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : 'Expired. Create another code.';
      };
      tick();
      timer = setInterval(tick, 1000);
      parts.push(h('div', { class: 'codebox' }, h('code', { text: command }), copyButton(() => command)), left);
    } else if (info.pairing_expires) {
      parts.push(h('p', { class: 'muted', text: 'A code is waiting to be used. Codes are shown once; create another if you lost it.' }));
    }
    parts.push(h('div', { class: 'card-foot' }, create));
    mount(pair.body, parts);
  }

  function renderCaps(meta) {
    if (!meta?.capabilities) {
      mount(caps.body, h('p', { class: 'muted', text: 'The bot reports its capabilities after it is paired.' }));
      return;
    }
    mount(caps.body, table([
      { label: 'Capability', render: (c) => h('code', { text: c.name }) },
      { label: 'Covers', render: (c) => c.description },
      { label: 'State', render: (c) => {
        if (!c.enabled) {
          return pill('Off', '');
        }
        if (!c.active) {
          return pill('Locked', 'warn');
        }
        return c.approval ? pill('On, needs approval', 'info') : pill('On', 'ok');
      } },
    ], meta.capabilities));
  }

  stops.push(subscribe('meta', (meta) => { renderCaps(meta); renderStatus(); }));
  if (!topic('meta')) {
    renderCaps(null);
  }
  stops.push(on('bot', (bot) => {
    if (code && bot.paired && bot.online) {
      code = null;
      toast('The bot is paired and connected.', { kind: 'ok' });
    }
    load();
  }));
  stops.push(() => clearInterval(timer));
  load();
  return () => stops.forEach((stop) => stop());
}
