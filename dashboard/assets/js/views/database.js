import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { bytes, num } from '../core/format.js';
import { replace } from '../core/router.js';
import { empty, skeleton } from '../ui/parts.js';

const PAGE = 50;

export default function databaseView(page, context) {
  let alive = true;
  let tables = null;
  let selected = context.params[0] || null;
  let offset = 0;
  let search = '';
  let order = '';
  let desc = true;

  const nav = h('nav', { class: 'cfg-sections' }, skeleton(6));
  const main = h('section', { class: 'cfg-main card db-main' }, empty('table', 'Pick a table', 'The browser is read-only. Columns that look like secrets are hidden.'));
  const info = h('p', { class: 'muted db-info' });
  page.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Database' }),
      h('p', { text: 'Read the bot database. Nothing can be changed from here.' }))),
    h('div', { class: 'cfg' }, h('aside', { class: 'cfg-nav card' }, info, nav), main));

  function renderNav() {
    mount(nav, tables.map((t) => h('button', {
      type: 'button', class: 'cfg-section', 'aria-current': t.name === selected ? 'true' : null,
      onClick: () => { selected = t.name; offset = 0; search = ''; order = ''; desc = true; replace(`database/${t.name}`); renderNav(); loadRows(); },
    }, h('span', { text: t.name }), h('small', { text: num(t.rows) }))));
  }

  async function loadRows() {
    const wanted = selected;
    mount(main, h('div', { class: 'card-body' }, skeleton(8)));
    let data;
    try {
      data = await run('database.rows', { table: wanted, offset, limit: PAGE, search, order, desc });
    } catch (error) {
      mount(main, empty('alert', 'The table could not be read', error.message));
      return;
    }
    if (!alive || wanted !== selected) {
      return;
    }
    order = data.order;
    const find = h('input', { type: 'search', class: 'log-search', placeholder: 'Find in this table', value: search, 'aria-label': 'Find in this table' });
    find.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        search = find.value.trim();
        offset = 0;
        loadRows();
      }
    });
    const sortBy = (column) => {
      if (order === column) {
        desc = !desc;
      } else {
        order = column;
        desc = true;
      }
      offset = 0;
      loadRows();
    };
    const head = h('tr', null, data.columns.map((c) => h('th', { scope: 'col' },
      h('button', { type: 'button', class: 'th-sort', onClick: () => sortBy(c) }, c, c === order ? icon(desc ? 'down' : 'right', desc ? '' : 'up') : null))));
    const rows = data.rows.map((r) => h('tr', null, r.map((v, i) => h('td', { dataset: { label: data.columns[i] }, class: v == null ? 'db-null' : null, title: typeof v === 'string' && v.length > 60 ? v : null },
      v == null ? 'NULL' : typeof v === 'string' && v.length > 120 ? `${v.slice(0, 120)}…` : String(v)))));
    const last = Math.min(data.offset + data.limit, data.total);
    mount(main,
      h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: data.table }),
        h('p', { text: data.total ? `Rows ${num(data.offset + 1)} to ${num(last)} of ${num(data.total)}${search ? ` matching "${search}"` : ''}` : 'No rows' })),
      h('div', { class: 'card-tools' }, find)),
      data.rows.length ? h('div', { class: 'table-wrap db-table' }, h('table', { class: 'table' }, h('thead', null, head), h('tbody', null, rows)))
        : h('div', { class: 'card-body' }, h('p', { class: 'muted', text: search ? 'Nothing matches.' : 'This table is empty.' })),
      h('div', { class: 'card-foot db-pager' },
        button('Previous', { class: 'btn btn-sm', disabled: data.offset === 0 ? true : null, onClick: () => { offset = Math.max(0, offset - PAGE); loadRows(); } }, 'left'),
        button('Next', { class: 'btn btn-sm', disabled: last >= data.total ? true : null, onClick: () => { offset += PAGE; loadRows(); } }, 'right')));
  }

  async function load() {
    try {
      const data = await run('database.tables');
      tables = data.tables;
      info.textContent = `${data.file}, ${bytes(data.size)}`;
    } catch (error) {
      if (alive) {
        mount(nav, h('p', { class: 'muted', text: error.message }));
        mount(main, empty('alert', 'The database could not be opened', error.message));
      }
      return;
    }
    if (!alive) {
      return;
    }
    renderNav();
    if (selected && tables.some((t) => t.name === selected)) {
      loadRows();
    }
  }

  load();
  return {
    update(params) {
      if (params[0] && params[0] !== selected) {
        selected = params[0];
        offset = 0;
        renderNav();
        loadRows();
      }
    },
    destroy() {
      alive = false;
    },
  };
}
