import { h, icon } from '../core/dom.js';
import { settle } from './motion.js';

let host = null;

function ensure() {
  if (!host) {
    host = h('div', { class: 'toasts', role: 'region', 'aria-live': 'polite', 'aria-label': 'Notifications' });
    document.body.appendChild(host);
  }
  return host;
}

export function toast(message, options = {}) {
  const kind = options.kind || 'info';
  const names = { ok: 'check', bad: 'alert', warn: 'alert', info: 'info' };
  const node = h('div', { class: 'toast', dataset: { kind }, role: kind === 'bad' ? 'alert' : 'status' },
    icon(names[kind] || 'info'),
    h('div', { class: 'toast-body' },
      options.title ? h('strong', { text: options.title }) : null,
      h('span', { text: message })),
    h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Dismiss', onClick: () => close() }, icon('x')));
  let timer = 0;
  function close() {
    clearTimeout(timer);
    node.classList.add('leaving');
    setTimeout(() => settle(host, () => node.remove()), 180);
  }
  settle(ensure(), () => host.appendChild(node));
  const timeout = options.timeout ?? (kind === 'bad' ? 9000 : 5000);
  if (timeout > 0) {
    timer = setTimeout(close, timeout);
  }
  return { close, update: (text) => { node.querySelector('.toast-body span').textContent = text; } };
}

export function failure(error, title) {
  toast(error?.message || 'Something went wrong.', { kind: 'bad', title });
}
