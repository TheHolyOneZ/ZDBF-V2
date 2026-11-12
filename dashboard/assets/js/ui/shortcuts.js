import { h } from '../core/dom.js';
import { modal } from './modal.js';

export const GO_KEYS = {
  o: 'overview', l: 'logs', y: 'system', c: 'chat', m: 'commands', s: 'servers', a: 'automations', t: 'tickets',
  f: 'files', e: 'extensions', d: 'database', p: 'panels', k: 'config', b: 'link', u: 'access', r: 'audit',
};

function typing(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  if (target.closest('input, textarea, select, [contenteditable="true"], .cm-editor')) {
    return true;
  }
  return Boolean(target.shadowRoot);
}

export function showHelp(routes) {
  const rows = [
    ['Ctrl K', 'Open the command palette'],
    ['/', 'Search on the current page'],
    ['?', 'Show these shortcuts'],
    ['Ctrl S', 'Save in the file and config editors'],
    ...Object.entries(GO_KEYS).filter(([, path]) => routes.some((r) => r.path === path))
      .map(([key, path]) => [`g ${key}`, `Go to ${routes.find((r) => r.path === path).title}`]),
  ];
  modal({
    title: 'Keyboard shortcuts',
    body: h('dl', { class: 'keys' }, rows.map(([keys, text]) => [h('dt', null, keys.split(' ').map((k) => h('kbd', { text: k }))), h('dd', { text })])),
  });
}

export function installShortcuts({ routes, go, palette }) {
  let pending = 0;
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      palette();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented || typing(event.composedPath()[0] || event.target)) {
      return;
    }
    if (document.querySelector('dialog[open]')) {
      return;
    }
    if (pending && Date.now() - pending < 1200) {
      pending = 0;
      const path = GO_KEYS[event.key.toLowerCase()];
      if (path && routes().some((r) => r.path === path)) {
        event.preventDefault();
        go(path);
      }
      return;
    }
    if (event.key === 'g') {
      pending = Date.now();
    } else if (event.key === '?') {
      event.preventDefault();
      showHelp(routes());
    } else if (event.key === '/') {
      const search = document.querySelector('#view input[type="search"], #view input.tree-search, #view .log-search');
      if (search) {
        event.preventDefault();
        search.focus();
        search.select?.();
      }
    }
  });
}
