import { run } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { num } from '../core/format.js';
import { replace } from '../core/router.js';
import { subscribe, topic } from '../core/store.js';
import { confirm } from '../ui/modal.js';
import { empty, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';
import { approvalToast } from './servers.js';

function value(v) {
  if (v === null || v === undefined) {
    return '-';
  }
  if (typeof v === 'boolean') {
    return v ? 'yes' : 'no';
  }
  if (typeof v === 'number') {
    return num(v);
  }
  return String(v);
}

export default function panelsView(page, context) {
  let alive = true;
  const stops = [];
  let selected = context.params[0] || null;
  const nav = h('nav', { class: 'cfg-sections' });
  const main = h('div', { class: 'panel-main' });
  page.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Panels' }),
      h('p', { text: 'Pages that extensions add to the dashboard.' }))),
    h('div', { class: 'cfg' }, h('aside', { class: 'cfg-nav card' }, nav), main));

  function list() {
    return topic('meta')?.panels || [];
  }

  function renderNav() {
    const panels = list();
    mount(nav, panels.length ? panels.map((p) => h('button', {
      type: 'button', class: 'cfg-section panel-nav', 'aria-current': p.id === selected ? 'true' : null,
      onClick: () => { selected = p.id; replace(`panels/${p.id}`); renderNav(); load(); },
    }, h('span', { text: p.title }))) : h('p', { class: 'muted tree-empty', text: 'No extension has a panel.' }));
    if (!selected && panels.length) {
      selected = panels[0].id;
      renderNav();
      load();
    } else if (!panels.length) {
      mount(main, h('section', { class: 'card' }, empty('panel', 'No panels yet', 'Extensions can add panels with stats, tables, forms and buttons. See docs/dev/dashboard-panels.md.')));
    }
  }

  async function act(action, args, label) {
    const t = approvalToast(label);
    try {
      const result = await run(`panel.${selected}.${action}`, args, { onStatus: t.onStatus });
      if (result.message) {
        toast(result.message, { kind: 'ok' });
      }
      render({ blocks: result.blocks });
    } catch (error) {
      failure(error);
    } finally {
      t.note.close();
    }
  }

  function block(b) {
    const title = b.title ? h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: b.title }))) : null;
    if (b.type === 'stats') {
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body ext-stats panel-stats' },
        b.items.map((i) => h('div', { title: i.hint || null }, h('strong', { text: value(i.value) }), h('span', { text: i.label })))));
    }
    if (b.type === 'table') {
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body' }, h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, b.columns.map((c) => h('th', { scope: 'col', text: c })))),
        h('tbody', null, b.rows.map((r) => h('tr', null, r.map((v, i) => h('td', { dataset: { label: b.columns[i] }, text: value(v) })))))))));
    }
    if (b.type === 'text') {
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body' }, h('p', { class: 'panel-text', text: b.text })));
    }
    if (b.type === 'list') {
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body' }, h('ul', { class: 'panel-list' }, b.items.map((i) => h('li', { text: i })))));
    }
    if (b.type === 'form') {
      const allowed = Boolean(b.action);
      const form = h('form', { class: 'form-grid' }, b.fields.map((f) => {
        if (f.kind === 'bool') {
          return h('label', { class: 'check span-all' }, h('input', { type: 'checkbox', name: f.key, checked: f.value ? true : null }), h('span', { text: f.label }));
        }
        const input = f.kind === 'choice'
          ? h('select', { name: f.key }, f.choices.map((c) => h('option', { value: c, text: c, selected: String(f.value) === c || null })))
          : f.kind === 'textarea' ? h('textarea', { name: f.key, rows: '3', required: f.required || null })
            : h('input', { name: f.key, type: f.kind === 'number' ? 'number' : 'text', step: 'any', value: f.value ?? '', required: f.required || null });
        if (f.kind === 'textarea') {
          input.value = f.value ?? '';
        }
        return h('label', { class: `field ${f.kind === 'textarea' ? 'span-all' : ''}`.trim() }, h('span', { text: f.label }), input);
      }), h('div', { class: 'span-all' }, button(b.submit, { class: 'btn btn-primary', type: 'submit', disabled: allowed ? null : true })));
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        const out = {};
        for (const f of b.fields) {
          const el = form.elements[f.key];
          out[f.key] = f.kind === 'bool' ? el.checked : f.kind === 'number' ? (el.value === '' ? null : Number(el.value)) : el.value;
        }
        act(b.action, out, b.submit);
      });
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body' }, form));
    }
    if (b.type === 'buttons') {
      return h('section', { class: 'card' }, title, h('div', { class: 'card-body panel-buttons' }, b.buttons.map((x) => button(x.label, {
        class: `btn ${x.style === 'primary' ? 'btn-primary' : x.style === 'danger' ? 'btn-danger' : ''}`.trim(),
        onClick: async () => {
          if (x.confirm && !await confirm(x.label, x.confirm, { label: x.label, danger: x.style === 'danger' })) {
            return;
          }
          act(x.action, {}, x.label);
        },
      }))));
    }
    return null;
  }

  function render(data) {
    const meta = list().find((p) => p.id === selected);
    mount(main,
      meta ? h('p', { class: 'muted panel-desc', text: meta.description || `From ${meta.module}` }) : null,
      data.blocks.length ? data.blocks.map(block) : h('section', { class: 'card' }, empty('panel', 'Nothing to show', 'The panel returned no content.')));
  }

  async function load() {
    if (!selected) {
      return;
    }
    const wanted = selected;
    mount(main, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6))));
    try {
      const data = await run(`panel.${wanted}`);
      if (alive && wanted === selected) {
        render(data);
      }
    } catch (error) {
      if (alive && wanted === selected) {
        mount(main, h('section', { class: 'card' }, empty('alert', 'The panel could not be loaded', error.message)));
      }
    }
  }

  stops.push(subscribe('meta', () => renderNav()));
  if (selected) {
    load();
  }

  return {
    update(params) {
      if (params[0] && params[0] !== selected) {
        selected = params[0];
        renderNav();
        load();
      }
    },
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}

