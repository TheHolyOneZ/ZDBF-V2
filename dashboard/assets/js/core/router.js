import { clear, h } from './dom.js';
import { enter, leave } from '../ui/motion.js';
import { can, emit } from './store.js';

const routes = new Map();
let outlet = null;
let cleanup = null;
let current = null;
let token = 0;

export function register(path, route) {
  routes.set(path, { path, ...route });
}

export function all() {
  return [...routes.values()];
}

export function allowed(route) {
  return !route.capability || can(route.capability);
}

export function path() {
  const hash = window.location.hash.replace(/^#\/?/, '');
  return hash.split('?')[0] || 'overview';
}

function parts() {
  const [name, ...rest] = path().split('/');
  return { name, params: rest.map((part) => decodeURIComponent(part)) };
}

export function go(target) {
  window.location.hash = `#/${target}`;
}

export function replace(target) {
  window.history.replaceState(null, '', `#/${target}`);
}

function teardown() {
  const destroy = typeof cleanup === 'function' ? cleanup : cleanup?.destroy;
  cleanup = null;
  if (typeof destroy === 'function') {
    try {
      destroy();
    } catch (error) {
      console.error(error);
    }
  }
}

async function render() {
  const mine = ++token;
  let { name, params } = parts();
  let route = routes.get(name);
  if (!route || !allowed(route)) {
    route = routes.get('overview');
    params = [];
    if (name !== 'overview') {
      window.history.replaceState(null, '', '#/overview');
    }
  }
  if (route === current && typeof cleanup?.update === 'function') {
    cleanup.update(params);
    return;
  }
  const [module] = await Promise.all([route.load(), leave(outlet)]);
  if (mine !== token) {
    return;
  }
  teardown();
  clear(outlet);
  const page = h('div', { class: 'page', dataset: { route: route.path } });
  outlet.appendChild(page);
  current = route;
  document.title = `${route.title} · ZDBF Dashboard`;
  emit('route', route);
  try {
    cleanup = module.default(page, { params }) || null;
  } catch (error) {
    console.error(error);
    page.appendChild(h('div', { class: 'empty' }, h('h2', { text: 'This page could not be shown' }),
      h('p', { text: 'Reload the page. If it keeps happening, check the browser console.' })));
  }
  outlet.scrollTop = 0;
  window.scrollTo(0, 0);
  enter(outlet, page);
}

export function start(element) {
  outlet = element;
  window.addEventListener('hashchange', render);
  return render();
}

export function active() {
  return current;
}
