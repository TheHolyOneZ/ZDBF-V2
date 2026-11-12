import { h, icon } from '../core/dom.js';

export function pageHead(title, subtitle, ...actions) {
  return h('header', { class: 'page-head' },
    h('div', { class: 'page-title' }, h('h1', { text: title }), subtitle ? h('p', { text: subtitle }) : null),
    actions.length ? h('div', { class: 'page-actions' }, actions) : null);
}

export function card(title, options = {}) {
  const body = h('div', { class: 'card-body' });
  const tools = h('div', { class: 'card-tools' }, options.tools || null);
  const el = h('section', { class: `card ${options.class || ''}`.trim() },
    title ? h('header', { class: 'card-head' },
      h('div', { class: 'card-title' }, h('h2', { text: title }), options.sub ? h('p', { text: options.sub }) : null),
      tools) : null,
    body);
  return { el, body, tools };
}

export function segmented(options, value, onChange, label = 'View') {
  const thumb = h('span', { class: 'seg-thumb', 'aria-hidden': 'true' });
  const el = h('div', { class: 'seg', role: 'group', 'aria-label': label }, thumb);
  const buttons = new Map();
  function place() {
    const active = [...buttons.values()].find((node) => node.getAttribute('aria-pressed') === 'true');
    if (!active || !active.offsetWidth) {
      return;
    }
    thumb.style.setProperty('--x', `${active.offsetLeft}px`);
    thumb.style.setProperty('--w', `${active.offsetWidth}px`);
    if (el.dataset.thumb !== 'on') {
      thumb.getBoundingClientRect();
      el.dataset.thumb = 'on';
    }
  }
  function select(next, notify = true) {
    for (const [key, node] of buttons) {
      node.setAttribute('aria-pressed', String(key === next));
    }
    place();
    if (notify) {
      onChange(next);
    }
  }
  for (const option of options) {
    const node = h('button', { type: 'button', class: 'seg-item', 'aria-pressed': String(option.value === value), onClick: () => select(option.value) },
      option.label, option.count != null ? h('span', { class: 'seg-count', text: String(option.count) }) : null);
    buttons.set(option.value, node);
    el.appendChild(node);
  }
  new ResizeObserver(place).observe(el);
  return { el, select, button: (key) => buttons.get(key) };
}

export function empty(iconName, title, text, action = null) {
  return h('div', { class: 'empty' }, h('span', { class: 'empty-icon' }, icon(iconName)), h('h2', { text: title }),
    text ? h('p', { text }) : null, action);
}

export function pill(text, kind = '') {
  return h('span', { class: 'pill', dataset: { kind } }, kind ? h('span', { class: 'pill-dot' }) : null, text);
}

export function skeleton(lines = 3) {
  return h('div', { class: 'skeleton', 'aria-hidden': 'true' }, Array.from({ length: lines }, () => h('span', { class: 'skeleton-line' })));
}

export function table(columns, rows, options = {}) {
  const head = h('tr', null, columns.map((c) => h('th', { scope: 'col', class: c.class || null, text: c.label })));
  const body = rows.map((row) => h('tr', null, columns.map((c) => h('td', { class: c.class || null, dataset: { label: c.label } }, c.render(row)))));
  return h('div', { class: 'table-wrap' },
    h('table', { class: `table ${options.class || ''}`.trim() }, h('thead', null, head), h('tbody', null, body)));
}

export function facts(pairs) {
  return h('dl', { class: 'facts' }, pairs.filter(Boolean).map(([label, value]) => [h('dt', { text: label }), h('dd', null, value)]));
}

export function copyButton(getText, label = 'Copy') {
  const node = h('button', { type: 'button', class: 'btn btn-sm' }, icon('copy'), h('span', { text: label }));
  node.addEventListener('click', async () => {
    const span = node.querySelector('span');
    try {
      await navigator.clipboard.writeText(getText());
      span.textContent = 'Copied';
    } catch (error) {
      span.textContent = 'Select and copy';
    }
    setTimeout(() => { span.textContent = label; }, 2000);
  });
  return node;
}
