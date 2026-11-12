import { ICONS } from './icons.js';

const SVG = 'http://www.w3.org/2000/svg';

function append(el, children) {
  for (const child of children) {
    if (child == null || child === false) {
      continue;
    }
    if (Array.isArray(child)) {
      append(el, child);
    } else if (child instanceof Node) {
      el.appendChild(child);
    } else {
      el.appendChild(document.createTextNode(String(child)));
    }
  }
}

function assign(el, props) {
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) {
      continue;
    }
    if (key === 'class') {
      el.setAttribute('class', value);
    } else if (key === 'text') {
      el.textContent = value;
    } else if (key === 'dataset') {
      for (const [name, data] of Object.entries(value)) {
        if (data != null) {
          el.dataset[name] = data;
        }
      }
    } else if (key === 'vars') {
      for (const [name, data] of Object.entries(value)) {
        el.style.setProperty(name, data);
      }
    } else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, String(value));
    }
  }
}

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    assign(el, props);
  }
  append(el, children);
  return el;
}

export function s(tag, props, ...children) {
  const el = document.createElementNS(SVG, tag);
  if (props) {
    assign(el, props);
  }
  append(el, children);
  return el;
}

export function icon(name, extra = '') {
  return s('svg', { class: `i ${extra}`.trim(), viewBox: '0 0 24 24', 'aria-hidden': 'true' },
    s('path', { d: ICONS[name] || ICONS.dot }));
}

export function add(el, ...children) {
  append(el, children);
  return el;
}

export function clear(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
  return el;
}

export function mount(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

export function button(label, props = {}, iconName = null) {
  return h('button', { type: 'button', class: 'btn', ...props }, iconName ? icon(iconName) : null,
    label ? h('span', { text: label }) : null);
}
