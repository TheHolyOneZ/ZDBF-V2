import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { bytes } from '../core/format.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session, subscribe } from '../core/store.js';
import { createEditor } from '../ui/editor.js';
import { modal } from '../ui/modal.js';
import { empty, pill, segmented, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

const STATUS = { working: ['Working', 'ok'], beta: ['Beta', 'warn'], broken: ['Broken', 'bad'] };

function manageReason() {
  if (!can('extensions')) {
    return 'Your role cannot load or reload extensions.';
  }
  if (!botAllows('extensions')) {
    return 'Managing extensions is switched off on the bot (capability extensions).';
  }
  if (!session.bot.online) {
    return 'The bot is offline.';
  }
  return '';
}

function installReason() {
  if (!can('marketplace')) {
    return 'Your role cannot install extensions.';
  }
  if (!botAllows('marketplace')) {
    return 'Installing from the marketplace is switched off on the bot. The bot owner can enable "marketplace" with /dashboard capabilities.';
  }
  if (!session.bot.online) {
    return 'The bot is offline.';
  }
  return '';
}

function approvalNote(state, note) {
  if (state === 'awaiting_approval') {
    note.update('Waiting for the bot owner to approve in Discord');
  }
}

export default function extensionsView(page, context) {
  const stops = [];
  let alive = true;
  let tab = context.params[0] === 'marketplace' ? 'marketplace' : 'installed';
  let installed = null;
  let market = null;
  let query = '';
  const busy = new Set();

  const content = h('div', { class: 'ext-content' });
  const tabs = segmented([
    { value: 'installed', label: 'Installed' },
    { value: 'marketplace', label: 'Marketplace' },
  ], tab, (value) => {
    tab = value;
    replace(value === 'marketplace' ? 'extensions/marketplace' : 'extensions');
    render();
    if (value === 'marketplace' && !market) {
      loadMarket();
    }
  }, 'Extensions view');
  page.append(
    h('header', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', { text: 'Extensions' }),
        h('p', { text: 'Load, reload and install the extensions of the bot.' })),
      h('div', { class: 'page-actions' }, tabs.el)),
    content);

  async function act(item, verb) {
    const key = `${verb}:${item.name}`;
    if (busy.has(key)) {
      return;
    }
    busy.add(key);
    render();
    const note = toast(`${verb[0].toUpperCase()}${verb.slice(1)}ing ${item.name}`, { timeout: 0 });
    try {
      const result = await run(`extensions.${verb}`, { name: item.name }, { onStatus: (s) => approvalNote(s, note) });
      note.close();
      if (result.ok) {
        toast(`${item.name}: ${result.action}ed${result.ms ? ` in ${Math.round(result.ms)} ms` : ''}.${result.note ? ` ${result.note}.` : ''}`, { kind: 'ok' });
      } else {
        toast(result.error || 'That did not work.', { kind: 'bad', title: `${item.name} was not ${verb}ed` });
      }
    } catch (error) {
      note.close();
      failure(error, `${item.name} was not ${verb}ed`);
    } finally {
      busy.delete(key);
      await loadInstalled();
    }
  }

  async function setHotReload(enabled) {
    try {
      await run('extensions.hot_reload', { enabled });
      toast(enabled ? 'Hot reload is on.' : 'Hot reload is off.', { kind: 'ok' });
    } catch (error) {
      failure(error, 'Hot reload was not changed');
    }
    loadInstalled();
  }

  function stateOf(item) {
    if (item.loaded) {
      return item.traceback ? ['Loaded, last reload failed', 'warn'] : ['Loaded', 'ok'];
    }
    if (item.error) {
      return ['Failed', 'bad'];
    }
    if (item.blacklisted) {
      return ['Blocked in config', ''];
    }
    return ['Not loaded', ''];
  }

  function extensionRow(item, reason) {
    const [label, kind] = stateOf(item);
    const verbs = item.loaded ? ['reload', 'unload'] : ['load'];
    const details = item.traceback || item.error;
    return h('article', { class: 'ext-row', dataset: { state: kind || 'off' } },
      h('div', { class: 'ext-main' },
        h('div', { class: 'ext-name' }, h('strong', { text: item.name }),
          item.version ? h('span', { class: 'muted', text: `v${item.version}` }) : null,
          pill(label, kind),
          item.marketplace ? pill('Marketplace') : null),
        item.description ? h('p', { class: 'ext-desc', text: item.description }) : null,
        h('p', { class: 'ext-meta muted' },
          [item.author ? `by ${item.author}` : null,
            item.loaded && item.ms ? `loaded in ${Math.round(item.ms)} ms` : null,
            item.commands.length ? `${item.commands.length} command${item.commands.length === 1 ? '' : 's'}` : null]
            .filter(Boolean).join(' · ') || item.module),
        details ? h('details', { class: 'ext-error' },
          h('summary', { text: item.loaded ? 'Error of the last reload' : 'Error' }),
          h('pre', { text: details })) : null),
      h('div', { class: 'ext-actions' },
        item.file && can('files.read') ? h('a', { class: 'btn btn-sm', href: `#/files/${encodeURIComponent(item.file)}` }, icon('file'), h('span', { text: 'Open file' })) : null,
        verbs.map((verb) => button(verb[0].toUpperCase() + verb.slice(1), {
          class: `btn btn-sm ${verb === 'unload' ? '' : 'btn-primary'}`,
          disabled: reason || busy.has(`${verb}:${item.name}`) ? true : null,
          title: reason || null,
          onClick: () => act(item, verb),
        }, verb === 'unload' ? 'power' : 'refresh'))));
  }

  function renderInstalled() {
    if (!installed) {
      return h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6)));
    }
    const reason = manageReason();
    const loaded = installed.extensions.filter((e) => e.loaded).length;
    const failed = installed.extensions.filter((e) => e.error && !e.loaded).length;
    const switchInput = h('input', { type: 'checkbox', checked: installed.hot_reload || null, disabled: reason ? true : null });
    switchInput.addEventListener('change', () => setHotReload(switchInput.checked));
    return [
      h('section', { class: 'card ext-summary' },
        h('div', { class: 'ext-stats' },
          h('div', null, h('strong', { text: String(installed.extensions.length) }), h('span', { text: 'extensions' })),
          h('div', null, h('strong', { text: String(loaded) }), h('span', { text: 'loaded' })),
          h('div', { dataset: { kind: failed ? 'bad' : '' } }, h('strong', { text: String(failed) }), h('span', { text: 'failed' }))),
        h('label', { class: 'check ext-hot', title: reason || null }, switchInput,
          h('span', null, 'Hot reload', h('small', { text: installed.hot_reload
            ? `The bot reloads an extension within ${installed.interval} s when its file changes.`
            : 'Changed files are only picked up when you reload them.' }))),
        reason ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Extensions' }),
          h('p', { text: `Files in ${installed.directory}` }))),
        h('div', { class: 'card-body ext-list' }, installed.extensions.length
          ? installed.extensions.map((item) => extensionRow(item, reason))
          : empty('puzzle', 'No extensions yet', 'Install one from the marketplace or upload a file in Files.',
            button('Open the marketplace', { class: 'btn btn-primary', onClick: () => tabs.select('marketplace') }, 'store')))),
      h('section', { class: 'card' },
        h('header', { class: 'card-head' }, h('div', { class: 'card-title' }, h('h2', { text: 'Built-in modules' }),
          h('p', { text: 'Switched on and off in config.toml under [modules].' }))),
        h('div', { class: 'card-body module-grid' }, installed.builtin.map((m) => h('div', { class: 'module-chip', dataset: { state: m.loaded ? 'ok' : m.error ? 'bad' : 'off' }, title: m.error || null },
          h('span', { class: 'pill-dot' }), h('span', { text: m.name }),
          h('small', { class: 'muted', text: m.loaded ? `${Math.round(m.ms)} ms` : m.enabled ? 'failed' : 'off' }))))),
    ];
  }

  function marketCard(item) {
    const [label, kind] = STATUS[item.status] || [item.status, ''];
    return h('button', { type: 'button', class: 'market-card', onClick: () => openListing(item) },
      h('div', { class: 'market-top' }, h('strong', { text: item.title }), h('span', { class: 'muted', text: `v${item.version}` })),
      h('p', { class: 'market-desc', text: item.description || 'No description.' }),
      h('div', { class: 'market-foot' },
        pill(label, kind),
        item.official ? pill('Official', 'info') : h('span', { class: 'muted', text: `by ${item.creator}` }),
        item.update ? pill(`Update from v${item.installed}`, 'warn') : item.installed ? pill(item.loaded ? 'Installed, loaded' : 'Installed', 'ok') : null));
  }

  function renderMarket() {
    if (!market) {
      return h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(6)));
    }
    if (market.error) {
      return h('section', { class: 'card' }, empty('alert', 'The marketplace could not be loaded', market.error,
        button('Try again', { class: 'btn', onClick: () => loadMarket(true) }, 'refresh')));
    }
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const shown = market.items.filter((i) => !words.length || words.every((w) => `${i.title} ${i.description} ${i.creator}`.toLowerCase().includes(w)));
    const updates = market.items.filter((i) => i.update).length;
    const search = h('input', { type: 'search', class: 'market-search', placeholder: 'Search the marketplace', value: query, 'aria-label': 'Search the marketplace' });
    search.addEventListener('input', () => {
      query = search.value;
      const grid = content.querySelector('.market-grid');
      const words2 = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
      mount(grid, market.items.filter((i) => !words2.length || words2.every((w) => `${i.title} ${i.description} ${i.creator}`.toLowerCase().includes(w))).map(marketCard));
    });
    return [
      h('div', { class: 'market-bar' }, search,
        h('span', { class: 'muted', text: `${market.items.length} extensions${updates ? `, ${updates} update${updates === 1 ? '' : 's'}` : ''}` }),
        button('Refresh', { class: 'btn btn-sm', onClick: () => loadMarket(true) }, 'refresh')),
      !market.license ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: 'The bot owner has to accept the marketplace license once with /marketplace in Discord before anything can be installed.' }) : null,
      h('div', { class: 'market-grid' }, shown.length ? shown.map(marketCard) : h('p', { class: 'muted', text: 'Nothing matches.' })),
    ];
  }

  async function openListing(item) {
    const [label, kind] = STATUS[item.status] || [item.status, ''];
    const scanBox = h('div', { class: 'market-scan' }, skeleton(4));
    const sourceHost = h('div', { class: 'market-source' });
    let viewer = null;
    let preview = null;
    const loadBox = h('input', { type: 'checkbox', checked: true });
    const pkgBox = h('input', { type: 'checkbox', checked: true });
    const reason = installReason();
    const dialog = modal({
      title: item.title,
      wide: true,
      body: [
        h('div', { class: 'market-head' }, pill(label, kind), h('span', { class: 'muted', text: `v${item.version} · ${item.official ? 'official' : `by ${item.creator}`}` }),
          item.installed ? pill(item.update ? `Installed v${item.installed}, update available` : 'Installed', item.update ? 'warn' : 'ok') : null),
        item.details || item.description ? h('p', { class: 'market-details', text: item.details || item.description }) : null,
        item.changelog ? h('details', { class: 'market-changelog' }, h('summary', { text: 'Changes in this version' }), h('pre', { text: item.changelog })) : null,
        scanBox,
        h('details', { class: 'market-code' }, h('summary', { text: 'Show the code' }), sourceHost),
        reason ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null,
      ],
      actions: [
        { label: 'Close', value: null },
        {
          label: item.installed ? (item.update ? 'Update' : 'Install again') : 'Install', primary: true, submit: true,
          run: async () => {
            if (reason) {
              throw new Error(reason);
            }
            if (!preview?.ok) {
              throw new Error(preview?.error || 'Wait for the check to finish.');
            }
            const note = toast(`Installing ${item.title}`, { timeout: 0 });
            try {
              const result = await run('marketplace.install', {
                id: item.id, sha256: preview.sha256, load: loadBox.checked, packages: pkgBox.checked,
              }, { timeout: 16 * 60 * 1000, onStatus: (s) => approvalNote(s, note) });
              note.close();
              return result;
            } catch (error) {
              note.close();
              throw error;
            }
          },
        },
      ],
    });
    dialog.form.querySelector('.modal-foot button[type="submit"]').disabled = true;
    try {
      preview = await run('marketplace.preview', { id: item.id }, { timeout: 120000 });
      if (!dialog.body.isConnected) {
        return;
      }
      const submit = dialog.form.querySelector('.modal-foot button[type="submit"]');
      submit.disabled = !preview.ok || Boolean(reason) || !preview.license;
      mount(scanBox,
        h('dl', { class: 'facts' },
          h('dt', { text: 'File' }), h('dd', null, h('code', { text: preview.path })),
          h('dt', { text: 'Size' }), h('dd', { text: `${bytes(preview.bytes)}, ${preview.lines} lines` }),
          h('dt', { text: 'Entry point' }), h('dd', { text: preview.has_setup ? 'async def setup found' : 'no async def setup, it may not load' }),
          h('dt', { text: 'Imports' }), h('dd', { text: preview.imports.join(', ') || 'none' })),
        !preview.ok ? h('p', { class: 'note', dataset: { kind: 'bad' }, text: preview.error }) : null,
        preview.exists ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: `${preview.file} exists on the bot and will be replaced.` }) : null,
        preview.flags.length ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: `Review before loading: ${preview.flags.join(', ')}. These are common in normal extensions too.` }) : null,
        !preview.license ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: 'The bot owner has to accept the marketplace license once with /marketplace in Discord.' }) : null,
        h('label', { class: 'check' }, loadBox, h('span', null, 'Load it after installing')),
        preview.packages.length ? h('label', { class: 'check' }, pkgBox,
          h('span', null, `Install the missing Python packages first: ${preview.packages.join(', ')}`,
            h('small', { text: market?.auto_packages ? `Runs ${preview.command} on the bot. This can take a few minutes.` : 'Package installs are switched off in [marketplace] auto_install_packages. Install them on the bot machine.' }))) : null);
      if (!market?.auto_packages) {
        pkgBox.checked = false;
        pkgBox.disabled = true;
      }
      sourceHost.closest('details').addEventListener('toggle', async () => {
        if (!viewer && sourceHost.closest('details').open) {
          viewer = await createEditor(sourceHost, { doc: preview.source, language: 'python', readOnly: true, label: 'Extension code' }).catch(() => null);
        }
      });
    } catch (error) {
      mount(scanBox, h('p', { class: 'note', dataset: { kind: 'bad' }, text: error.message }));
    }
    const result = await dialog.done;
    viewer?.destroy();
    if (!result || !alive) {
      return;
    }
    const failed = result.steps.filter((s) => !s.ok);
    modal({
      title: failed.length ? `${item.title} needs attention` : `${item.title} installed`,
      body: h('ul', { class: 'steps' }, result.steps.map((step) => h('li', { dataset: { kind: step.ok ? 'ok' : 'bad' } },
        icon(step.ok ? 'check' : 'alert'), h('span', null, step.text,
          step.missing?.length ? h('small', { text: `Still missing: ${step.missing.join(', ')}` }) : null,
          step.output?.length ? h('pre', { text: step.output.join('\n') }) : null)))),
    });
    market = null;
    loadMarket();
    loadInstalled();
  }

  function render() {
    mount(content, tab === 'marketplace' ? renderMarket() : renderInstalled());
  }

  async function loadInstalled() {
    try {
      const data = await run('extensions.list');
      if (alive) {
        installed = data;
      }
    } catch (error) {
      if (alive && !installed) {
        mount(content, h('section', { class: 'card' }, empty('alert', 'Extensions could not be loaded', error.message)));
        return;
      }
    }
    if (alive && tab === 'installed') {
      render();
    }
  }

  async function loadMarket(refresh = false) {
    if (refresh) {
      market = null;
      render();
    }
    try {
      market = await run('marketplace.list', { refresh }, { timeout: 90000 });
    } catch (error) {
      market = { error: error.message };
    }
    if (alive && tab === 'marketplace') {
      render();
    }
  }

  stops.push(on('bot', () => render()));
  stops.push(subscribe('meta', () => render()));
  render();
  loadInstalled();
  if (tab === 'marketplace') {
    loadMarket();
  }

  return {
    update(params) {
      const next = params[0] === 'marketplace' ? 'marketplace' : 'installed';
      if (next !== tab) {
        tabs.select(next);
      }
    },
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}
