import { clear, h, icon, mount, s } from '../core/dom.js';
import { ago, bytes, compact, duration, fixed, initials, num, shortStamp, stamp, time } from '../core/format.js';
import { watch } from '../core/live.js';
import { stagger, tilt, tween } from '../ui/motion.js';
import { can, on, session, subscribe, topic } from '../core/store.js';
import { chartGroup, meter, rankedBars } from '../ui/chart.js';
import { card, empty, facts, pageHead, pill, segmented, skeleton, table } from '../ui/parts.js';

const SERIES = [
  { key: 'cpu', title: 'CPU', min: 5, format: (v) => `${fixed(v, 1)}%` },
  { key: 'rss_mb', title: 'Memory', min: 50, format: (v) => `${fixed(v, 0)} MB` },
  { key: 'latency_ms', title: 'Gateway latency', min: 50, format: (v) => `${fixed(v, 0)} ms` },
  { key: 'lag_ms', title: 'Event loop lag', min: 5, format: (v) => `${fixed(v, 1)} ms` },
  { key: 'commands_per_min', title: 'Commands per minute', min: 2, format: (v) => fixed(v, 1) },
];

const RING = 2 * Math.PI * 80;
const RING_FULL = 500;
const TRACE = { width: 600, height: 112, top: 16, bottom: 30 };
const MINUTES = 15;

function niceMax(value, floor) {
  const target = Math.max(value * 1.2, floor);
  const power = 10 ** Math.floor(Math.log10(target));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (step * power >= target) {
      return step * power;
    }
  }
  return 10 * power;
}

function fact(label, big = false) {
  const value = h('dd', { text: '-' });
  return { el: h('div', { class: big ? 'fact fact-big' : 'fact' }, h('dt', { text: label }), value), value };
}

function buildPulse() {
  const arc = s('circle', { class: 'ring-arc', cx: 100, cy: 100, r: 80, transform: 'rotate(-90 100 100)' });
  const wave = s('circle', { class: 'ring-wave', cx: 100, cy: 100, r: 80 });
  const number = h('span', { class: 'ring-number', text: '-' });
  const ring = h('div', { class: 'ring', role: 'img', 'aria-label': 'Gateway latency' },
    s('svg', { viewBox: '0 0 200 200', 'aria-hidden': 'true' },
      s('circle', { class: 'ring-ticks', cx: 100, cy: 100, r: 95 }),
      s('circle', { class: 'ring-track', cx: 100, cy: 100, r: 80 }),
      wave, arc),
    h('div', { class: 'ring-read' },
      h('span', { class: 'ring-value' }, number, h('small', { text: 'ms' })),
      h('span', { class: 'ring-label', text: 'Gateway latency' })));
  arc.style.strokeDasharray = `0 ${RING.toFixed(1)}`;

  const facts = {
    uptime: fact('Uptime', true), started: fact('Started'), shards: fact('Shards'),
    lag: fact('Event loop lag'), memory: fact('Bot memory'),
  };
  const avatar = h('span', { class: 'avatar pulse-avatar', 'aria-hidden': 'true' });
  const name = h('strong', { text: 'Your bot' });
  const tag = h('small');
  const state = h('span', { class: 'pulse-state' });

  const line = s('path', { class: 'trace-line' });
  const area = s('path', { class: 'trace-area' });
  const grid = s('line', { class: 'trace-grid', x1: 0, x2: TRACE.width, y1: TRACE.top, y2: TRACE.top });
  const top = h('span', { class: 'trace-y' });
  const start = h('span', { class: 'trace-x0' });
  const dot = h('span', { class: 'trace-dot', hidden: true });
  const cross = h('span', { class: 'trace-cross' });
  const tip = h('span', { class: 'trace-tip' });
  const trace = h('figure', { class: 'trace', 'aria-label': 'Gateway latency over the last 15 minutes' },
    s('svg', { viewBox: `0 0 ${TRACE.width} ${TRACE.height}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
      s('defs', null, s('linearGradient', { id: 'trace-fill', x1: 0, y1: 0, x2: 0, y2: 1 },
        s('stop', { class: 'trace-stop-a', offset: 0 }), s('stop', { class: 'trace-stop-b', offset: 1 }))),
      grid, area, line),
    h('div', { class: 'trace-labels' }, top, start, h('span', { class: 'trace-x1', text: 'now' })),
    cross, dot, tip);
  top.style.top = `${(TRACE.top / TRACE.height) * 100}%`;
  let samples = [];

  trace.addEventListener('pointermove', (event) => {
    if (samples.length < 2) {
      return;
    }
    const box = trace.getBoundingClientRect();
    const plot = box.width - 20;
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / plot));
    const sample = samples[Math.round(ratio * (samples.length - 1))];
    const x = ratio * plot;
    cross.style.left = `${x}px`;
    cross.dataset.on = 'true';
    mount(tip, `${fixed(sample.v, 0)} ms`, h('small', { text: time(sample.t) }));
    tip.dataset.on = 'true';
    tip.style.left = `${Math.min(plot - 130, Math.max(8, x + 10))}px`;
  });
  trace.addEventListener('pointerleave', () => {
    cross.dataset.on = 'false';
    tip.dataset.on = 'false';
  });

  const el = h('article', { class: 'card pulse' },
    h('header', { class: 'pulse-head' }, avatar, h('span', { class: 'pulse-name' }, name, tag), state),
    h('div', { class: 'pulse-body' }, ring,
      h('dl', { class: 'pulse-facts' }, Object.values(facts).map((item) => item.el))),
    trace);

  return {
    el, facts, name, tag, state, avatar,
    latency(value) {
      if (value == null) {
        number.textContent = '-';
        arc.style.strokeDasharray = `0 ${RING.toFixed(1)}`;
        return;
      }
      const changed = Number(number.dataset.value) !== value;
      tween(number, value, (v) => fixed(v, 0));
      ring.setAttribute('aria-label', `Gateway latency ${fixed(value, 0)} milliseconds`);
      arc.style.strokeDasharray = `${(RING * Math.min(1, value / RING_FULL)).toFixed(1)} ${RING.toFixed(1)}`;
      if (changed) {
        wave.classList.remove('pulse-wave');
        wave.getBoundingClientRect();
        wave.classList.add('pulse-wave');
      }
    },
    series(points) {
      samples = points.filter((p) => typeof p.v === 'number' && Number.isFinite(p.v));
      dot.hidden = samples.length < 2;
      if (samples.length < 2) {
        line.setAttribute('d', '');
        area.setAttribute('d', '');
        return;
      }
      const max = niceMax(Math.max(...samples.map((p) => p.v)), 200);
      const span = TRACE.height - TRACE.top - TRACE.bottom;
      const y = (v) => TRACE.top + (1 - Math.min(1, v / max)) * span;
      const d = samples.map((p, i) => `${i ? 'L' : 'M'}${((i / (samples.length - 1)) * TRACE.width).toFixed(1)} ${y(p.v).toFixed(1)}`).join('');
      line.setAttribute('d', d);
      area.setAttribute('d', `${d}L${TRACE.width} ${TRACE.height}L0 ${TRACE.height}Z`);
      top.textContent = `${num(max)} ms`;
      start.textContent = time(samples[0].t);
      dot.style.top = `${(y(samples[samples.length - 1].v) / TRACE.height) * 100}%`;
    },
  };
}

function tile(label, iconName, extra) {
  const value = h('strong', { class: 'stat-value', text: '-' });
  const note = h('span', { class: 'stat-note' });
  const el = h('article', { class: `stat ${extra}` },
    h('header', { class: 'stat-head' }, h('span', { class: 'stat-label', text: label }), icon(iconName)),
    h('div', { class: 'stat-foot' }, value, note));
  return { el, value, note };
}

function buildCommands() {
  const value = h('strong', { class: 'stat-value', text: '-' });
  const registered = h('b', { text: '-' });
  const bars = h('div', { class: 'minute-bars', role: 'img', 'aria-label': 'Commands per minute over the last 15 minutes' });
  const el = h('article', { class: 'stat tile-commands' },
    h('div', { class: 'commands-top' },
      h('div', null, h('span', { class: 'stat-label', text: 'Commands run' }), value),
      h('p', { class: 'commands-rate' }, registered, 'registered')),
    h('figure', { class: 'commands-chart' }, bars,
      h('figcaption', { class: 'bars-caption' }, h('span', { text: 'Per minute, 15 minutes ago' }), h('span', { text: 'now' }))));
  return {
    el, value, registered,
    series(points) {
      if (!points.length) {
        return;
      }
      const end = points[points.length - 1].t;
      const sums = Array.from({ length: MINUTES }, () => ({ total: 0, count: 0 }));
      for (const point of points) {
        const slot = MINUTES - 1 - Math.floor((end - point.t) / 60);
        if (slot >= 0 && typeof point.v === 'number') {
          sums[slot].total += point.v;
          sums[slot].count += 1;
        }
      }
      const rates = sums.map((slot) => (slot.count ? slot.total / slot.count : 0));
      const max = Math.max(2, ...rates);
      mount(bars, rates.map((rate, i) => h('i', {
        vars: { '--v': String(rate / max) },
        title: `${fixed(rate, 1)} per minute, ${time(end - (MINUTES - 1 - i) * 60)}`,
      })));
      bars.setAttribute('aria-label', `Commands per minute over the last 15 minutes, highest ${fixed(Math.max(...rates), 1)}`);
    },
  };
}

function buildReach() {
  const rows = { guilds: h('dd', { text: '-' }), members: h('dd', { text: '-' }), each: h('dd', { text: '-' }) };
  const el = h('article', { class: 'stat tile-reach' },
    h('header', { class: 'stat-head' }, h('span', { class: 'stat-label', text: 'Servers and members' }), icon('users')),
    h('dl', { class: 'reach' },
      h('div', null, h('dt', { text: 'Servers' }), rows.guilds),
      h('div', null, h('dt', { text: 'Members' }), rows.members),
      h('div', null, h('dt', { text: 'Per server' }), rows.each)));
  return { el, ...rows };
}

function plural(count, word) {
  return `${num(count)} ${word}${count === 1 ? '' : 's'}`;
}

export default function overview(page) {
  const stops = [];
  if (!can('view')) {
    page.append(pageHead('Overview'), empty('lock', 'Nothing to show', 'Your role cannot view the bot status.'));
    return null;
  }
  const subtitle = h('p', { text: 'Live status of your bot.' });
  const head = h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Overview' }), subtitle));
  const body = h('div', { class: 'overview' });
  page.append(head, body);

  const pulse = buildPulse();
  const commands = buildCommands();
  const errors = tile('Error rate', 'alert', 'tile-errors');
  const reach = buildReach();
  const stats = h('div', { class: 'bento' }, pulse.el, commands.el, errors.el, reach.el);
  stops.push(tilt([commands.el, errors.el, reach.el]));
  let avatarKey = null;

  const charts = chartGroup(SERIES, { range: 'last 15 minutes' });
  const chartMode = segmented([{ value: 'chart', label: 'Charts' }, { value: 'table', label: 'Table' }], 'chart',
    (mode) => charts.setMode(mode), 'Show as');
  const chartCard = card('Performance', { sub: 'Last 15 minutes, one reading every 5 seconds', tools: chartMode.el, class: 'span-all' });
  chartCard.body.appendChild(charts.element);
  stops.push(() => charts.destroy());

  const topCard = card('Most used commands', { sub: 'Since the bot started' });
  const healthCard = card('Resources');
  const shardCard = card('Shards', { class: 'span-all' });
  const runtimeCard = card('Runtime');
  let feed = 'commands';
  const feedMode = segmented([
    { value: 'commands', label: 'Commands' }, { value: 'errors', label: 'Errors' }, { value: 'alerts', label: 'Alerts' },
  ], feed, (next) => { feed = next; renderActivity(topic('activity')); }, 'Recent activity');
  const feedCard = card('Recent activity', { tools: feedMode.el });
  for (const c of [topCard, healthCard, runtimeCard, feedCard]) {
    c.body.appendChild(skeleton(4));
  }
  const grid = h('div', { class: 'grid-2' }, chartCard.el, topCard.el, feedCard.el, healthCard.el, runtimeCard.el, shardCard.el);
  shardCard.el.hidden = true;

  function renderShell() {
    const bot = session.bot;
    const has = Boolean(topic('overview'));
    clear(body);
    if (!bot.paired) {
      body.appendChild(empty('link', 'No bot is paired yet',
        'Connect your ZDBF bot to this dashboard. It takes one command in Discord.',
        can('link.manage') ? h('a', { class: 'btn btn-primary', href: '#/link' }, 'Pair a bot') : null));
      return;
    }
    if (!has) {
      body.appendChild(empty('clock', 'Waiting for the first report',
        bot.online ? 'The bot is connected. Its status appears here in a moment.' : 'The bot is paired but has not reported yet. Check that it is running.'));
      return;
    }
    body.append(stats, grid);
    stagger([...stats.children, ...grid.children].filter((n) => !n.hidden));
  }

  function renderOverview(o) {
    if (!o) {
      return;
    }
    if (!stats.isConnected) {
      renderShell();
    }
    const shards = o.shards || [];
    const up = shards.filter((shard) => !shard.closed).length;
    pulse.latency(o.latency_ms);
    mount(pulse.state, pill(o.ready ? 'Connected to Discord' : 'Connecting', o.ready ? 'ok' : 'warn'));
    pulse.facts.uptime.value.textContent = duration(o.uptime);
    pulse.facts.started.value.textContent = shortStamp(o.started_at);
    pulse.facts.started.value.title = stamp(o.started_at);
    pulse.facts.shards.value.textContent = shards.length ? `${up} of ${shards.length} connected` : plural(1, 'shard');
    pulse.facts.lag.value.textContent = o.loop_lag_ms == null ? '-' : `${fixed(o.loop_lag_ms, 1)} ms`;
    pulse.facts.memory.value.textContent = bytes(o.process.rss);
    tween(commands.value, o.commands.total, (v) => (v < 100000 ? num(Math.round(v)) : compact(Math.round(v))));
    commands.registered.textContent = num(o.commands.registered);
    errors.value.textContent = `${fixed(o.commands.error_rate, 1)}%`;
    errors.note.textContent = `${plural(o.commands.errors, 'error')} since start`;
    errors.el.dataset.level = o.commands.error_rate >= 10 ? 'bad' : o.commands.error_rate >= 3 ? 'warn' : '';
    tween(reach.guilds, o.guilds, (v) => num(Math.round(v)));
    tween(reach.members, o.members, (v) => compact(Math.round(v)));
    reach.each.textContent = o.guilds ? num(Math.round(o.members / o.guilds)) : '-';

    const top = (o.commands.top || []).slice(0, 8).map(([label, value]) => ({ label, value }));
    mount(topCard.body, top.length
      ? rankedBars(top, (v) => num(v))
      : h('p', { class: 'muted', text: 'No commands have run since the bot started.' }));

    const p = o.process;
    const slash = o.commands.slash;
    const lagLimit = o.loop_lag_threshold_ms;
    mount(healthCard.body,
      meter('Bot memory', p.rss / (p.system_memory_total || 1), `${bytes(p.rss)} of ${bytes(p.system_memory_total)}`),
      meter('Bot CPU', p.cpu / 100, `${fixed(p.cpu, 1)}% of one core`),
      meter('Host memory', p.system_memory / 100, `${fixed(p.system_memory, 0)}% in use`, { warn: 0.85, bad: 0.95 }),
      o.disk ? meter('Disk', o.disk.used / (o.disk.total || 1), `${bytes(o.disk.free)} free of ${bytes(o.disk.total)}`, { warn: 0.85, bad: 0.95 }) : null,
      lagLimit && o.loop_lag_ms != null
        ? meter('Event loop lag', o.loop_lag_ms / lagLimit, `${fixed(o.loop_lag_ms, 1)} ms, alert at ${lagLimit} ms`, { warn: 0.5, bad: 1 }) : null,
      meter('Slash commands', slash.top_level / slash.limit, `${slash.top_level} of ${slash.limit}${slash.demoted ? `, ${slash.demoted} prefix-only` : ''}`, { warn: 0.9, bad: 1 }));

    shardCard.el.hidden = shards.length < 2;
    if (shards.length > 1) {
      mount(shardCard.body, table([
        { label: 'Shard', render: (s) => `#${s.id}` },
        { label: 'State', render: (s) => pill(s.closed ? 'Disconnected' : 'Connected', s.closed ? 'bad' : 'ok') },
        { label: 'Latency', class: 'n', render: (s) => (s.latency_ms == null ? '-' : `${fixed(s.latency_ms, 0)} ms`) },
        { label: 'Servers', class: 'n', render: (s) => num(s.guilds) },
      ], shards));
    }
    renderRuntime();
  }

  function renderRuntime() {
    const meta = topic('meta');
    const o = topic('overview');
    if (!meta || !o) {
      return;
    }
    subtitle.textContent = `${meta.bot?.tag || meta.bot?.name || 'Your bot'} on ZDBF ${meta.version}`;
    pulse.name.textContent = meta.bot?.name || 'Your bot';
    pulse.tag.textContent = meta.bot?.tag || '';
    const key = `${meta.bot?.avatar || ''}|${meta.bot?.name || ''}`;
    if (key !== avatarKey) {
      avatarKey = key;
      mount(pulse.avatar, initials(meta.bot?.name || 'Bot'));
      if (meta.bot?.avatar) {
        const img = h('img', { alt: '', referrerpolicy: 'no-referrer', src: meta.bot.avatar });
        img.addEventListener('load', () => mount(pulse.avatar, img));
      }
    }
    const ext = o.extensions;
    mount(runtimeCard.body, facts([
      ['ZDBF', meta.version],
      ['discord.py', meta.discord_py],
      ['Python', `${meta.python} on ${meta.platform}`],
      ['Prefix', h('code', { text: meta.prefix })],
      ['Modules', `${ext.modules} built-in`],
      ['Extensions', ext.failed ? h('span', null, `${ext.loaded} loaded, `, pill(`${ext.failed} failed`, 'bad')) : `${ext.loaded} loaded`],
      ['Messages seen', num(o.commands.messages)],
      ['Interactions', num(o.commands.interactions)],
      ['Database queries', num(o.database.queries)],
      !o.hooks.running ? ['Event hooks', pill('Worker stopped', 'bad')] : o.hooks.queue > 50 ? ['Event hooks', pill(`${o.hooks.queue} queued`, 'warn')] : null,
      ['Process', `PID ${o.process.pid}, ${o.process.threads} threads`],
      o.approvals_pending ? ['Approvals waiting', pill(String(o.approvals_pending), 'warn')] : null,
    ]));
  }

  function renderSeries(data) {
    if (!data) {
      return;
    }
    const points = (data.points || []).map((p) => ({
      t: p[0], values: { cpu: p[1], rss_mb: p[2], latency_ms: p[3], lag_ms: p[4], commands_per_min: p[5] },
    }));
    charts.update(points);
    pulse.series(points.map((p) => ({ t: p.t, v: p.values.latency_ms })));
    commands.series(points.map((p) => ({ t: p.t, v: p.values.commands_per_min })));
  }

  function renderActivity(data) {
    if (!data) {
      return;
    }
    feedMode.button('errors').dataset.alert = data.errors.length ? 'true' : 'false';
    const now = Date.now() / 1000;
    const rows = {
      commands: () => data.commands.map((c) => h('li', { class: 'feed-row' },
        h('code', { text: c.name }), h('time', { title: stamp(c.at), text: ago(c.at, now) }))),
      errors: () => data.errors.map((e) => h('li', { class: 'feed-row feed-block' },
        h('div', { class: 'feed-top' }, h('code', { text: e.command }), h('time', { title: stamp(e.at), text: ago(e.at, now) })),
        h('p', { text: e.error }))),
      alerts: () => data.alerts.map((a) => h('li', { class: 'feed-row feed-block' },
        h('div', { class: 'feed-top' },
          pill(a.system, a.level === 'error' || a.level === 'critical' ? 'bad' : a.level === 'warning' ? 'warn' : 'info'),
          h('time', { title: stamp(a.at), text: time(a.at) })),
        h('p', { text: a.message }))),
    }[feed]();
    const nothing = { commands: 'No commands yet.', errors: 'No errors. Good.', alerts: 'No alerts since the bot started.' }[feed];
    mount(feedCard.body, rows.length ? h('ul', { class: 'feed' }, rows) : h('p', { class: 'muted', text: nothing }));
  }

  renderShell();
  stops.push(watch(['series', 'activity']));
  stops.push(subscribe('overview', renderOverview));
  stops.push(subscribe('meta', renderRuntime));
  stops.push(subscribe('series', renderSeries));
  stops.push(subscribe('activity', renderActivity));
  stops.push(on('bot', () => {
    if (!stats.isConnected || !session.bot.paired) {
      renderShell();
    }
  }));
  const ticker = setInterval(() => renderActivity(topic('activity')), 20000);
  stops.push(() => clearInterval(ticker));
  return () => stops.forEach((stop) => stop());
}
