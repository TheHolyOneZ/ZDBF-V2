import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { stamp } from '../core/format.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session, subscribe } from '../core/store.js';
import { createDiff, createEditor, lineDiff } from '../ui/editor.js';
import { modal } from '../ui/modal.js';
import { empty, pill, segmented, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

function show(value) {
  if (value == null) {
    return 'not set';
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value) === '' ? 'empty' : String(value);
}

function label(key) {
  const last = key.split('.').pop().replace(/_/g, ' ');
  return last[0].toUpperCase() + last.slice(1);
}

function waiting(state, note) {
  if (state === 'awaiting_approval') {
    note.update('Waiting for the bot owner to approve in Discord');
  }
}

export default function configView(page, context) {
  const stops = [];
  let alive = true;
  let tab = context.params[0] === 'file' ? 'file' : 'settings';
  let data = null;
  let section = null;
  let filter = '';
  let editor = null;
  let draft = null;

  const content = h('div', { class: 'cfg-content' });
  const tabs = segmented([{ value: 'settings', label: 'Settings' }, { value: 'file', label: 'config.toml' }], tab, (value) => {
    if (tab === 'file' && editor) {
      draft = editor.text;
    }
    tab = value;
    replace(value === 'file' ? 'config/file' : 'config');
    render();
  }, 'Configuration view');
  page.append(
    h('header', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', { text: 'Configuration' }),
        h('p', { text: 'Every change is checked by the bot before it is used. Some settings need a restart.' })),
      h('div', { class: 'page-actions' }, tabs.el)),
    content);

  function writeReason() {
    if (!can('config')) {
      return 'Your role can only read the configuration.';
    }
    if (!botAllows('config')) {
      return 'Changing the configuration is switched off on the bot.';
    }
    if (!session.bot.online) {
      return 'The bot is offline.';
    }
    return '';
  }

  function restartNote(keys) {
    return keys.length ? ` ${keys.join(', ')} ${keys.length === 1 ? 'needs' : 'need'} a restart of the bot to take effect.` : '';
  }

  function control(field) {
    const value = field.value;
    let input;
    let read;
    if (field.kind === 'bool') {
      input = h('select', null, h('option', { value: 'true', text: 'Yes', selected: value === true || null }), h('option', { value: 'false', text: 'No', selected: value === false || null }));
      read = () => input.value === 'true';
    } else if (field.kind === 'choice') {
      input = h('select', null, field.choices.map((c) => h('option', { value: c, text: c, selected: String(value) === c || null })));
      read = () => input.value;
    } else if (field.kind === 'int' || field.kind === 'float') {
      input = h('input', { type: 'number', step: field.kind === 'int' ? '1' : 'any', min: field.min ?? null, max: field.max ?? null,
        value: value ?? '', placeholder: field.optional ? 'not set' : null });
      read = () => {
        if (input.value === '' && field.optional) {
          return null;
        }
        const n = Number(input.value);
        if (input.value === '' || Number.isNaN(n) || (field.kind === 'int' && !Number.isInteger(n))) {
          throw new Error(field.kind === 'int' ? 'Enter a whole number.' : 'Enter a number.');
        }
        return n;
      };
    } else if (field.kind === 'multi') {
      const boxes = field.choices.map((c) => h('input', { type: 'checkbox', value: c, checked: (value || []).includes(c) || null }));
      input = h('div', { class: 'cfg-multi' }, boxes.map((b) => h('label', { class: 'check' }, b, h('span', { text: b.value }))));
      read = () => boxes.filter((b) => b.checked).map((b) => b.value);
    } else if (field.kind === 'list') {
      input = h('textarea', { rows: '3', placeholder: 'One per line' });
      input.value = (value || []).join('\n');
      read = () => {
        const items = input.value.split('\n').map((s) => s.trim()).filter(Boolean);
        if (field.item === 'int') {
          if (items.some((s) => !/^-?\d+$/.test(s))) {
            throw new Error('Every line has to be a whole number.');
          }
          return items.map((s) => Number(s));
        }
        return items;
      };
    } else if (field.kind === 'json') {
      input = h('textarea', { rows: '4', class: 'mono', spellcheck: 'false' });
      input.value = JSON.stringify(value, null, 2);
      read = () => {
        try {
          return JSON.parse(input.value);
        } catch (error) {
          throw new Error('This has to be valid JSON.');
        }
      };
    } else {
      input = h('input', { type: 'text', value: value ?? '', autocomplete: 'off', placeholder: field.optional ? 'not set' : null });
      read = () => (input.value === '' && field.optional ? null : input.value);
    }
    return { input, read };
  }

  function fieldRow(field, reason) {
    const { input, read } = control(field);
    const blocked = field.protected;
    const saveBtn = button('Apply', { class: 'btn btn-sm btn-primary', hidden: true }, 'check');
    const resetBtn = field.override ? button('Use config.toml', { class: 'btn btn-sm', title: 'Remove the runtime override' }, 'undo') : null;
    const error = h('small', { class: 'cfg-error', hidden: true });
    if (blocked || reason) {
      for (const el of [input, ...input.querySelectorAll?.('input') || []]) {
        el.disabled = true;
      }
    }
    const changed = () => {
      try {
        saveBtn.hidden = JSON.stringify(read()) === JSON.stringify(field.value);
        error.hidden = true;
      } catch (problem) {
        saveBtn.hidden = false;
      }
    };
    input.addEventListener('input', changed);
    input.addEventListener('change', changed);
    async function apply(args, what) {
      saveBtn.disabled = true;
      if (resetBtn) {
        resetBtn.disabled = true;
      }
      const note = toast(`${what} ${field.key}`, { timeout: 0 });
      try {
        const result = await run('config.set', args, { onStatus: (s) => waiting(s, note) });
        note.close();
        field.value = result.value;
        field.override = result.override;
        toast(`${field.key} is now ${show(result.value)}.${result.restart ? ' Restart the bot for it to take effect.' : ''}`, { kind: 'ok' });
        render();
      } catch (problem) {
        note.close();
        error.textContent = problem.message;
        error.hidden = false;
        saveBtn.disabled = false;
        if (resetBtn) {
          resetBtn.disabled = false;
        }
      }
    }
    saveBtn.addEventListener('click', () => {
      let value;
      try {
        value = read();
      } catch (problem) {
        error.textContent = problem.message;
        error.hidden = false;
        return;
      }
      apply({ key: field.key, value }, 'Saving');
    });
    resetBtn?.addEventListener('click', () => apply({ key: field.key, unset: true }, 'Resetting'));
    if (reason || blocked) {
      saveBtn.remove();
      resetBtn?.setAttribute('disabled', '');
    }
    return h('div', { class: 'cfg-field', dataset: { kind: field.kind } },
      h('div', { class: 'cfg-label' },
        h('strong', { text: label(field.key) }),
        h('code', { text: field.key }),
        field.override ? pill('Runtime override', 'info') : null,
        blocked ? pill('Bot only', 'warn') : null,
        data.restart.some((r) => field.key === r || field.key.startsWith(`${r}.`)) ? pill('Restart') : null),
      field.note ? h('p', { class: 'cfg-note', text: field.note }) : null,
      h('div', { class: 'cfg-input' }, input, saveBtn, resetBtn),
      blocked ? h('small', { class: 'muted', text: 'Only the bot owner can change this, on the bot machine or with /dashboard capabilities.' })
        : h('small', { class: 'muted', text: `Default: ${show(field.default)}` }),
      error);
  }

  function renderSettings() {
    const reason = writeReason();
    const q = filter.trim().toLowerCase();
    const sections = data.sections.map((s) => ({ ...s, fields: s.fields.filter((f) => !q || f.key.includes(q) || (f.note || '').toLowerCase().includes(q)) }))
      .filter((s) => s.fields.length);
    if (!section || !sections.some((s) => s.name === section)) {
      section = sections[0]?.name || null;
    }
    const search = h('input', { type: 'search', class: 'tree-search', placeholder: 'Find a setting', value: filter, 'aria-label': 'Find a setting' });
    search.addEventListener('input', () => {
      filter = search.value;
      const pos = search.selectionStart;
      render();
      const again = content.querySelector('.tree-search');
      again.focus();
      again.setSelectionRange(pos, pos);
    });
    const current = sections.find((s) => s.name === section);
    return h('div', { class: 'cfg' },
      h('aside', { class: 'cfg-nav card' }, h('div', { class: 'tree-head' }, search),
        h('nav', { class: 'cfg-sections' }, sections.map((s) => h('button', {
          type: 'button', class: 'cfg-section', 'aria-current': s.name === section ? 'true' : null,
          onClick: () => { section = s.name; render(); },
        }, h('span', { text: `[${s.name}]` }), h('small', { text: String(s.fields.length) }))))),
      h('section', { class: 'cfg-main card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: current ? `[${current.name}]` : 'No setting matches' }),
          h('p', { text: 'Changes here are runtime overrides: they apply at once and stay in data/config_overrides.json on top of config.toml.' }))),
        reason ? h('p', { class: 'note cfg-reason', dataset: { kind: 'warn' }, text: reason }) : null,
        h('div', { class: 'card-body cfg-fields' }, current ? current.fields.map((f) => fieldRow(f, reason)) : null)));
  }

  async function check(text) {
    return run('config.validate', { text });
  }

  function verdict(result) {
    if (result.errors.length) {
      return h('div', { class: 'note', dataset: { kind: 'bad' } }, h('strong', { text: 'The bot cannot use this file.' }), h('pre', { text: result.errors.join('\n') }));
    }
    if (result.protected.length) {
      return h('p', { class: 'note', dataset: { kind: 'bad' }, text: `The dashboard cannot change ${result.protected.join(', ')}. Undo those lines to save.` });
    }
    return h('p', { class: 'note', dataset: { kind: 'ok' } },
      result.changes.length ? `Valid. Changes: ${result.changes.slice(0, 12).join(', ')}${result.changes.length > 12 ? ` and ${result.changes.length - 12} more` : ''}.` : 'Valid. Nothing changed yet.',
      restartNote(result.restart));
  }

  async function saveFile(output) {
    const reason = writeReason();
    if (reason) {
      toast(reason, { kind: 'warn' });
      return;
    }
    const text = editor.text;
    let result;
    try {
      result = await check(text);
    } catch (error) {
      failure(error, 'The file could not be checked');
      return;
    }
    mount(output, verdict(result));
    if (result.errors.length || result.protected.length || !result.changes.length) {
      return;
    }
    const host = h('div', { class: 'diff-host' });
    let diff = null;
    const counts = lineDiff(data.text, text);
    const dialog = modal({
      title: 'Save config.toml',
      wide: true,
      body: [h('p', { class: 'modal-text', text: `${counts.added} line${counts.added === 1 ? '' : 's'} added or changed, ${counts.removed} removed. The bot keeps the old file as a last good copy.${restartNote(result.restart)}` }), host],
      actions: [{ label: 'Keep editing', value: null }, {
        label: 'Save', primary: true, submit: true,
        run: async () => {
          const note = toast('Saving config.toml', { timeout: 0 });
          try {
            const saved = await run('config.write', { text, expect: data.sha256 }, { onStatus: (s) => waiting(s, note) });
            note.close();
            return saved;
          } catch (error) {
            note.close();
            throw error;
          }
        },
      }],
    });
    createDiff(host, data.text, text, { language: 'toml' }).then((made) => { diff = made; }).catch(() => null);
    const saved = await dialog.done;
    diff?.destroy();
    if (saved && alive) {
      toast(`config.toml saved and loaded by the bot.${restartNote(saved.restart)}`, { kind: 'ok' });
      draft = null;
      await load();
    }
  }

  async function openHistory() {
    const box = h('div', { class: 'trash-list' }, data.history.length ? data.history.map((entry) => h('div', { class: 'trash-row' },
      icon('file'), h('div', { class: 'trash-text' }, h('strong', { text: entry.name }), h('small', { text: `Saved ${stamp(entry.at)}` })),
      button('Open in the editor', {
        class: 'btn btn-sm',
        onClick: async () => {
          try {
            const copy = await run('config.backup', { name: entry.name });
            editor?.setText(copy.text);
            dialog.close();
            toast('The old copy is in the editor. Check and save it to use it again.');
          } catch (error) {
            failure(error);
          }
        },
      }, 'undo'))) : h('p', { class: 'muted', text: 'No copies yet. The bot keeps the last 10 versions each time the file is saved from here.' }));
    const dialog = modal({ title: 'Last good copies', wide: true, body: box });
    await dialog.done;
  }

  function renderFile() {
    const reason = writeReason();
    const host = h('div', { class: 'cfg-code' });
    const output = h('div', { class: 'cfg-output' });
    const checkBtn = button('Check', { class: 'btn btn-sm' }, 'check');
    const saveBtn = button('Save', { class: 'btn btn-sm btn-primary', disabled: reason ? true : null, title: reason || 'Save (Ctrl+S)' }, 'save');
    checkBtn.addEventListener('click', async () => {
      try {
        mount(output, verdict(await check(editor.text)));
      } catch (error) {
        failure(error, 'The file could not be checked');
      }
    });
    saveBtn.addEventListener('click', () => saveFile(output));
    const node = h('section', { class: 'card cfg-file' },
      h('header', { class: 'fedit-head' },
        h('div', { class: 'fedit-title' }, h('h2', null, h('span', { text: data.path }))),
        h('div', { class: 'fedit-actions' },
          h('button', { type: 'button', class: 'icon-btn', title: 'Search (Ctrl+F)', 'aria-label': 'Search', onClick: () => editor?.search() }, icon('search')),
          button('Last good copies', { class: 'btn btn-sm', onClick: () => openHistory() }, 'undo'),
          checkBtn, saveBtn)),
      reason ? h('p', { class: 'note cfg-reason', dataset: { kind: 'warn' }, text: reason }) : null,
      h('p', { class: 'muted cfg-protected', text: `The dashboard can never change ${data.protected.join(', ')}. Secrets such as the token live in .env, which the dashboard cannot open.` }),
      host, output);
    editor?.destroy();
    editor = null;
    createEditor(host, { doc: draft ?? data.text, language: 'toml', label: 'config.toml', onSave: () => saveFile(output) })
      .then((made) => {
        if (!alive || !host.isConnected) {
          made.destroy();
          return;
        }
        editor = made;
      }).catch(() => mount(host, empty('alert', 'The editor could not start', 'Reload the page and try again.')));
    return node;
  }

  function render() {
    if (!data) {
      mount(content, h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(8))));
      return;
    }
    if (tab !== 'file' && editor) {
      draft = editor.text;
      editor.destroy();
      editor = null;
    }
    mount(content, tab === 'file' ? renderFile() : renderSettings());
  }

  async function load() {
    try {
      data = await run('config.read');
    } catch (error) {
      if (alive) {
        mount(content, h('section', { class: 'card' }, empty('alert', 'The configuration could not be loaded', error.message)));
      }
      return;
    }
    if (alive) {
      render();
    }
  }

  stops.push(on('bot', () => { if (tab === 'settings') { render(); } }));
  stops.push(subscribe('meta', () => { if (tab === 'settings' && data) { render(); } }));
  render();
  load();

  return {
    update(params) {
      const next = params[0] === 'file' ? 'file' : 'settings';
      if (next !== tab) {
        tabs.select(next);
      }
    },
    destroy() {
      alive = false;
      editor?.destroy();
      stops.forEach((stop) => stop());
    },
  };
}
