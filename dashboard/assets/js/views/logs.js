import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { watch } from '../core/live.js';
import { on } from '../core/store.js';
import { arrive } from '../ui/motion.js';
import { empty, segmented, skeleton } from '../ui/parts.js';
import { failure } from '../ui/toast.js';

const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
const KEEP = 2000;
const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const day = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });

function recall(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch (error) {
    return fallback;
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

function keyOf(entry) {
  return `${entry.t}|${entry.name}|${entry.msg}`;
}

export default function logsView(page) {
  const stops = [];
  let alive = true;
  let entries = [];
  const seen = new Set();
  let level = recall('zdbf-logs-level', 'INFO');
  let query = '';
  let paused = false;
  let follow = true;
  let held = [];
  let searched = null;

  const list = h('div', { class: 'log-list', role: 'log', 'aria-live': 'off', tabindex: '0' }, skeleton(12));
  const counter = h('span', { class: 'muted log-count' });
  const search = h('input', { type: 'search', class: 'log-search', placeholder: 'Filter the lines below', 'aria-label': 'Filter log lines', autocomplete: 'off' });
  const pauseBtn = button('Pause', { class: 'btn btn-sm', 'aria-pressed': 'false' }, 'pause');
  const deepBtn = button('Search the whole log', { class: 'btn btn-sm', title: 'Search the last 16 MB of the log file on the bot' }, 'search');
  const saveBtn = button('Download', { class: 'btn btn-sm' }, 'download');
  const jump = button('Jump to the newest line', { class: 'btn btn-sm log-jump', hidden: true }, 'down');
  const banner = h('div', { class: 'log-banner' });
  const levels = segmented(Object.keys(LEVELS).slice(0, 4).map((name) => ({ value: name, label: name[0] + name.slice(1).toLowerCase() })), level, (value) => {
    level = value;
    remember('zdbf-logs-level', level);
    renderAll();
  }, 'Lowest level');

  page.append(
    h('header', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', { text: 'Logs' }),
        h('p', { text: 'The bot log as it is written, with tokens and secrets hidden.' }))),
    h('section', { class: 'card log-card' },
      h('div', { class: 'log-tools' }, levels.el, search, deepBtn, h('span', { class: 'log-grow' }), counter, pauseBtn, saveBtn),
      banner, list, jump));

  function visible(entry) {
    if ((LEVELS[entry.level] || 0) < LEVELS[level]) {
      return false;
    }
    if (!query) {
      return true;
    }
    const q = query.toLowerCase();
    return entry.msg.toLowerCase().includes(q) || entry.name.toLowerCase().includes(q) || (entry.exc || '').toLowerCase().includes(q);
  }

  function line(entry) {
    const date = new Date(entry.t * 1000);
    const today = date.toDateString() === new Date().toDateString();
    const node = h('div', { class: 'log-line', dataset: { level: entry.level } },
      h('time', { datetime: date.toISOString(), title: date.toLocaleString(), text: today ? clock.format(date) : `${day.format(date)} ${clock.format(date)}` }),
      h('span', { class: 'log-level', text: entry.level === 'WARNING' ? 'WARN' : entry.level === 'CRITICAL' ? 'CRIT' : entry.level }),
      h('span', { class: 'log-name', text: entry.name, title: entry.name }),
      h('span', { class: 'log-msg', text: entry.msg }));
    if (entry.exc) {
      return h('details', { class: 'log-entry' }, h('summary', null, node), h('pre', { class: 'log-exc', text: entry.exc }));
    }
    return h('div', { class: 'log-entry' }, node);
  }

  function nearBottom() {
    return list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  }

  function scrollDown() {
    list.scrollTop = list.scrollHeight;
    jump.hidden = true;
  }

  function count() {
    const shown = list.querySelectorAll('.log-entry').length;
    counter.textContent = searched ? `${shown} matches in the log file` : `${shown} of ${entries.length} lines${held.length ? `, ${held.length} new while paused` : ''}`;
  }

  function renderBanner() {
    mount(banner, searched
      ? h('p', { class: 'note', dataset: { kind: 'info' } }, `Showing the lines in the log file that contain "${searched}". `,
        h('button', { type: 'button', class: 'link-btn', text: 'Back to the live log', onClick: () => { searched = null; load(); } }))
      : null);
  }

  function renderAll() {
    const source = entries.filter(visible);
    mount(list, source.length ? source.map(line) : empty('scroll', entries.length ? 'No line matches' : 'No log lines yet',
      entries.length ? 'Change the level or the filter.' : 'Lines appear here as the bot writes them.'));
    count();
    renderBanner();
    scrollDown();
  }

  function add(fresh) {
    const keep = [];
    for (const entry of fresh) {
      const key = keyOf(entry);
      if (!seen.has(key)) {
        seen.add(key);
        keep.push(entry);
      }
    }
    if (!keep.length) {
      return;
    }
    entries.push(...keep);
    if (entries.length > KEEP) {
      for (const old of entries.splice(0, entries.length - KEEP)) {
        seen.delete(keyOf(old));
      }
    }
    const bottom = nearBottom();
    if (list.querySelector('.empty')) {
      list.textContent = '';
    }
    const quiet = keep.length > 6;
    for (const entry of keep) {
      if (visible(entry)) {
        const node = line(entry);
        list.appendChild(node);
        if (!quiet) {
          arrive(node);
        }
      }
    }
    let extra = list.querySelectorAll('.log-entry').length - KEEP;
    while (extra-- > 0) {
      list.firstChild?.remove();
    }
    if (bottom && follow) {
      scrollDown();
    } else {
      jump.hidden = false;
    }
    count();
  }

  async function load() {
    mount(list, skeleton(12));
    try {
      const data = await run('logs.history', { level: 'DEBUG', limit: KEEP });
      if (!alive) {
        return;
      }
      entries = [];
      seen.clear();
      held = [];
      add(data.entries);
      renderAll();
      if (!data.exists) {
        mount(list, empty('scroll', 'No log file yet', `The bot has not written ${data.file} yet.`));
      }
    } catch (error) {
      if (alive) {
        mount(list, empty('alert', 'The log could not be loaded', error.message));
      }
    }
  }

  async function deepSearch() {
    const text = search.value.trim();
    if (!text) {
      search.focus();
      return;
    }
    deepBtn.disabled = true;
    mount(list, skeleton(12));
    try {
      const data = await run('logs.history', { level, query: text, limit: KEEP });
      searched = text;
      query = '';
      search.value = '';
      mount(list, data.entries.length ? data.entries.map(line) : empty('search', 'Nothing found', `No line in the last 16 MB of the log contains "${text}".`));
      renderBanner();
      count();
      scrollDown();
    } catch (error) {
      failure(error, 'Search failed');
      renderAll();
    } finally {
      deepBtn.disabled = false;
    }
  }

  pauseBtn.addEventListener('click', () => {
    paused = !paused;
    pauseBtn.setAttribute('aria-pressed', String(paused));
    mount(pauseBtn, icon(paused ? 'play' : 'pause'), h('span', { text: paused ? 'Resume' : 'Pause' }));
    if (!paused && held.length) {
      const flush = held;
      held = [];
      add(flush);
    }
    count();
  });
  search.addEventListener('input', () => {
    query = search.value.trim();
    if (!searched) {
      renderAll();
    }
  });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      deepSearch();
    }
  });
  deepBtn.addEventListener('click', deepSearch);
  saveBtn.addEventListener('click', () => {
    const text = (searched ? [...list.querySelectorAll('.log-entry')].map((n) => n.textContent) : entries.filter(visible).map((e) =>
      `${new Date(e.t * 1000).toISOString()} | ${e.level.padEnd(8)} | ${e.name} | ${e.msg}${e.exc ? `\n${e.exc}` : ''}`)).join('\n');
    const link = h('a', { download: `zdbf-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`,
      href: URL.createObjectURL(new Blob([text], { type: 'text/plain' })) });
    document.body.appendChild(link);
    link.click();
    setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
  });
  jump.addEventListener('click', () => {
    follow = true;
    scrollDown();
  });
  list.addEventListener('scroll', () => {
    follow = nearBottom();
    if (follow) {
      jump.hidden = true;
    }
  });

  stops.push(watch(['logs.tail']));
  stops.push(on('event:logs.tail', (event) => {
    if (!event?.data || searched) {
      return;
    }
    if (paused) {
      held.push(event.data);
      if (held.length > KEEP) {
        held.splice(0, held.length - KEEP);
      }
      count();
      return;
    }
    add([event.data]);
  }));
  load();

  return {
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}
