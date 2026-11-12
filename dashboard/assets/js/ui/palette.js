import { clear, h, icon } from '../core/dom.js';
import { refract } from './refract.js';

let dialog = null;
let lens = null;

export function openPalette(commands) {
  if (dialog) {
    return;
  }
  const input = h('input', { class: 'palette-input', type: 'text', placeholder: 'Type a page or an action', 'aria-label': 'Search', autocomplete: 'off', spellcheck: 'false' });
  const list = h('ul', { class: 'palette-list', role: 'listbox' });
  let items = [];
  let index = 0;

  function close() {
    lens?.();
    lens = null;
    dialog?.close();
    dialog?.remove();
    dialog = null;
  }

  function choose(item) {
    close();
    item.run();
  }

  const light = h('li', { class: 'palette-light', role: 'presentation', 'aria-hidden': 'true' });
  let rows = [];

  function select(next, scroll = true) {
    if (!rows.length) {
      return;
    }
    index = (next + rows.length) % rows.length;
    rows.forEach((row, i) => row.setAttribute('aria-selected', i === index ? 'true' : 'false'));
    light.style.setProperty('--y', `${rows[index].offsetTop}px`);
    if (scroll) {
      rows[index].scrollIntoView({ block: 'nearest' });
    }
  }

  function render(first = false) {
    const query = input.value.trim().toLowerCase();
    items = commands.filter((c) => !query || c.label.toLowerCase().includes(query) || (c.hint || '').toLowerCase().includes(query));
    index = Math.min(index, Math.max(0, items.length - 1));
    clear(list);
    rows = [];
    if (!items.length) {
      list.appendChild(h('li', { class: 'palette-empty', text: 'Nothing matches. Try the name of a page.' }));
      return;
    }
    list.appendChild(light);
    items.forEach((item, i) => {
      const row = h('li', {
        class: first && i < 10 ? 'palette-item rise' : 'palette-item', role: 'option', 'aria-selected': 'false',
        vars: first && i < 10 ? { '--delay': `${60 + i * 18}ms` } : null,
        onClick: () => choose(item),
        onPointermove: () => {
          if (index !== i) {
            select(i, false);
          }
        },
      }, icon(item.icon || 'right'), h('span', { text: item.label }), item.hint ? h('small', { text: item.hint }) : null);
      rows.push(row);
      list.appendChild(row);
    });
    select(index);
  }

  dialog = h('dialog', { class: 'palette', 'aria-label': 'Command palette' },
    h('div', { class: 'palette-head' }, icon('search'), input, h('kbd', { text: 'Esc' })), list);
  input.addEventListener('input', () => {
    index = 0;
    render();
  });
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      select(index + 1);
      event.preventDefault();
    } else if (event.key === 'ArrowUp') {
      select(index - 1);
      event.preventDefault();
    } else if (event.key === 'Enter' && items[index]) {
      event.preventDefault();
      choose(items[index]);
    }
  });
  dialog.addEventListener('close', () => {
    lens?.();
    lens = null;
    dialog?.remove();
    dialog = null;
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      close();
    }
  });
  document.body.appendChild(dialog);
  dialog.showModal();
  lens = refract(dialog, { rim: 24, scale: 56 });
  render(true);
  input.focus();
}
