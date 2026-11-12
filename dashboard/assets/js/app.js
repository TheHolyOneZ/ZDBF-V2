import { get, post, url } from './core/api.js';
import { button, clear, h, icon, mount } from './core/dom.js';
import { ago, fixed, initials } from './core/format.js';
import * as live from './core/live.js';
import * as router from './core/router.js';
import { can, on, session, subscribe, topic } from './core/store.js';
import { createField } from './ui/field.js';
import * as motion from './ui/motion.js';
import { refract } from './ui/refract.js';
import { watchSelects } from './ui/select.js';
import { openPalette } from './ui/palette.js';
import { GO_KEYS, installShortcuts, showHelp } from './ui/shortcuts.js';
import { failure, toast } from './ui/toast.js';

const GROUPS = ['Monitor', 'Control', 'Manage', 'Administration'];

router.register('overview', { title: 'Overview', icon: 'overview', group: 'Monitor', load: () => import('./views/overview.js') });
router.register('chat', { title: 'Chat', icon: 'chat', group: 'Control', capability: 'chat.read', load: () => import('./views/chat.js') });
router.register('commands', { title: 'Commands', icon: 'terminal', group: 'Control', capability: 'view', load: () => import('./views/commands.js') });
router.register('servers', { title: 'Servers', icon: 'server', group: 'Control', capability: 'view', load: () => import('./views/servers.js') });
router.register('automations', { title: 'Automations', icon: 'bolt', group: 'Control', capability: 'view', load: () => import('./views/automations.js') });
router.register('tickets', { title: 'Tickets', icon: 'megaphone', group: 'Control', capability: 'view', load: () => import('./views/tickets.js') });
router.register('files', { title: 'Files', icon: 'folder', group: 'Manage', capability: 'files.read', load: () => import('./views/files.js') });
router.register('extensions', { title: 'Extensions', icon: 'puzzle', group: 'Manage', capability: 'view', load: () => import('./views/extensions.js') });
router.register('logs', { title: 'Logs', icon: 'scroll', group: 'Monitor', capability: 'logs', load: () => import('./views/logs.js') });
router.register('system', { title: 'System', icon: 'activity', group: 'Monitor', capability: 'view', load: () => import('./views/system.js') });
router.register('database', { title: 'Database', icon: 'table', group: 'Manage', capability: 'database', load: () => import('./views/database.js') });
router.register('panels', { title: 'Panels', icon: 'panel', group: 'Manage', capability: 'view', load: () => import('./views/panels.js') });
router.register('config', { title: 'Configuration', icon: 'sliders', group: 'Manage', capability: 'config', load: () => import('./views/config.js') });
router.register('link', { title: 'Bot link', icon: 'link', group: 'Administration', capability: 'link.manage', load: () => import('./views/link.js') });
router.register('access', { title: 'Users and roles', icon: 'users', group: 'Administration', capability: 'users.manage', load: () => import('./views/access.js') });
router.register('audit', { title: 'Audit log', icon: 'list', group: 'Administration', capability: 'audit.view', load: () => import('./views/audit.js') });
router.register('sessions', { title: 'Sessions', icon: 'devices', group: 'Administration', load: () => import('./views/sessions.js') });
router.register('account', { title: 'Account', icon: 'user', group: null, load: () => import('./views/account.js') });

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    return false;
  }
  return true;
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  remember('zdbf-theme', theme);
}

function toggleTheme() {
  setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
}

async function logout() {
  try {
    await post('api/account.php', { action: 'logout' });
  } catch (error) {
    failure(error);
    return;
  }
  window.location.assign(url('login.php?e=out'));
}

function avatar(src, name, extra = '') {
  const node = h('span', { class: `avatar ${extra}`.trim(), 'aria-hidden': 'true' }, initials(name));
  if (src) {
    const img = h('img', { alt: '', referrerpolicy: 'no-referrer', src });
    img.addEventListener('load', () => mount(node, img));
  }
  return node;
}

function buildRail(shell) {
  const nav = h('nav', { class: 'rail-nav', 'aria-label': 'Main' });
  const indicator = h('span', { class: 'nav-indicator', 'aria-hidden': 'true' });
  nav.appendChild(indicator);
  const links = new Map();
  for (const group of GROUPS) {
    const routes = router.all().filter((r) => r.group === group && router.allowed(r));
    if (!routes.length) {
      continue;
    }
    nav.appendChild(h('div', { class: 'nav-group' },
      h('span', { class: 'nav-label', text: group }),
      routes.map((route) => {
        const link = h('a', { class: 'nav-item', href: `#/${route.path}`, title: route.title }, icon(route.icon), h('span', { text: route.title }));
        links.set(route.path, link);
        return link;
      })));
  }
  const user = session.user;
  const chip = h('a', { class: 'user-chip', href: '#/account', title: 'Account and security' },
    avatar(null, user.username),
    h('span', { class: 'user-text' }, h('strong', { text: user.username }), h('small', { text: user.role })));
  links.set('account', chip);
  const rail = h('aside', { class: 'rail' },
    h('a', { class: 'rail-brand', href: '#/overview' },
      h('span', { class: 'brand-mark' }, icon('z')),
      h('span', { class: 'brand-text' }, h('strong', { text: 'ZDBF' }), h('small', { text: 'Dashboard' }))),
    nav,
    h('div', { class: 'rail-foot' },
      chip,
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Log out', title: 'Log out', onClick: logout }, icon('logout'))));

  function place() {
    const route = router.active();
    const activeLink = route ? links.get(route.path) : null;
    if (activeLink && activeLink.classList.contains('nav-item')) {
      indicator.style.setProperty('--y', `${activeLink.offsetTop}px`);
      indicator.style.setProperty('--h', `${activeLink.offsetHeight}px`);
      indicator.hidden = false;
    } else {
      indicator.hidden = true;
    }
  }

  on('route', (route) => {
    for (const [name, link] of links) {
      if (name === route.path) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    }
    place();
    shell.dataset.drawer = 'closed';
  });
  new ResizeObserver(place).observe(nav);
  return rail;
}

function buildTopbar(shell) {
  const botAvatar = h('span', { class: 'bot-avatar' });
  const botName = h('strong', { text: 'No bot paired' });
  let avatarKey = null;
  const pill = h('span', { class: 'status-pill', dataset: { state: 'off' } }, h('span', { class: 'status-dot' }), h('span', { class: 'status-text', text: 'Not paired' }));

  function renderBot() {
    const meta = topic('meta');
    const overview = topic('overview');
    const bot = session.bot;
    const key = `${meta?.bot?.avatar || ''}|${meta?.bot?.name || ''}`;
    if (key !== avatarKey) {
      avatarKey = key;
      mount(botAvatar, avatar(meta?.bot?.avatar, meta?.bot?.name || 'Bot', 'avatar-sm'));
    }
    botName.textContent = bot.paired ? (meta?.bot?.name || 'Your bot') : 'No bot paired';
    let state = 'off';
    let text = 'Not paired';
    if (bot.paired && bot.online) {
      state = overview?.ready === false ? 'warn' : 'ok';
      const latency = overview?.latency_ms;
      text = overview?.ready === false ? 'Connecting to Discord' : `Online${latency != null ? ` · ${fixed(latency, 0)} ms` : ''}`;
    } else if (bot.paired) {
      state = 'bad';
      text = `Offline · seen ${ago(bot.seen_at)}`;
    }
    pill.dataset.state = state;
    pill.querySelector('.status-text').textContent = text;
  }
  subscribe('meta', renderBot);
  subscribe('overview', renderBot);
  on('bot', renderBot);
  renderBot();

  const themeButton = h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Switch theme', title: 'Switch theme', onClick: toggleTheme },
    icon('sun', 'when-dark'), icon('moon', 'when-light'));
  return h('header', { class: 'topbar' },
    h('button', {
      type: 'button', class: 'icon-btn rail-toggle', 'aria-label': 'Toggle navigation', title: 'Toggle navigation',
      onClick: () => {
        if (window.matchMedia('(max-width: 900px)').matches) {
          shell.dataset.drawer = shell.dataset.drawer === 'open' ? 'closed' : 'open';
        } else {
          shell.dataset.rail = shell.dataset.rail === 'slim' ? 'full' : 'slim';
          remember('zdbf-rail', shell.dataset.rail);
        }
      },
    }, icon('panel')),
    h('div', { class: 'bot-chip' }, botAvatar, h('div', { class: 'bot-text' }, botName, pill)),
    h('div', { class: 'topbar-space' }),
    h('button', { type: 'button', class: 'palette-trigger', onClick: palette, 'aria-label': 'Open the command palette' },
      icon('search'), h('span', { text: 'Jump to' }), h('kbd', { text: 'Ctrl K' })),
    themeButton);
}

function buildBanner() {
  const banner = h('div', { class: 'banner', hidden: true, role: 'status' });
  function render() {
    const meta = topic('meta');
    const bot = session.bot;
    let kind = '';
    let text = '';
    if (session.connection === 'lost') {
      kind = 'bad';
      text = 'The connection to the website was lost. Trying again.';
    } else if (bot.paired && !bot.online) {
      kind = 'warn';
      text = `The bot is offline. You see the last data it sent, ${ago(bot.seen_at)}.`;
    } else if (bot.paired && meta?.locked) {
      kind = 'warn';
      text = 'The bot owner locked this dashboard to view-only. Actions are refused until it is unlocked in Discord.';
    }
    banner.hidden = !text;
    banner.dataset.kind = kind;
    mount(banner, text ? icon(kind === 'bad' ? 'alert' : 'info') : null, text ? h('span', { text }) : null);
  }
  on('connection', render);
  on('bot', render);
  subscribe('meta', render);
  setInterval(render, 15000);
  return banner;
}

const SUBPAGES = [
  ['extensions/marketplace', 'Marketplace', 'Extensions', 'store'],
  ['automations/tasks', 'Scheduled tasks', 'Automations', 'clock'],
  ['config/file', 'Edit config.toml', 'Configuration', 'file'],
  ['system/shards', 'Shards', 'System', 'server'],
  ['system/hooks', 'Event hooks', 'System', 'bolt'],
  ['system/plugins', 'Plugins', 'System', 'puzzle'],
  ['system/alerts', 'Alerts', 'System', 'alert'],
  ['system/status', 'Bot status rotation', 'System', 'megaphone'],
];

function palette() {
  const allowed = router.all().filter(router.allowed);
  const keyOf = Object.fromEntries(Object.entries(GO_KEYS).map(([key, path]) => [path, key]));
  const commands = allowed.map((route) => ({
    label: route.title, hint: keyOf[route.path] ? `Go to page · g ${keyOf[route.path]}` : 'Go to page', icon: route.icon,
    run: () => router.go(route.path),
  }));
  for (const [path, label, parent, iconName] of SUBPAGES) {
    if (allowed.some((r) => r.path === path.split('/')[0])) {
      commands.push({ label, hint: parent, icon: iconName, run: () => router.go(path) });
    }
  }
  if (allowed.some((r) => r.path === 'panels')) {
    for (const panel of topic('meta')?.panels || []) {
      commands.push({ label: panel.title, hint: 'Extension panel', icon: 'panel', run: () => router.go(`panels/${panel.id}`) });
    }
  }
  if (allowed.some((r) => r.path === 'servers')) {
    for (const guild of (topic('guilds')?.items || []).slice(0, 100)) {
      if (guild.id && guild.name) {
        commands.push({ label: guild.name, hint: 'Server', icon: 'server', run: () => router.go(`servers/${guild.id}`) });
      }
    }
  }
  commands.push(
    { label: 'Keyboard shortcuts', hint: '?', icon: 'info', run: () => showHelp(allowed) },
    { label: 'Switch theme', hint: 'Light or dark', icon: 'sun', run: toggleTheme },
    { label: 'Refresh data', hint: 'Ask for everything again', icon: 'refresh', run: () => { live.refresh(); toast('Refreshing.'); } },
    { label: 'Log out', hint: session.user.username, icon: 'logout', run: logout },
  );
  openPalette(commands);
}

function startField() {
  const canvas = h('canvas', { class: 'backdrop', 'aria-hidden': 'true' });
  document.body.prepend(canvas);
  const root = document.documentElement;
  const field = createField(canvas, { light: root.getAttribute('data-theme') === 'light' });
  if (field.mode === 'off') {
    canvas.remove();
    return;
  }
  new MutationObserver(() => field.setLight(root.getAttribute('data-theme') === 'light'))
    .observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  let last = 0;
  function ripple(path, kind) {
    const now = performance.now();
    if (now - last < 500 || document.hidden) {
      return;
    }
    last = now;
    const link = document.querySelector(`.nav-item[href="#/${path}"]`);
    const box = link?.getBoundingClientRect();
    if (box && box.width && box.right > 0) {
      field.ripple(box.left + box.width / 2, box.top + box.height / 2, kind);
    } else {
      field.ripple(window.innerWidth / 2, 40, kind);
    }
  }
  let seen = null;
  subscribe('overview', (overview) => {
    const commands = overview?.commands;
    if (!commands) {
      return;
    }
    if (seen && commands.errors > seen.errors) {
      ripple('logs', 2);
    } else if (seen && commands.total > seen.total) {
      ripple('commands', 0);
    }
    seen = { total: commands.total, errors: commands.errors };
  });
  on('event', (event) => {
    const name = String(event?.topic || '');
    if (name.startsWith('chat')) {
      ripple('chat', 1);
    } else if (name === 'logs.tail' && ['ERROR', 'CRITICAL'].includes(String(event.data?.level || '').toUpperCase())) {
      ripple('logs', 2);
    }
  });
}

async function boot() {
  const app = document.getElementById('app');
  let data;
  try {
    data = await get('api/session.php');
  } catch (error) {
    mount(app, h('div', { class: 'empty' }, h('h2', { text: 'The dashboard could not start' }),
      h('p', { text: error.message }), button('Try again', { class: 'btn btn-primary', onClick: () => window.location.reload() })));
    return;
  }
  Object.assign(session, {
    user: data.user, csrf: data.csrf, version: data.version, hold: data.hold, oauth: data.oauth,
    capabilities: data.capabilities, bot: data.bot,
  });
  let railMode = 'full';
  try {
    railMode = localStorage.getItem('zdbf-rail') === 'slim' ? 'slim' : 'full';
  } catch (error) {
    railMode = 'full';
  }
  const shell = h('div', { class: 'shell', dataset: { rail: railMode, drawer: 'closed' } });
  const outlet = h('main', { class: 'content', id: 'view', tabindex: '-1' });
  shell.append(
    buildRail(shell),
    h('div', { class: 'scrim', onClick: () => { shell.dataset.drawer = 'closed'; } }),
    h('div', { class: 'main' }, buildTopbar(shell), buildBanner(), outlet),
  );
  app.classList.remove('boot');
  app.removeAttribute('aria-busy');
  mount(app, shell);
  installShortcuts({ routes: () => router.all().filter(router.allowed), go: router.go, palette });
  watchSelects();
  live.watch(can('view') ? ['meta', 'overview'] : []);
  live.start();
  if (can('view')) {
    await live.ready(1200);
  }
  await router.start(outlet);
  requestAnimationFrame(() => {
    startField();
    refract(document.querySelector('.rail'));
    motion.glassLight();
    motion.magnetic();
    motion.load();
  });
}

boot();
