import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session, subscribe } from '../core/store.js';
import { renderMessage } from '../ui/message.js';
import { empty, pill, skeleton } from '../ui/parts.js';

const HINTS = {
  member: 'Name, mention or ID',
  role: 'Role name, mention or ID',
  channel: 'Channel name, mention or ID',
  thread: 'Thread name, mention or ID',
  'member or role': 'Name, mention or ID',
  'whole number': 'A whole number',
  number: 'A number',
};
const MAX_RESULTS = 5;

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    return false;
  }
  return true;
}

export default function commandsView(page, context) {
  const stops = [];
  let alive = true;
  let commands = [];
  let prefix = '!';
  let tree = null;
  let filter = '';
  let selected = context.params[0] || null;
  let channelId = recall('zdbf-cmd-channel') || recall('zdbf-chat-channel') || '';
  let controls = new Map();
  let busy = false;
  const modes = new Map();

  function modeOf(command) {
    return modes.get(command.name) || (command.owner ? 'owner' : 'member');
  }

  const search = h('input', { class: 'tree-search', type: 'text', placeholder: 'Find a command', 'aria-label': 'Find a command', autocomplete: 'off' });
  const listBody = h('div', { class: 'cmd-list-body' }, skeleton(10));
  const listPane = h('aside', { class: 'cmd-list card' }, h('div', { class: 'tree-head' }, search), listBody);
  const detail = h('section', { class: 'cmd-detail card' });
  const results = h('div', { class: 'cmd-results' });
  const root = h('div', { class: 'cmd', dataset: { pane: selected ? 'detail' : 'list' } }, listPane, h('div', { class: 'cmd-side' }, detail, results));
  page.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', { text: 'Commands' }),
      h('p', { text: 'Run any command as the bot, in a channel you choose.' }))),
    root);

  function find(name) {
    return commands.find((c) => c.name === name) || null;
  }

  function display(command) {
    return command.form === 'slash' || command.slash ? `/${command.slash || command.name}` : `${prefix}${command.name}`;
  }

  function renderList() {
    const query = filter.trim().toLowerCase();
    const shown = commands.filter((c) => !query || c.name.includes(query) || c.description.toLowerCase().includes(query)
      || c.aliases.some((a) => a.includes(query)) || c.category.toLowerCase().includes(query));
    const groups = new Map();
    for (const command of shown) {
      if (!groups.has(command.category)) {
        groups.set(command.category, []);
      }
      groups.get(command.category).push(command);
    }
    mount(listBody, groups.size ? [...groups.entries()].map(([category, items]) => h('section', { class: 'cmd-group' },
      h('header', { class: 'tree-category', text: category }),
      items.map((command) => h('button', {
        type: 'button', class: 'cmd-item', 'aria-current': command.name === selected ? 'true' : null,
        onClick: () => select(command.name),
      }, h('span', { class: 'cmd-item-name' }, h('code', { text: command.name }), command.owner ? icon('lock') : null),
      h('span', { class: 'cmd-item-desc', text: command.description })))))
      : h('p', { class: 'muted tree-empty', text: query ? 'No command matches.' : 'The bot reported no commands.' }));
  }

  function gate(command) {
    const owner = modeOf(command) === 'owner';
    const capability = owner ? 'commands.owner' : 'commands.run';
    if (!can(capability)) {
      return owner ? 'Your role cannot run commands with the rights of the bot owner.' : 'Your role cannot run commands.';
    }
    if (!botAllows(capability)) {
      return owner
        ? 'Running commands with the rights of the bot owner is switched off on the bot. The bot owner can enable "commands.owner" with /dashboard capabilities.'
        : 'Running commands is switched off on the bot (capability commands.run).';
    }
    if (command.params.some((p) => p.kind === 'file' && p.required)) {
      return 'This command needs a file, which only works in Discord.';
    }
    if (!session.bot.online) {
      return 'The bot is offline.';
    }
    if (tree && !tree.guilds.length && !tree.dms.length) {
      return 'The bot has no channel it can write in.';
    }
    return '';
  }

  function control(param) {
    let input;
    const common = { name: param.name, 'aria-label': param.label };
    if (param.kind === 'choice') {
      input = h('select', { ...common, required: param.required || null },
        h('option', { value: '', text: param.required ? 'Choose' : (param.default ? `Default: ${param.default}` : 'Not set') }),
        param.choices.map((choice) => h('option', { value: choice, text: choice })));
    } else if (param.kind === 'yes / no') {
      input = h('select', { ...common, required: param.required || null },
        h('option', { value: '', text: param.required ? 'Choose' : (param.default ? `Default: ${param.default}` : 'Not set') }),
        h('option', { value: 'true', text: 'Yes' }), h('option', { value: 'false', text: 'No' }));
    } else if (param.kind === 'file') {
      input = h('input', { ...common, type: 'text', disabled: true, placeholder: 'Files can only be sent in Discord' });
    } else if (param.rest) {
      input = h('textarea', { ...common, rows: '3', maxlength: '1800', required: param.required || null,
        placeholder: param.default ? `Default: ${param.default}` : '' });
    } else {
      const numeric = param.kind === 'whole number' || param.kind === 'number';
      input = h('input', { ...common, type: 'text', maxlength: '400', required: param.required || null, autocomplete: 'off',
        inputmode: numeric ? (param.kind === 'number' ? 'decimal' : 'numeric') : null,
        placeholder: param.default ? `Default: ${param.default}` : (HINTS[param.kind] || '') });
    }
    controls.set(param.name, input);
    return h('label', { class: 'field' },
      h('span', null, param.label, param.required ? h('em', { class: 'req', text: 'required' }) : null,
        h('small', { class: 'kind', text: param.kind })),
      input, param.description ? h('small', { text: param.description }) : null);
  }

  function collect(command) {
    const values = {};
    let last = -1;
    command.params.forEach((param, index) => {
      const value = String(controls.get(param.name)?.value || '').trim();
      if (value) {
        values[param.name] = value;
        last = index;
      }
    });
    command.params.slice(0, Math.max(0, last)).forEach((param) => {
      if (values[param.name] === undefined && param.default != null) {
        values[param.name] = param.kind === 'yes / no' ? String(param.default === 'yes') : param.default;
      }
    });
    return values;
  }

  function rightsPicker(command) {
    const mode = modeOf(command);
    const select = h('select', { 'aria-label': 'Run with the rights of' },
      h('option', { value: 'member', text: 'An ordinary member', selected: mode === 'member' || null }),
      h('option', { value: 'owner', text: 'The bot owner', selected: mode === 'owner' || null }));
    select.addEventListener('change', () => {
      modes.set(command.name, select.value);
      refresh();
    });
    return h('label', { class: 'field' }, h('span', { text: 'Run with the rights of' }), select,
      mode === 'member' && command.owner ? h('small', { text: 'This command is restricted, so the bot will refuse it for an ordinary member.' }) : null);
  }

  function channelPicker(command) {
    if (!tree) {
      return h('p', { class: 'muted', text: 'Loading channels.' });
    }
    const all = [];
    for (const guild of tree.guilds) {
      for (const item of guild.channels) {
        all.push({ id: item.id, guild: guild.id, label: `#${item.name}` });
        for (const thread of guild.threads.filter((t) => t.parent === item.id)) {
          all.push({ id: thread.id, guild: guild.id, label: `   ${thread.name} (thread)` });
        }
      }
    }
    for (const dm of tree.dms) {
      all.push({ id: dm.id, guild: 'dm', label: `@${dm.name}` });
    }
    if (!all.some((c) => c.id === channelId)) {
      channelId = all[0]?.id || '';
    }
    const current = all.find((c) => c.id === channelId);
    const guildSelect = h('select', { 'aria-label': 'Server' },
      tree.guilds.map((g) => h('option', { value: g.id, text: g.name, selected: current?.guild === g.id || null })),
      tree.dms.length ? h('option', { value: 'dm', text: 'Direct messages', selected: current?.guild === 'dm' || null }) : null);
    const channelSelect = h('select', { 'aria-label': 'Channel' });
    const fill = () => {
      const items = all.filter((c) => c.guild === guildSelect.value);
      if (!items.some((c) => c.id === channelId)) {
        channelId = items[0]?.id || '';
      }
      mount(channelSelect, items.map((c) => h('option', { value: c.id, text: c.label, selected: c.id === channelId || null })));
    };
    guildSelect.addEventListener('change', () => {
      channelId = '';
      fill();
      remember('zdbf-cmd-channel', channelId);
    });
    channelSelect.addEventListener('change', () => {
      channelId = channelSelect.value;
      remember('zdbf-cmd-channel', channelId);
    });
    fill();
    return h('div', { class: 'cmd-where-grid' },
      h('label', { class: 'field' }, h('span', { text: 'Server' }), guildSelect),
      h('label', { class: 'field' }, h('span', { text: 'Channel' }), channelSelect),
      rightsPicker(command));
  }

  function resultCard(command) {
    const state = h('span', { class: 'cmd-result-state' }, pill('Running', 'info'));
    const body = h('div', { class: 'cmd-result-body' }, skeleton(3));
    const link = h('span', { class: 'cmd-result-link' });
    const title = h('code', { text: display(command) });
    const node = h('article', { class: 'card cmd-result' },
      h('header', { class: 'card-head' }, h('div', { class: 'cmd-result-title' }, title, state), link), body);
    results.prepend(node);
    while (results.children.length > MAX_RESULTS) {
      results.lastChild.remove();
    }
    return {
      status(text) {
        mount(state, pill(text, 'info'));
      },
      fail(message) {
        mount(state, pill('Not run', 'bad'));
        mount(body, h('p', { class: 'note', dataset: { kind: 'bad' }, text: message }));
      },
      done(data) {
        title.textContent = data.ran;
        mount(state, data.pending ? pill('Still running', 'warn') : data.failed ? pill('Refused or failed', 'bad') : pill('Done', 'ok'),
          h('span', { class: 'muted', text: `in ${data.channel.name.startsWith('@') ? data.channel.name : `#${data.channel.name}`}, ${data.as_owner ? 'with owner rights' : 'as an ordinary member'}` }));
        mount(link, h('a', { class: 'btn btn-sm', href: data.url, target: '_blank', rel: 'noopener noreferrer' }, icon('external'), h('span', { text: 'Open in Discord' })));
        const interactive = data.messages.some((m) => JSON.stringify(m.components).includes('"t":"button"') || JSON.stringify(m.components).includes('"t":"select"'));
        mount(body,
          data.messages.length
            ? h('div', { class: 'cmd-result-messages' }, data.messages.map((m) => renderMessage(m, {})))
            : h('p', { class: 'muted', text: data.pending
              ? 'The command is still working. Its answer will appear in the channel.'
              : 'The command finished without posting a message.' }),
          interactive ? h('p', { class: 'muted cmd-hint', text: 'Buttons and menus in the answer are used in Discord.' }) : null);
      },
    };
  }

  async function submit(command, runButton) {
    if (busy) {
      return;
    }
    const values = collect(command);
    busy = true;
    runButton.disabled = true;
    const view = resultCard(command);
    try {
      const data = await run(modeOf(command) === 'owner' ? 'commands.run_owner' : 'commands.run',
        { command: command.name, values, channel_id: channelId },
        { onStatus: (status) => view.status(status === 'awaiting_approval' ? 'Waiting for approval in Discord' : 'Running') });
      if (alive) {
        view.done(data);
      }
    } catch (error) {
      view.fail(error.message);
    } finally {
      busy = false;
      runButton.disabled = false;
    }
  }

  function renderDetail() {
    const command = find(selected);
    controls = new Map();
    if (!command) {
      mount(detail, empty('terminal', commands.length ? 'Pick a command' : 'Loading commands',
        commands.length ? 'Choose a command on the left to see its options and run it.' : ''));
      return;
    }
    const reason = gate(command);
    const runButton = button('Run as the bot', { class: 'btn btn-primary', type: 'submit', disabled: reason ? true : null }, 'play');
    const form = h('form', { class: 'cmd-form' },
      command.params.length ? h('div', { class: 'cmd-options' }, command.params.map(control)) : h('p', { class: 'muted', text: 'This command has no options.' }),
      h('div', { class: 'cmd-where' }, h('h3', { text: 'Where and how' }), channelPicker(command)),
      reason ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null,
      h('div', { class: 'card-foot' }, runButton,
        h('span', { class: 'muted cmd-hint', text: 'The bot posts the command in the channel and answers there.' })));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (form.reportValidity()) {
        submit(command, runButton);
      }
    });
    mount(detail,
      h('header', { class: 'cmd-head' },
        h('button', { type: 'button', class: 'icon-btn cmd-back', 'aria-label': 'Back to the list', onClick: () => { root.dataset.pane = 'list'; } }, icon('left')),
        h('div', { class: 'cmd-title' }, h('h2', null, h('code', { text: display(command) })), h('p', { text: command.description })),
        h('div', { class: 'pills' },
          pill(command.access !== 'Everyone' ? command.access : command.owner ? 'Restricted' : 'Everyone', command.owner ? 'warn' : ''),
          command.form === 'slash' ? pill('Slash only') : pill(command.slash ? 'Slash and prefix' : 'Prefix only'),
          pill(command.category))),
      command.aliases.length ? h('p', { class: 'muted cmd-aliases' }, 'Also: ', command.aliases.map((a, i) => [i ? ', ' : '', h('code', { text: `${prefix}${a}` })])) : null,
      form);
  }

  function select(name) {
    selected = name;
    root.dataset.pane = 'detail';
    replace(`commands/${encodeURIComponent(name)}`);
    renderList();
    renderDetail();
  }

  async function load() {
    try {
      const [list, channels] = await Promise.all([run('commands.list'), run('commands.channels')]);
      if (!alive) {
        return;
      }
      commands = list.commands;
      prefix = list.prefix;
      tree = channels;
    } catch (error) {
      if (alive) {
        mount(listBody, h('p', { class: 'muted tree-empty', text: error.message }));
        mount(detail, empty('alert', 'Commands could not be loaded', error.message));
      }
      return;
    }
    renderList();
    renderDetail();
  }

  search.addEventListener('input', () => {
    filter = search.value;
    renderList();
  });
  function refresh() {
    if (commands.length && !busy) {
      const typed = new Map([...controls].map(([name, input]) => [name, input.value]));
      renderDetail();
      for (const [name, value] of typed) {
        if (controls.has(name)) {
          controls.get(name).value = value;
        }
      }
    }
  }

  stops.push(on('bot', refresh));
  stops.push(subscribe('meta', refresh));
  renderDetail();
  load();

  return {
    update(params) {
      if (params[0] && params[0] !== selected && find(params[0])) {
        select(params[0]);
      }
    },
    destroy() {
      alive = false;
      stops.forEach((stop) => stop());
    },
  };
}
