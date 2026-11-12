import { get } from './api.js';
import { emit, session, setTopic } from './store.js';

const wanted = new Map();
const covered = new Set();
let rev = 0;
let ev = -1;
let controller = null;
let running = false;
let hiddenSince = 0;
let failures = 0;
let restartTimer = 0;
let announce = null;
const first = new Promise((resolve) => { announce = resolve; });

function topics() {
  return [...wanted.keys()].sort();
}

function restart() {
  clearTimeout(restartTimer);
  restartTimer = setTimeout(() => controller?.abort(), 30);
}

export function watch(names) {
  let added = false;
  for (const name of names) {
    const count = wanted.get(name) || 0;
    wanted.set(name, count + 1);
    added = added || count === 0;
  }
  if (added) {
    restart();
  }
  return () => {
    for (const name of names) {
      const count = (wanted.get(name) || 1) - 1;
      if (count <= 0) {
        wanted.delete(name);
        covered.delete(name);
      } else {
        wanted.set(name, count);
      }
    }
  };
}

function setConnection(state) {
  if (session.connection !== state) {
    session.connection = state;
    emit('connection', state);
  }
}

function setBot(bot) {
  const before = session.bot;
  session.bot = bot;
  if (before.online !== bot.online || before.paired !== bot.paired || before.seen_at !== bot.seen_at) {
    emit('bot', bot);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loop() {
  while (running) {
    if (document.hidden && hiddenSince && Date.now() - hiddenSince > 45000) {
      await sleep(1000);
      continue;
    }
    controller = new AbortController();
    const started = Date.now();
    const asked = topics();
    const full = asked.some((name) => !covered.has(name));
    try {
      const data = await get('api/live.php', {
        rev: full ? 0 : rev,
        ev,
        topics: asked.join(','),
        online: session.bot.paired ? (session.bot.online ? '1' : '0') : null,
      }, { signal: controller.signal });
      failures = 0;
      setConnection('ok');
      for (const name of asked) {
        if (wanted.has(name)) {
          covered.add(name);
        }
      }
      rev = Math.max(rev, data.rev || 0);
      ev = data.ev ?? ev;
      for (const [name, entry] of Object.entries(data.state || {})) {
        setTopic(name, entry);
      }
      setBot(data.bot);
      announce();
      for (const event of data.events || []) {
        emit(`event:${event.topic}`, event);
        emit('event', event);
      }
      const quiet = !Object.keys(data.state || {}).length && !(data.events || []).length;
      if (quiet && Date.now() - started < 1500) {
        await sleep(2000);
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        continue;
      }
      announce();
      if (error.code === 'auth') {
        running = false;
        return;
      }
      failures++;
      if (failures >= 2) {
        setConnection('lost');
      }
      await sleep(Math.min(15000, 1000 * 2 ** Math.min(failures, 4)));
    }
  }
}

export function start() {
  if (running) {
    return;
  }
  running = true;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hiddenSince = Date.now();
    } else {
      const away = hiddenSince ? Date.now() - hiddenSince : 0;
      hiddenSince = 0;
      if (away > 45000) {
        covered.clear();
      }
    }
  });
  loop();
}

export function ready(ms) {
  return Promise.race([first, sleep(ms)]);
}

export function refresh() {
  covered.clear();
  restart();
}
