import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { ago, duration, fixed, num, shortStamp } from '../core/format.js';
import { replace } from '../core/router.js';
import { can } from '../core/store.js';
import { confirm } from '../ui/modal.js';
import { empty, facts, pill, segmented, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';
import { approvalToast, blockedReason } from './servers.js';

const TABS = [
  { value: 'health', label: 'Health' }, { value: 'shards', label: 'Shards' }, { value: 'hooks', label: 'Event hooks' },
  { value: 'plugins', label: 'Plugins' }, { value: 'alerts', label: 'Alerts' }, { value: 'status', label: 'Bot status' },
];
const STATE = { healthy: ['Healthy', 'ok'], degraded: ['Degraded', 'warn'], critical: ['Critical', 'bad'] };

function spark(values, label) {
  const clean = values.filter((v) => typeof v === 'number');
  if (clean.length < 2) {
    return null;
  }
  const max = Math.max(...clean, 1);
  const w = 160;
  const hgt = 32;
  const step = w / (clean.length - 1);
  const points = clean.map((v, i) => `${(i * step).toFixed(1)},${(hgt - (v / max) * (hgt - 2) - 1).toFixed(1)}`).join(' ');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hgt}`);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', points);
  svg.appendChild(line);
  return svg;
}

export default function systemView(page, context) {
  let alive = true;
  const stops = [];
  let tab = TABS.some((t) => t.value === context.params[0]) ? context.params[0] : 'health';
  const body = h('div', { class: 'sys-body' });
  const tabs = segmented(TABS, tab, (value) => {
    tab = value;
    replace(`system/${value}`);
    load();
  }, 'System section');
  const shutdownReason = blockedReason('system', 'shut the bot down');
  page.append(
    h('header', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', { text: 'System' }), h('p', { text: 'How the bot runs: health, shards, hooks, plugins and alerts.' })),
      h('div', { class: 'page-actions' }, can('system') ? button('Shut down', { class: 'btn btn-danger btn-sm', disabled: shutdownReason ? true : null, title: shutdownReason || null, onClick: () => shutdown() }, 'power') : null)),
    h('div', { class: 'sys-tabs' }, tabs.el), body);

  async function shutdown() {
    if (!await confirm('Shut the bot down', 'The bot goes offline and only comes back when it is started again on its machine (or by a process manager).', { label: 'Shut down', danger: true })) {
      return;
    }
    const t = approvalToast('Shutting down');
    try {
      await run('system.shutdown', {}, { onStatus: t.onStatus });
      toast('The bot is shutting down.', { kind: 'ok' });
    } catch (error) {
      failure(error);
    } finally {
      t.note.close();
    }
  }

  function health(data) {
    if (!data.enabled) {
      return h('section', { class: 'card' }, empty('activity', 'Diagnostics is switched off', 'Turn on [modules] diagnostics to see health checks.'));
    }
    const r = data.report;
    const [label, kind] = STATE[data.status] || [data.status, ''];
    const hist = data.history;
    const check = button('Check now', { class: 'btn btn-sm' }, 'refresh');
    check.addEventListener('click', async () => {
      check.disabled = true;
      try {
        await run('system.health_check');
        load();
      } catch (error) {
        failure(error);
        check.disabled = false;
      }
    });
    return [
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', null, 'Health ', pill(label, kind)),
          h('p', { text: `Degraded above ${data.thresholds.error_rate}% errors or ${data.thresholds.loop_lag_ms} ms event loop lag` })), h('div', { class: 'card-tools' }, check)),
        h('div', { class: 'card-body sys-health' },
          [['Error rate', hist.map((x) => x.error_rate), `${fixed(hist.at(-1)?.error_rate ?? 0)} %`],
            ['Loop lag', hist.map((x) => x.loop_lag_ms), `${fixed(r.loop_lag_ms)} ms`],
            ['Gateway latency', hist.map((x) => x.latency_ms), `${fixed(r.bot.latency_ms)} ms`],
            ['Memory', hist.map((x) => x.memory_mb), `${fixed(hist.at(-1)?.memory_mb ?? 0)} MB`]]
            .map(([name, values, now]) => h('div', { class: 'sys-metric' }, h('span', { class: 'muted', text: name }), h('strong', { text: now }), spark(values, `${name} over the last checks`))))),
      cachesCard(),
      h('section', { class: 'card' }, h('div', { class: 'card-body' }, facts([
        ['Version', r.version], ['Uptime', duration(r.uptime_seconds)], ['Python', r.environment.python],
        ['discord.py', r.environment.discord_py], ['Platform', r.environment.platform], ['Servers', num(r.guilds)],
        ['Prefix commands', num(r.commands.prefix_total)], ['Slash commands', `${num(r.commands.top_level)} of ${num(r.commands.limit)}`],
        ['Failed extensions', Object.keys(r.extensions.failed).length ? Object.keys(r.extensions.failed).join(', ') : 'none'],
        ['Checks kept', `${hist.length} (every few minutes)`],
      ]))),
    ];
  }

  function cachesCard() {
    const box = h('div', { class: 'card-body' }, skeleton(2));
    const reason = blockedReason('settings', 'clear the caches');
    const clearBtn = button('Clear all caches', { class: 'btn btn-sm', disabled: reason ? true : null, title: reason || null }, 'trash');
    const fill = async () => {
      try {
        const c = await run('system.caches');
        mount(box, facts([
          ['File cache', `${num(c.files.cache_size)} of ${num(c.files.max_cache_size)} entries, ${c.files.hit_rate}% hits`],
          ['Reads and writes', `${num(c.files.reads)} / ${num(c.files.writes)}`],
          ['Prefix cache', `${num(c.prefixes)} servers, ${num(c.prefix_hits)} hits`],
          ['Permission cache', `${num(c.permissions)} servers`],
        ]));
      } catch (error) {
        mount(box, h('p', { class: 'muted', text: error.message }));
      }
    };
    clearBtn.addEventListener('click', async () => {
      try {
        const result = await run('system.clear_caches');
        toast(`Caches cleared, ${result.dropped} file entries dropped.`, { kind: 'ok' });
        fill();
      } catch (error) {
        failure(error);
      }
    });
    fill();
    return h('section', { class: 'card' },
      h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Caches' })), h('div', { class: 'card-tools' }, clearBtn)), box);
  }

  function shards(data) {
    return [
      data.cluster ? h('section', { class: 'card' }, h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Cluster' }))),
        h('div', { class: 'card-body' }, facts([['Mode', data.cluster.mode], ['Name', data.cluster.name], ['Address', data.cluster.address],
          ['Link', data.cluster.running ? pill('Running', 'ok') : pill('Not running', 'bad')], ['Shards here', data.cluster.shard_ids.join(', ')]]))) : null,
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: `Shards (${data.count})` }),
          h('p', { text: data.monitor ? 'With the shard monitor' : 'Turn on [modules] shards for uptime and reconnect counts.' }))),
        h('div', { class: 'card-body' }, table([
          { label: 'Shard', render: (s) => h('span', { class: 'bk-name' }, `#${s.id}`, s.closed ? pill('Closed', 'bad') : s.healthy === false ? pill(s.note, 'warn') : pill('Healthy', 'ok')) },
          { label: 'Servers', class: 'num', render: (s) => num(s.guilds) },
          { label: 'Latency', class: 'num', render: (s) => (s.latency_ms == null ? '-' : `${fixed(s.latency_ms)} ms`) },
          { label: 'Average', class: 'num', render: (s) => (s.avg_ms == null ? '-' : `${fixed(s.avg_ms)} ms`) },
          { label: 'Uptime', class: 'num', render: (s) => (s.uptime_pct == null ? '-' : `${fixed(s.uptime_pct, 2)} %`) },
          { label: 'Reconnects', class: 'num', render: (s) => (s.disconnects == null ? '-' : String(s.disconnects)) },
          { label: 'Latency trend', render: (s) => (s.history ? spark(s.history, `Latency of shard ${s.id}`) : '') },
        ], data.shards))),
    ];
  }

  function hooks(data) {
    const reason = blockedReason('extensions', 'turn hooks on or off');
    const toggle = async (hook, enabled) => {
      try {
        await run('system.hook_toggle', { id: hook.id, enabled });
        load();
      } catch (error) {
        failure(error);
      }
    };
    return [
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Registered hooks' }),
          h('p', { text: `${data.hooks.length} hooks · queue ${data.queue} · ${data.running ? 'worker running' : 'worker stopped'}` }))),
        h('div', { class: 'card-body' }, data.hooks.length ? table([
          { label: 'Event', render: (x) => h('code', { text: x.event }) },
          { label: 'Handler', render: (x) => h('span', { class: 'mono', title: x.id, text: `${x.module}.${x.name}` }) },
          { label: 'Runs', class: 'num', render: (x) => `${num(x.executions)}${x.failures ? ` (${x.failures} failed)` : ''}` },
          { label: 'Average', class: 'num', render: (x) => `${fixed(x.avg_ms)} ms` },
          { label: 'State', render: (x) => (x.tripped ? pill('Paused after errors', 'bad') : x.disabled ? pill('Off') : pill('On', 'ok')) },
          { label: '', class: 'num', render: (x) => button(x.disabled || x.tripped ? 'Turn on' : 'Turn off', { class: 'btn btn-sm', disabled: reason ? true : null, title: reason || null, onClick: () => toggle(x, x.disabled || x.tripped) }) },
        ], data.hooks) : empty('bolt', 'No hooks registered', 'Extensions register hooks to react to framework events.'))),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Recent events' }))),
        h('div', { class: 'card-body' }, data.history.length ? table([
          { label: 'When', render: (e) => ago(e.at) },
          { label: 'Event', render: (e) => h('code', { text: e.event }) },
          { label: 'Handlers', class: 'num', render: (e) => `${e.ok} ok${e.failed ? `, ${e.failed} failed` : ''}` },
          { label: 'Waited', class: 'num', render: (e) => `${fixed(e.delay_ms)} ms` },
          { label: 'Errors', render: (e) => e.errors.join('; ') },
        ], data.history.slice(0, 50)) : h('p', { class: 'muted', text: 'No events yet.' }))),
    ];
  }

  function plugins(data) {
    return h('section', { class: 'card' }, h('div', { class: 'card-body' }, data.plugins.length ? table([
      { label: 'Plugin', render: (p) => h('div', null, h('strong', { text: p.name }), h('small', { class: 'muted block', text: p.description })) },
      { label: 'Version', render: (p) => p.version },
      { label: 'Author', render: (p) => p.author },
      { label: 'Needs', render: (p) => Object.keys(p.dependencies).join(', ') || '-' },
      { label: 'Commands', class: 'num', render: (p) => String(p.commands.length) },
      { label: 'Load', class: 'num', render: (p) => `${fixed(p.load_ms)} ms` },
      { label: 'Problems', render: (p) => (p.problems.length ? h('span', { class: 'pills' }, p.problems.map((x) => pill(x, 'warn'))) : pill('None', 'ok')) },
    ], data.plugins) : empty('puzzle', 'No plugins', 'Loaded extensions with plugin metadata appear here.')));
  }

  function alerts(data) {
    const routes = Object.entries(data.channels);
    return [
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Recent alerts' }), h('p', { text: 'The last 100 since the bot started' }))),
        h('div', { class: 'card-body' }, data.alerts.length ? table([
          { label: 'When', render: (a) => shortStamp(a.at) },
          { label: 'Level', render: (a) => pill(a.level, a.level === 'error' ? 'bad' : a.level === 'warning' ? 'warn' : 'info') },
          { label: 'System', render: (a) => a.system },
          { label: 'Message', render: (a) => (a.title ? `${a.title}: ${a.message}` : a.message) },
        ], data.alerts) : empty('check', 'No alerts', 'Nothing went wrong since the bot started.'))),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Where alerts go' }), h('p', { text: 'Set with /fw alerts in Discord' }))),
        h('div', { class: 'card-body' }, routes.length ? facts(routes.map(([system, c]) => [system, c.name ? `#${c.name}` : c.id]))
          : h('p', { class: 'muted', text: 'No alert channels are set. Alerts only appear here and in the log.' }))),
    ];
  }

  function status(data) {
    const reason = blockedReason('presence', 'change the bot status');
    const rows = h('div', { class: 'presence-rows' });
    const add = (entry) => {
      const presence = h('select', { 'aria-label': 'Online status' }, data.presences.map((p) => h('option', { value: p, text: p, selected: entry.presence === p || null })));
      const type = h('select', { 'aria-label': 'Activity type' }, data.activities.map((p) => h('option', { value: p, text: p, selected: entry.type === p || null })));
      const text = h('input', { type: 'text', maxlength: '128', value: entry.text || '', 'aria-label': 'Text', placeholder: '{guilds} servers' });
      const row = h('div', { class: 'presence-row' }, presence, type, text,
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Remove', onClick: () => row.remove() }, icon('x')));
      row.read = () => ({ presence: presence.value, type: type.value, text: text.value.trim() });
      rows.appendChild(row);
    };
    data.rotation.forEach(add);
    const interval = h('input', { type: 'number', min: '10', max: '3600', value: String(data.interval) });
    const save = button('Save and apply', { class: 'btn btn-primary btn-sm', disabled: reason ? true : null }, 'check');
    save.addEventListener('click', async () => {
      try {
        await run('presence.set', { rotation: [...rows.children].map((r) => r.read()), interval: Number(interval.value) });
        toast('Status rotation saved.', { kind: 'ok' });
        load();
      } catch (error) {
        failure(error);
      }
    });
    const reset = button('Use config.toml', { class: 'btn btn-sm', disabled: reason || !data.override ? true : null }, 'undo');
    reset.addEventListener('click', async () => {
      try {
        await run('presence.set', { reset: true });
        load();
      } catch (error) {
        failure(error);
      }
    });
    return h('section', { class: 'card' },
      h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Status rotation' }),
        h('p', { text: `Placeholders: ${data.placeholders.map((p) => `{${p}}`).join(' ')}. Saved as a runtime override.` }))),
      h('div', { class: 'card-body' },
        reason ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null,
        rows,
        h('div', { class: 'presence-foot' },
          button('Add entry', { class: 'btn btn-sm', onClick: () => add({ presence: 'online', type: 'playing', text: '' }) }, 'plus'),
          h('label', { class: 'auto-pick' }, h('span', { class: 'muted', text: 'Seconds between changes' }), interval),
          h('span', { class: 'log-grow' }), reset, save),
        data.preview.length ? h('p', { class: 'muted', text: `Shown now as: ${data.preview.join('  ·  ')}` }) : null));
  }

  const LOADERS = {
    health: ['system.diagnostics', health], shards: ['system.shards', shards], hooks: ['system.hooks', hooks],
    plugins: ['system.plugins', plugins], alerts: ['system.alerts', alerts], status: ['presence.get', status],
  };

  async function load() {
    const current = tab;
    const [type, render] = LOADERS[current];
    if (!body.childElementCount) {
      mount(body, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6))));
    }
    try {
      const data = await run(type);
      if (alive && tab === current) {
        mount(body, render(data));
      }
    } catch (error) {
      if (alive && tab === current) {
        mount(body, h('section', { class: 'card' }, empty('alert', 'This could not be loaded', error.message)));
      }
    }
  }

  load();

  return {
    update(params) {
      if (params[0] && params[0] !== tab && LOADERS[params[0]]) {
        tabs.select(params[0]);
      }
    },
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}

