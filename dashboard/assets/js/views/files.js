import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { bytes, stamp } from '../core/format.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session, subscribe } from '../core/store.js';
import { createDiff, createEditor, LANGUAGE_LABELS, languageOf, lineDiff } from '../ui/editor.js';
import { confirm, field, modal } from '../ui/modal.js';
import { empty, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

const drafts = new Map();
const IMAGES = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml', ico: 'image/x-icon' };
const INLINE = 700 * 1024;

function recall(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch (error) {
    return fallback;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    return false;
  }
  return true;
}

export function toBase64(data) {
  let text = '';
  for (let i = 0; i < data.length; i += 0x8000) {
    text += String.fromCharCode.apply(null, data.subarray(i, i + 0x8000));
  }
  return btoa(text);
}

export function fromBase64(text) {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) {
    out[i] = raw.charCodeAt(i);
  }
  return out;
}

function decodeText(data) {
  if (data.subarray(0, 8000).includes(0)) {
    return null;
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(data);
  } catch (error) {
    return null;
  }
}

function extOf(name) {
  const lower = name.toLowerCase();
  return lower.includes('.') ? lower.split('.').pop() : '';
}

function parentOf(path) {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
}

function nameOf(path) {
  return path.split('/').pop();
}

function randomId() {
  const data = new Uint8Array(16);
  crypto.getRandomValues(data);
  return [...data].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function fetchFile(path, onProgress) {
  const parts = [];
  let offset = 0;
  let first = null;
  for (;;) {
    const chunk = await run('files.read', { path, offset });
    if (!first) {
      first = chunk;
    } else if (chunk.version !== first.version) {
      throw new Error('The file changed while it was loading. Open it again.');
    }
    const data = fromBase64(chunk.data);
    parts.push(data);
    offset += data.length;
    onProgress?.(offset, chunk.size);
    if (chunk.eof || !data.length) {
      break;
    }
  }
  const all = new Uint8Array(offset);
  let at = 0;
  for (const part of parts) {
    all.set(part, at);
    at += part.length;
  }
  return { ...first, bytes: all };
}

function saveBlob(name, data, type = 'application/octet-stream') {
  const link = h('a', { download: name, href: URL.createObjectURL(new Blob([data], { type })) });
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 1000);
}

export default function filesView(page, context) {
  const stops = [];
  let alive = true;
  let info = null;
  const listings = new Map();
  const expanded = new Set(recall('zdbf-files-open', []));
  let selected = context.params[0] || recall('zdbf-files-selected', '') || '';
  let current = null;
  let editor = null;
  let reloadAfter = recall('zdbf-files-reload', true);
  let wrap = recall('zdbf-files-wrap', false);
  let busy = false;

  const treeBody = h('div', { class: 'ftree-body' }, skeleton(8));
  const tools = h('div', { class: 'ftree-tools' });
  const treePane = h('aside', { class: 'ftree card' }, tools, treeBody);
  const head = h('header', { class: 'fedit-head' });
  const body = h('div', { class: 'fedit-body' });
  const status = h('footer', { class: 'fedit-status' });
  const editPane = h('section', { class: 'fedit card' }, head, body, status);
  const root = h('div', { class: 'files', dataset: { pane: selected ? 'detail' : 'list' } }, treePane, editPane);
  page.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Files' }),
      h('p', { text: 'Read and edit the files in the folders the bot allows, with a copy of every change kept in the trash.' }))),
    root);

  function writable() {
    if (!can('files.write')) {
      return 'Your role can only read files.';
    }
    if (!botAllows('files.write')) {
      return 'Changing files is switched off on the bot. The bot owner can enable "files.write" with /dashboard capabilities.';
    }
    if (!session.bot.online) {
      return 'The bot is offline.';
    }
    return '';
  }

  function dirty() {
    return Boolean(current?.text != null && editor && editor.text !== current.text);
  }

  function stashDraft() {
    if (current && editor) {
      if (dirty()) {
        drafts.set(current.path, { text: editor.text, base: current.sha256 });
      } else {
        drafts.delete(current.path);
      }
    }
  }

  async function list(path, force = false) {
    if (!force && listings.has(path)) {
      return listings.get(path);
    }
    const data = await run('files.list', { path });
    listings.set(path, data);
    return data;
  }

  function folderOf(path) {
    if (!path) {
      return info?.roots.find((r) => r.ok)?.path || '';
    }
    for (const [, data] of listings) {
      const item = data.items.find((i) => i.path === path);
      if (item) {
        return item.dir ? item.path : parentOf(item.path);
      }
    }
    return info?.roots.some((r) => r.path === path) ? path : parentOf(path);
  }

  function isFolder(path) {
    if (info?.roots.some((r) => r.path === path)) {
      return true;
    }
    for (const [, data] of listings) {
      const item = data.items.find((i) => i.path === path);
      if (item) {
        return item.dir;
      }
    }
    return false;
  }

  function row(item, depth) {
    const open = item.dir && expanded.has(item.path);
    const node = h('button', {
      type: 'button', class: 'ftree-row', 'aria-current': item.path === selected ? 'true' : null,
      'aria-expanded': item.dir ? String(open) : null, vars: { '--depth': String(depth) }, title: item.path,
      onClick: () => (item.dir ? toggle(item.path) : openFile(item.path)),
    },
    item.dir ? icon('right', `ftree-caret ${open ? 'open' : ''}`) : h('span', { class: 'ftree-caret-space' }),
    icon(item.dir ? (open ? 'folderOpen' : 'folder') : 'file', item.dir ? 'ftree-folder' : ''),
    h('span', { class: 'ftree-name', text: item.name }),
    drafts.has(item.path) ? h('span', { class: 'ftree-dot', title: 'Unsaved changes' }) : null,
    !item.dir ? h('small', { class: 'ftree-size', text: bytes(item.size) }) : null);
    const out = [node];
    if (open) {
      const data = listings.get(item.path);
      if (!data) {
        out.push(h('p', { class: 'ftree-note muted', vars: { '--depth': String(depth + 1) }, text: 'Loading' }));
      } else if (!data.items.length) {
        out.push(h('p', { class: 'ftree-note muted', vars: { '--depth': String(depth + 1) }, text: 'Empty folder' }));
      } else {
        for (const child of data.items) {
          out.push(...row(child, depth + 1));
        }
        if (data.cut) {
          out.push(h('p', { class: 'ftree-note muted', vars: { '--depth': String(depth + 1) }, text: 'Only the first 2000 entries are shown.' }));
        }
      }
    }
    return out;
  }

  function renderTree() {
    if (!info) {
      return;
    }
    const nodes = [];
    for (const rootInfo of info.roots) {
      if (!rootInfo.ok) {
        nodes.push(h('p', { class: 'ftree-note muted', text: `${rootInfo.path}: ${rootInfo.error}` }));
        continue;
      }
      nodes.push(...row({ name: rootInfo.path, path: rootInfo.path, dir: true }, 0));
    }
    mount(treeBody, nodes.length ? nodes : h('p', { class: 'ftree-note muted', text: 'The bot allows no folders.' }));
  }

  function renderTools() {
    const reason = writable();
    const folderSelected = isFolder(selected);
    const isRoot = info?.roots.some((r) => r.path === selected);
    const make = (label, iconName, handler, disabled = false) => h('button', {
      type: 'button', class: 'icon-btn', title: label, 'aria-label': label, disabled: disabled || null, onClick: handler,
    }, icon(iconName));
    mount(tools,
      make('New file', 'plus', () => createFile(), Boolean(reason)),
      make('New folder', 'folder', () => createFolder(), Boolean(reason)),
      make('Upload files', 'upload', () => pickUpload(), Boolean(reason)),
      h('span', { class: 'ftree-sep' }),
      make(folderSelected ? 'Rename folder' : 'Rename file', 'edit', () => renameSelected(), Boolean(reason) || !selected || isRoot),
      make(folderSelected ? 'Delete folder' : 'Delete file', 'trash', () => deleteSelected(), Boolean(reason) || !selected || isRoot),
      h('span', { class: 'ftree-grow' }),
      make('Download the folder as a zip', 'download', () => downloadFolder()),
      make('Trash', 'undo', () => openTrash()),
      make('Refresh', 'refresh', () => refreshTree()));
  }

  async function toggle(path) {
    selected = path;
    remember('zdbf-files-selected', selected);
    if (expanded.has(path)) {
      expanded.delete(path);
    } else {
      expanded.add(path);
      renderTree();
      try {
        await list(path);
      } catch (error) {
        expanded.delete(path);
        failure(error, 'Could not open the folder');
      }
    }
    remember('zdbf-files-open', [...expanded]);
    renderTree();
    renderTools();
  }

  async function refreshTree() {
    const paths = [...expanded];
    listings.clear();
    try {
      await Promise.all(paths.map((p) => list(p, true).catch(() => expanded.delete(p))));
    } finally {
      renderTree();
      renderTools();
    }
  }

  async function revealParents(path) {
    const parts = path.split('/');
    for (let i = 1; i < parts.length; i++) {
      const folder = parts.slice(0, i).join('/');
      if (info.roots.some((r) => folder === r.path || folder.startsWith(`${r.path}/`))) {
        expanded.add(folder);
        await list(folder).catch(() => null);
      }
    }
    remember('zdbf-files-open', [...expanded]);
  }

  function setStatus(line = 1, col = 1) {
    if (!current) {
      mount(status);
      return;
    }
    const lang = current.language ? LANGUAGE_LABELS[current.language] : 'Plain text';
    mount(status,
      h('span', { text: current.text != null ? `Line ${line}, column ${col}` : '' }),
      h('span', { class: 'fedit-grow' }),
      h('span', { text: current.text != null ? lang : current.kind }),
      h('span', { text: bytes(current.size) }),
      h('span', { text: `Changed ${stamp(current.mtime)}` }));
  }

  function renderHead() {
    if (!current) {
      mount(head);
      return;
    }
    const reason = writable();
    const textual = current.text != null;
    const changed = dirty();
    const saveBtn = button('Save', { class: 'btn btn-primary btn-sm', disabled: !textual || !changed || reason ? true : null, title: reason || 'Save (Ctrl+S)' }, 'save');
    saveBtn.addEventListener('click', () => save());
    mount(head,
      h('button', { type: 'button', class: 'icon-btn files-back', 'aria-label': 'Back to the files', onClick: () => { root.dataset.pane = 'list'; } }, icon('left')),
      h('div', { class: 'fedit-title' },
        h('h2', null, h('span', { class: 'fedit-dir', text: `${parentOf(current.path)}/` }), h('span', { text: nameOf(current.path) }),
          changed ? h('span', { class: 'fedit-dirty', title: 'Unsaved changes', text: 'Unsaved' }) : null)),
      h('div', { class: 'fedit-actions' },
        textual ? h('label', { class: 'check fedit-reload', title: 'Reload the extension this file belongs to after saving' },
          h('input', { type: 'checkbox', checked: reloadAfter || null, onChange: (e) => { reloadAfter = e.target.checked; remember('zdbf-files-reload', reloadAfter); } }),
          h('span', { text: 'Reload after saving' })) : null,
        textual ? h('button', { type: 'button', class: 'icon-btn', title: 'Search (Ctrl+F)', 'aria-label': 'Search', onClick: () => editor?.search() }, icon('search')) : null,
        textual ? h('button', { type: 'button', class: 'icon-btn', title: wrap ? 'Do not wrap lines' : 'Wrap long lines', 'aria-label': 'Wrap lines', 'aria-pressed': String(wrap),
          onClick: () => { wrap = !wrap; remember('zdbf-files-wrap', wrap); editor?.setWrap(wrap); renderHead(); } }, icon('wrap')) : null,
        textual && changed ? h('button', { type: 'button', class: 'icon-btn', title: 'Discard changes', 'aria-label': 'Discard changes', onClick: () => discard() }, icon('undo')) : null,
        h('button', { type: 'button', class: 'icon-btn', title: 'Download', 'aria-label': 'Download', onClick: () => download(current.path) }, icon('download')),
        saveBtn));
  }

  function renderBody(text = null) {
    editor?.destroy();
    editor = null;
    if (!current) {
      mount(body, empty('file', 'Pick a file', 'Choose a file on the left to read or edit it.'));
      return;
    }
    if (current.text == null) {
      const ext = extOf(current.path);
      const preview = IMAGES[ext] && current.bytes
        ? h('img', { class: 'fedit-image', alt: nameOf(current.path), src: `data:${IMAGES[ext]};base64,${toBase64(current.bytes)}` })
        : null;
      mount(body, h('div', { class: 'fedit-binary' }, preview || h('span', { class: 'empty-icon' }, icon('file')),
        h('p', { text: preview ? `${current.kind}, ${bytes(current.size)}` : `This file is not text (${bytes(current.size)}). Download it to open it on your computer.` }),
        button('Download', { class: 'btn btn-sm', onClick: () => download(current.path) }, 'download')));
      return;
    }
    const host = h('div', { class: 'fedit-code' });
    mount(body, host);
    createEditor(host, {
      doc: text ?? current.text, language: current.language, wrap, label: current.path,
      onChange: () => { renderHead(); },
      onCursor: (line, col) => setStatus(line, col),
      onSave: () => save(),
    }).then((made) => {
      if (!alive || !host.isConnected) {
        made.destroy();
        return;
      }
      editor = made;
      renderHead();
    }).catch(() => {
      mount(body, empty('alert', 'The editor could not start', 'Reload the page and try again.'));
    });
  }

  async function openFile(path, { force = false } = {}) {
    if (!force && current && current.path === path) {
      root.dataset.pane = 'detail';
      return;
    }
    stashDraft();
    selected = path;
    remember('zdbf-files-selected', selected);
    replace(`files/${encodeURIComponent(path)}`);
    root.dataset.pane = 'detail';
    renderTree();
    renderTools();
    current = null;
    editor?.destroy();
    editor = null;
    mount(head, h('div', { class: 'fedit-title' }, h('h2', { text: path })));
    const progress = h('p', { class: 'muted', text: 'Loading' });
    mount(body, h('div', { class: 'fedit-loading' }, skeleton(10), progress));
    mount(status);
    try {
      const file = await fetchFile(path, (done, total) => {
        progress.textContent = total > 1024 * 1024 ? `Loading ${bytes(done)} of ${bytes(total)}` : 'Loading';
      });
      if (!alive || selected !== path) {
        return;
      }
      const text = decodeText(file.bytes);
      const ext = extOf(path);
      current = {
        path: file.path, size: file.size, mtime: file.mtime, sha256: file.sha256, text,
        bytes: text == null ? file.bytes : null, language: languageOf(path),
        kind: IMAGES[ext] ? `${ext.toUpperCase()} image` : 'Binary file',
      };
      const draft = drafts.get(path);
      renderHead();
      renderBody(draft && draft.base === file.sha256 ? draft.text : null);
      if (draft && draft.base !== file.sha256) {
        drafts.delete(path);
        toast('The file changed on the bot, so your unsaved changes from before were dropped.', { kind: 'warn' });
      }
      setStatus();
    } catch (error) {
      if (alive && selected === path) {
        mount(head, h('div', { class: 'fedit-title' }, h('h2', { text: path })));
        mount(body, empty('alert', 'The file could not be opened', error.message));
      }
    }
  }

  async function discard() {
    if (current && editor && await confirm('Discard changes', 'Your changes to this file will be lost.', { label: 'Discard', danger: true })) {
      editor.setText(current.text);
      drafts.delete(current.path);
      renderHead();
      renderTree();
    }
  }

  async function writeFile(path, data, extra = {}, onStatus = null) {
    if (data.length <= INLINE) {
      return run('files.write', { path, data: toBase64(data), size: data.length, ...extra }, { onStatus });
    }
    const upload = randomId();
    const chunk = info?.chunk || 768 * 1024;
    for (let offset = 0; offset < data.length; offset += chunk) {
      onStatus?.(`uploading ${Math.round((offset / data.length) * 100)}%`);
      await run('files.stage', { upload, total: data.length, offset, data: toBase64(data.subarray(offset, offset + chunk)) });
    }
    return run('files.write', { path, upload, size: data.length, ...extra }, { onStatus });
  }

  function statusText(state) {
    if (state === 'awaiting_approval') {
      return 'Waiting for the bot owner to approve in Discord';
    }
    if (String(state).startsWith('uploading')) {
      return `Uploading, ${state.split(' ')[1]}`;
    }
    return 'Saving';
  }

  async function save() {
    if (busy || !current || current.text == null || !editor || !dirty()) {
      return;
    }
    const reason = writable();
    if (reason) {
      toast(reason, { kind: 'warn' });
      return;
    }
    const text = editor.text;
    const counts = lineDiff(current.text, text);
    const diffHost = h('div', { class: 'diff-host' });
    let diff = null;
    const dialog = modal({
      title: `Save ${nameOf(current.path)}`,
      wide: true,
      body: [
        h('p', { class: 'modal-text' }, `${counts.added} line${counts.added === 1 ? '' : 's'} added or changed, ${counts.removed} removed. The old version is kept in the trash.`),
        diffHost,
        reloadAfter && current.language === 'python' ? h('p', { class: 'muted', text: 'If this file belongs to a loaded extension, the bot reloads it after saving.' }) : null,
      ],
      actions: [
        { label: 'Keep editing', value: false },
        {
          label: 'Save', primary: true, submit: true,
          run: async () => {
            busy = true;
            const note = toast('Saving', { kind: 'info', timeout: 0 });
            try {
              const result = await writeFile(current.path, new TextEncoder().encode(text),
                { expect: current.sha256, reload: reloadAfter }, (state) => note.update(statusText(state)));
              note.close();
              return result;
            } catch (error) {
              note.close();
              throw error;
            } finally {
              busy = false;
            }
          },
        },
      ],
    });
    createDiff(diffHost, current.text, text, { language: current.language }).then((made) => { diff = made; })
      .catch(() => mount(diffHost, h('p', { class: 'muted', text: 'The comparison could not be shown.' })));
    const result = await dialog.done;
    diff?.destroy();
    if (!result || result === false || !alive) {
      return;
    }
    if (current) {
      current.text = text;
      current.sha256 = result.sha256;
      current.size = result.size;
      current.mtime = result.mtime;
      drafts.delete(current.path);
      renderHead();
      setStatus();
      listings.delete(parentOf(current.path));
      refreshTree();
    }
    if (result.reload) {
      toast(result.reload.ok ? `Saved and reloaded ${result.reload.module} in ${Math.round(result.reload.ms)} ms.`
        : `Saved, but ${result.reload.module} did not reload: ${result.reload.error}`, { kind: result.reload.ok ? 'ok' : 'bad' });
    } else {
      toast('Saved.', { kind: 'ok' });
    }
  }

  async function download(path) {
    const note = toast(`Downloading ${nameOf(path)}`, { timeout: 0 });
    try {
      const file = current?.path === path && current.text != null && !dirty()
        ? { bytes: new TextEncoder().encode(current.text) }
        : await fetchFile(path, (done, total) => note.update(`Downloading ${nameOf(path)}, ${Math.round((done / Math.max(total, 1)) * 100)}%`));
      saveBlob(nameOf(path), file.bytes);
      note.close();
    } catch (error) {
      note.close();
      failure(error, 'Download failed');
    }
  }

  async function downloadFolder() {
    const folder = folderOf(selected);
    const note = toast(`Packing ${folder}`, { timeout: 0 });
    try {
      const made = await run('files.archive', { path: folder }, { timeout: 6 * 60 * 1000 });
      const parts = [];
      let offset = 0;
      for (;;) {
        const chunk = await run('files.archive_read', { id: made.id, offset });
        const data = fromBase64(chunk.data);
        parts.push(data);
        offset += data.length;
        note.update(`Downloading ${made.name}, ${Math.round((offset / Math.max(chunk.size, 1)) * 100)}%`);
        if (chunk.eof || !data.length) {
          break;
        }
      }
      saveBlob(made.name, new Blob(parts, { type: 'application/zip' }));
      note.close();
      toast(`${made.name}: ${made.files} files, ${bytes(made.size)}.`, { kind: 'ok' });
    } catch (error) {
      note.close();
      failure(error, 'The folder could not be downloaded');
    }
  }

  async function createFile() {
    const folder = folderOf(selected);
    const result = await modal({
      title: 'New file',
      body: [h('p', { class: 'modal-text', text: `In ${folder}/` }), field('Name', { name: 'name', required: true, maxlength: '200', placeholder: 'my_extension.py', autocomplete: 'off' })],
      actions: [{ label: 'Cancel', value: null }, {
        label: 'Create', primary: true, submit: true,
        run: (form) => run('files.write', { path: `${folder}/${String(form.get('name')).trim()}`, data: '', size: 0, create: true },
          { onStatus: () => null }),
      }],
    }).done;
    if (result) {
      listings.delete(folder);
      expanded.add(folder);
      await refreshTree();
      openFile(result.path);
    }
  }

  async function createFolder() {
    const folder = folderOf(selected);
    const result = await modal({
      title: 'New folder',
      body: [h('p', { class: 'modal-text', text: `In ${folder}/` }), field('Name', { name: 'name', required: true, maxlength: '200', autocomplete: 'off' })],
      actions: [{ label: 'Cancel', value: null }, {
        label: 'Create', primary: true, submit: true,
        run: (form) => run('files.mkdir', { path: folder, name: String(form.get('name')).trim() }),
      }],
    }).done;
    if (result) {
      expanded.add(folder);
      selected = result.path;
      await refreshTree();
    }
  }

  async function renameSelected() {
    const path = selected;
    const result = await modal({
      title: 'Rename',
      body: [field('New name', { name: 'name', required: true, maxlength: '200', value: nameOf(path), autocomplete: 'off' })],
      actions: [{ label: 'Cancel', value: null }, {
        label: 'Rename', primary: true, submit: true,
        run: (form) => run('files.rename', { path, name: String(form.get('name')).trim() }),
      }],
    }).done;
    if (result) {
      if (current?.path === path) {
        drafts.delete(path);
        current = null;
        await refreshTree();
        openFile(result.path, { force: true });
      } else {
        selected = result.path;
        await refreshTree();
      }
      toast('Renamed.', { kind: 'ok' });
    }
  }

  async function deleteSelected() {
    const path = selected;
    const folder = isFolder(path);
    if (!await confirm(folder ? 'Delete folder' : 'Delete file',
      `${path} moves to the trash on the bot. You can restore it from there for 30 days.`, { label: 'Delete', danger: true })) {
      return;
    }
    try {
      const result = await run('files.delete', { path }, { onStatus: (s) => s === 'awaiting_approval' && toast('Waiting for the bot owner to approve in Discord.') });
      drafts.delete(path);
      if (current && (current.path === path || current.path.startsWith(`${path}/`))) {
        current = null;
        renderHead();
        renderBody();
        setStatus();
      }
      selected = parentOf(path);
      expanded.delete(path);
      await refreshTree();
      toast(result.loaded_module ? `Moved to the trash. The extension ${result.loaded_module} is still loaded until you unload it.` : 'Moved to the trash.', { kind: 'ok' });
    } catch (error) {
      failure(error, 'Could not delete');
    }
  }

  function pickUpload() {
    const input = h('input', { type: 'file', multiple: true, hidden: true });
    input.addEventListener('change', () => {
      upload([...input.files]);
      input.remove();
    });
    document.body.appendChild(input);
    input.click();
  }

  async function upload(files) {
    const folder = folderOf(selected);
    if (!files.length) {
      return;
    }
    const existing = new Set((await list(folder).catch(() => ({ items: [] }))).items.map((i) => i.name));
    for (const file of files) {
      if (info && file.size > info.max_bytes) {
        toast(`${file.name} is larger than the limit of ${bytes(info.max_bytes)}.`, { kind: 'bad' });
        continue;
      }
      const replacing = existing.has(file.name);
      if (replacing && !await confirm('Replace file', `${folder}/${file.name} exists. Replace it? The old version goes to the trash.`, { label: 'Replace', danger: true })) {
        continue;
      }
      const note = toast(`Uploading ${file.name}`, { timeout: 0 });
      try {
        const data = new Uint8Array(await file.arrayBuffer());
        await writeFile(`${folder}/${file.name}`, data, replacing ? { force: true } : { create: true },
          (state) => note.update(`${file.name}: ${statusText(state)}`));
        note.close();
        toast(`${file.name} uploaded.`, { kind: 'ok' });
      } catch (error) {
        note.close();
        failure(error, `${file.name} was not uploaded`);
      }
    }
    listings.delete(folder);
    expanded.add(folder);
    refreshTree();
  }

  async function openTrash() {
    const listBox = h('div', { class: 'trash-list' }, skeleton(4));
    const dialog = modal({ title: 'Trash', wide: true, body: [h('p', { class: 'modal-text', text: 'Replaced and deleted files stay here on the bot for 30 days (at most 200).' }), listBox] });
    const fill = async () => {
      try {
        const data = await run('files.trash');
        mount(listBox, data.items.length ? data.items.map((entry) => h('div', { class: 'trash-row' },
          icon(entry.dir ? 'folder' : 'file'),
          h('div', { class: 'trash-text' }, h('strong', { text: entry.path }),
            h('small', { text: `${entry.reason === 'replaced' ? 'Replaced' : 'Deleted'} ${stamp(entry.at)}${entry.by ? ` by ${entry.by}` : ''}, ${bytes(entry.size)}` })),
          button('Restore', {
            class: 'btn btn-sm', disabled: writable() ? true : null,
            onClick: async (event) => {
              event.target.closest('button').disabled = true;
              try {
                await run('files.restore', { id: entry.id });
                toast(`${entry.path} restored.`, { kind: 'ok' });
                if (current?.path === entry.path) {
                  openFile(entry.path, { force: true });
                }
                refreshTree();
                fill();
              } catch (error) {
                failure(error, 'Could not restore');
                event.target.closest('button').disabled = false;
              }
            },
          }, 'undo'))) : h('p', { class: 'muted', text: 'The trash is empty.' }));
      } catch (error) {
        mount(listBox, h('p', { class: 'muted', text: error.message }));
      }
    };
    fill();
    await dialog.done;
  }

  async function load() {
    try {
      info = await run('files.roots');
    } catch (error) {
      if (alive) {
        mount(treeBody, h('p', { class: 'ftree-note muted', text: error.message }));
        mount(body, empty('alert', 'Files could not be loaded', error.message));
      }
      return;
    }
    if (!alive) {
      return;
    }
    for (const rootInfo of info.roots) {
      if (rootInfo.ok && !expanded.size) {
        expanded.add(rootInfo.path);
      }
    }
    if (selected && !isFolder(selected) && selected.includes('/')) {
      await revealParents(selected);
    }
    await Promise.all([...expanded].map((p) => list(p).catch(() => expanded.delete(p))));
    if (!alive) {
      return;
    }
    renderTree();
    renderTools();
    if (selected && !isFolder(selected)) {
      openFile(selected, { force: true });
    } else {
      renderBody();
    }
  }

  function beforeUnload(event) {
    if (dirty()) {
      event.preventDefault();
      event.returnValue = '';
    }
  }

  window.addEventListener('beforeunload', beforeUnload);
  stops.push(() => window.removeEventListener('beforeunload', beforeUnload));
  stops.push(on('bot', () => { renderTools(); renderHead(); }));
  stops.push(subscribe('meta', () => { renderTools(); renderHead(); }));
  renderBody();
  load();

  return {
    update(params) {
      const path = params[0] || '';
      if (path && path !== current?.path && info) {
        revealParents(path).then(() => { renderTree(); openFile(path); });
      }
    },
    destroy() {
      stashDraft();
      alive = false;
      editor?.destroy();
      stops.forEach((stop) => stop());
    },
  };
}
