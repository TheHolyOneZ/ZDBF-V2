import { h, icon } from '../core/dom.js';

const VALUE = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
const INDEX = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
const parts = new WeakMap();
let open = null;
let serial = 0;

function nameOf(select) {
  const own = select.getAttribute('aria-label');
  if (own) {
    return own;
  }
  const label = select.closest('label');
  const text = label?.querySelector(':scope > span');
  return text ? text.textContent.trim() : '';
}

function close(focus = false) {
  if (!open) {
    return;
  }
  const { button, pop, stop } = open;
  open = null;
  stop();
  pop.remove();
  button.setAttribute('aria-expanded', 'false');
  button.removeAttribute('aria-activedescendant');
  if (focus) {
    button.focus();
  }
}

function choose(select, option) {
  if (option.disabled) {
    return;
  }
  const before = VALUE.get.call(select);
  option.selected = true;
  parts.get(select)?.sync();
  if (VALUE.get.call(select) !== before) {
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function place(button, pop) {
  const box = button.getBoundingClientRect();
  const below = window.innerHeight - box.bottom - 12;
  const above = box.top - 12;
  const up = below < Math.min(220, pop.scrollHeight) && above > below;
  const room = Math.max(120, up ? above : below);
  pop.style.minWidth = `${box.width}px`;
  pop.style.maxWidth = `${Math.max(box.width, Math.min(420, window.innerWidth - 16))}px`;
  pop.style.maxHeight = `${Math.min(340, room)}px`;
  pop.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - pop.offsetWidth - 8))}px`;
  if (up) {
    pop.style.top = 'auto';
    pop.style.bottom = `${window.innerHeight - box.top + 6}px`;
  } else {
    pop.style.bottom = 'auto';
    pop.style.top = `${box.bottom + 6}px`;
  }
  pop.dataset.side = up ? 'up' : 'down';
}

function show(select) {
  const { button } = parts.get(select);
  close();
  const id = `sel-${++serial}`;
  const options = [...select.options].filter((option) => !option.hidden);
  const rows = options.map((option, index) => h('div', {
    class: 'sel-option', role: 'option', id: `${id}-${index}`,
    'aria-selected': option.selected ? 'true' : 'false', 'aria-disabled': option.disabled ? 'true' : null,
  }, h('span', { text: option.textContent || ' ' }), option.selected ? icon('check') : null));
  const pop = h('div', { class: 'sel-pop', role: 'listbox', id, 'aria-label': nameOf(select) || null }, rows);
  let active = Math.max(0, options.findIndex((option) => option.selected));

  function mark(next, scroll = true) {
    if (!rows.length) {
      return;
    }
    active = Math.max(0, Math.min(rows.length - 1, next));
    rows.forEach((row, index) => row.classList.toggle('active', index === active));
    button.setAttribute('aria-activedescendant', rows[active].id);
    if (scroll) {
      rows[active].scrollIntoView({ block: 'nearest' });
    }
  }

  rows.forEach((row, index) => {
    row.addEventListener('pointermove', () => {
      if (active !== index) {
        mark(index, false);
      }
    });
    row.addEventListener('click', () => {
      choose(select, options[index]);
      close(true);
    });
  });
  const outside = (event) => {
    if (!pop.contains(event.target) && !button.contains(event.target)) {
      close();
    }
  };
  const away = (event) => {
    if (!pop.contains(event.target)) {
      close();
    }
  };
  const moved = () => close();
  const gone = new MutationObserver(() => {
    if (!button.isConnected) {
      close();
    }
  });
  gone.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('pointerdown', outside, true);
  window.addEventListener('scroll', away, true);
  window.addEventListener('resize', moved);
  (select.closest('dialog') || document.body).appendChild(pop);
  button.setAttribute('aria-expanded', 'true');
  button.setAttribute('aria-controls', id);
  open = {
    select, button, pop, mark, options,
    get active() {
      return active;
    },
    stop() {
      gone.disconnect();
      document.removeEventListener('pointerdown', outside, true);
      window.removeEventListener('scroll', away, true);
      window.removeEventListener('resize', moved);
    },
  };
  place(button, pop);
  mark(active);
}

function typed(select, state, key) {
  clearTimeout(state.timer);
  state.text += key.toLowerCase();
  state.timer = setTimeout(() => { state.text = ''; }, 700);
  const options = [...select.options].filter((option) => !option.hidden && !option.disabled);
  const from = open?.select === select ? open.active : select.selectedIndex;
  const order = [...options.slice(from + (state.text.length === 1 ? 1 : 0)), ...options.slice(0, from + 1)];
  const hit = order.find((option) => option.textContent.trim().toLowerCase().startsWith(state.text));
  if (!hit) {
    return;
  }
  if (open?.select === select) {
    open.mark(open.options.indexOf(hit));
  } else {
    choose(select, hit);
  }
}

function single(select) {
  const text = h('span', { class: 'sel-text' });
  const button = h('button', { type: 'button', class: 'sel', 'aria-haspopup': 'listbox', 'aria-expanded': 'false' }, text, icon('down'));
  const state = { text: '', timer: 0 };

  function sync() {
    const option = select.selectedOptions[0];
    const shown = option ? option.textContent : '';
    text.textContent = shown || ' ';
    button.dataset.empty = option && VALUE.get.call(select) !== '' ? 'false' : 'true';
    button.disabled = select.disabled;
    button.hidden = select.hidden;
    const label = nameOf(select);
    if (label) {
      button.setAttribute('aria-label', shown ? `${label}: ${shown}` : label);
    }
    for (const name of select.classList) {
      if (name !== 'sel-native') {
        button.classList.add(name);
      }
    }
  }

  button.addEventListener('click', () => {
    if (open?.select === select) {
      close();
    } else {
      show(select);
    }
  });
  button.addEventListener('keydown', (event) => {
    const shown = open?.select === select;
    if (event.key === 'Escape' && shown) {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === 'Tab' && shown) {
      close();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (shown) {
        open.mark(open.active + (event.key === 'ArrowDown' ? 1 : -1));
      } else {
        show(select);
      }
    } else if (event.key === 'Home' || event.key === 'End') {
      if (shown) {
        event.preventDefault();
        open.mark(event.key === 'Home' ? 0 : open.options.length - 1);
      }
    } else if (event.key === 'Enter' || event.key === ' ') {
      if (shown) {
        event.preventDefault();
        if (open.options[open.active]) {
          choose(select, open.options[open.active]);
        }
        close(true);
      }
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      typed(select, state, event.key);
    }
  });
  select.addEventListener('focus', () => button.focus());
  return { button, sync };
}

function many(select) {
  const list = h('div', { class: 'sel-list', role: 'listbox', 'aria-multiselectable': 'true', 'aria-label': nameOf(select) || null });

  function sync() {
    list.hidden = select.hidden;
    list.replaceChildren(...[...select.options].filter((option) => !option.hidden).map((option) => {
      const row = h('div', {
        class: 'sel-option', role: 'option', tabindex: select.disabled || option.disabled ? null : '0',
        'aria-selected': option.selected ? 'true' : 'false', 'aria-disabled': select.disabled || option.disabled ? 'true' : null,
      }, h('span', { class: 'sel-box' }, icon('check')), h('span', { text: option.textContent }));
      const flip = () => {
        if (select.disabled || option.disabled) {
          return;
        }
        option.selected = !option.selected;
        row.setAttribute('aria-selected', option.selected ? 'true' : 'false');
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
      };
      row.addEventListener('click', flip);
      row.addEventListener('keydown', (event) => {
        if (event.key === ' ' || event.key === 'Enter') {
          event.preventDefault();
          flip();
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          (event.key === 'ArrowDown' ? row.nextElementSibling : row.previousElementSibling)?.focus();
        }
      });
      return row;
    }));
  }

  return { button: list, sync };
}

export function enhance(select) {
  if (!(select instanceof HTMLSelectElement) || 'plain' in select.dataset) {
    return;
  }
  let part = parts.get(select);
  if (!part) {
    part = select.multiple ? many(select) : single(select);
    parts.set(select, part);
    select.classList.add('sel-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    let queued = false;
    const later = () => {
      if (!queued) {
        queued = true;
        queueMicrotask(() => {
          queued = false;
          part.sync();
        });
      }
    };
    Object.defineProperty(select, 'value', {
      configurable: true,
      get() {
        return VALUE.get.call(this);
      },
      set(value) {
        VALUE.set.call(this, value);
        later();
      },
    });
    Object.defineProperty(select, 'selectedIndex', {
      configurable: true,
      get() {
        return INDEX.get.call(this);
      },
      set(value) {
        INDEX.set.call(this, value);
        later();
      },
    });
    new MutationObserver(later).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'hidden', 'class', 'selected'] });
    select.addEventListener('change', later);
    select.form?.addEventListener('reset', () => setTimeout(later));
  }
  if (select.nextElementSibling !== part.button) {
    select.after(part.button);
  }
  part.sync();
}

export function watchSelects(root = document.body) {
  const scan = (node) => {
    if (node.nodeType !== 1) {
      return;
    }
    if (node.tagName === 'SELECT') {
      enhance(node);
    } else if (node.firstElementChild) {
      node.querySelectorAll('select').forEach(enhance);
    }
  };
  scan(root);
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        scan(node);
      }
    }
  }).observe(root, { childList: true, subtree: true });
}
