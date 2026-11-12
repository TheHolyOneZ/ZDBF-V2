import { run } from '../core/api.js';
import { button, h, icon, mount } from '../core/dom.js';
import { shortStamp } from '../core/format.js';
import { replace } from '../core/router.js';
import { can, on, subscribe } from '../core/store.js';
import { confirm, modal } from '../ui/modal.js';
import { empty, pill, segmented, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';
import { approvalToast, blockedReason } from './servers.js';

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

function iso(value) {
  return value ? Date.parse(value) / 1000 : null;
}

function channelOptions(resources, types) {
  const allowed = types && types.length ? types : ['text', 'news'];
  return resources.channels.filter((c) => allowed.includes(c.kind));
}

export function paramControl(param, value, resources, extra = {}) {
  let input;
  let read;
  const kind = param.kind;
  if (kind === 'channel') {
    const list = channelOptions(resources, param.channel_types);
    input = h('select', null, h('option', { value: '', text: extra.channelEmpty || (param.required ? 'Choose a channel' : 'Not set') }),
      list.map((c) => h('option', { value: c.id, text: `${c.kind === 'category' ? '' : '#'}${c.name}${c.category ? `  (${c.category})` : ''}`, selected: String(value) === c.id || null })));
    read = () => input.value || null;
  } else if (kind === 'role') {
    input = h('select', null, h('option', { value: '', text: param.required ? 'Choose a role' : 'Not set' }),
      resources.roles.map((r) => h('option', { value: r.id, text: r.name, selected: String(value) === r.id || null })));
    read = () => input.value || null;
  } else if (kind === 'roles') {
    const chosen = new Set((value || []).map(String));
    input = h('select', { multiple: true, size: '6' }, resources.roles.map((r) => h('option', { value: r.id, text: r.name, selected: chosen.has(r.id) || null })));
    read = () => [...input.selectedOptions].map((o) => o.value);
  } else if (kind === 'bool') {
    input = h('input', { type: 'checkbox', checked: (value ?? param.default) ? true : null });
    read = () => input.checked;
  } else if (kind === 'choice') {
    input = h('select', null, param.choices.map((c) => h('option', { value: c, text: c.replace(/_/g, ' '), selected: String(value ?? param.default) === c || null })));
    read = () => input.value;
  } else if (kind === 'number') {
    input = h('input', { type: 'number', step: 'any', value: value ?? param.default ?? '' });
    read = () => (input.value === '' ? null : Number(input.value));
  } else if (kind === 'json') {
    input = h('textarea', { rows: '4', class: 'mono', spellcheck: 'false' });
    input.value = value == null ? (param.default ?? '') : (typeof value === 'string' ? value : JSON.stringify(value, null, 2));
    read = () => input.value.trim() || null;
  } else if (kind === 'automation') {
    input = h('input', { type: 'text', value: value ?? '', placeholder: 'Automation ID' });
    read = () => input.value.trim() || null;
  } else if (kind === 'textarea') {
    input = h('textarea', { rows: '3', maxlength: '4000' });
    input.value = value ?? param.default ?? '';
    read = () => input.value;
  } else {
    input = h('input', { type: 'text', value: value ?? param.default ?? '', maxlength: '300' });
    read = () => input.value;
  }
  const node = kind === 'bool'
    ? h('label', { class: 'check' }, input, h('span', null, param.label, param.description ? h('small', { text: param.description }) : null))
    : h('label', { class: 'field' }, h('span', null, param.label, param.required ? h('em', { class: 'req', text: 'required' }) : null), input,
      param.description ? h('small', { text: param.description }) : null);
  return { node, input, read };
}

function actionsEditor(catalogue, initial, resources) {
  const box = h('div', { class: 'act-list' });
  const items = [];
  const addSelect = h('select', { 'aria-label': 'Action to add' }, catalogue.actions.map((a) => h('option', { value: a.id, text: a.name })));
  function add(entry) {
    const type = catalogue.actions.find((a) => a.id === entry.type);
    if (!type) {
      return;
    }
    const controls = type.fields.map((f) => [f.key, paramControl(f, entry[f.key], resources, { channelEmpty: 'The channel of the event' })]);
    const item = { type: type.id, controls };
    const node = h('div', { class: 'act-item' },
      h('header', null, h('strong', { text: type.name }), h('small', { class: 'muted', text: type.description }),
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Remove action', onClick: () => { items.splice(items.indexOf(item), 1); node.remove(); } }, icon('x'))),
      h('div', { class: 'act-fields' }, controls.map(([, c]) => c.node)));
    item.node = node;
    items.push(item);
    box.appendChild(node);
  }
  for (const entry of initial || []) {
    add(entry);
  }
  const node = h('div', { class: 'act-editor' }, box,
    h('div', { class: 'act-add' }, addSelect, button('Add action', { class: 'btn btn-sm', onClick: () => add({ type: addSelect.value }) }, 'plus')));
  return {
    node,
    read: () => items.map((item) => {
      const out = { type: item.type };
      for (const [key, control] of item.controls) {
        const value = control.read();
        if (value !== null && value !== '') {
          out[key] = value;
        }
      }
      return out;
    }),
  };
}

export default function automationsView(page, context) {
  let alive = true;
  const stops = [];
  let tab = context.params[0] === 'tasks' ? 'tasks' : 'automations';
  let servers = null;
  let guildId = recall('zdbf-auto-guild') || '';
  let catalogue = null;
  let resources = null;
  let autos = null;
  let tasks = null;

  const body = h('div', { class: 'auto-body' });
  const picker = h('select', { class: 'auto-guild', 'aria-label': 'Server' });
  const tabs = segmented([{ value: 'automations', label: 'Automations' }, { value: 'tasks', label: 'Scheduled tasks' }], tab, (value) => {
    tab = value;
    replace(value === 'tasks' ? 'automations/tasks' : 'automations');
    render();
  }, 'Automations view');
  page.append(
    h('header', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', { text: 'Automations' }), h('p', { text: 'What the bot does on its own: automations react to events, scheduled tasks run on a timetable.' })),
      h('div', { class: 'page-actions' }, tabs.el)),
    body);

  picker.addEventListener('change', () => {
    guildId = picker.value;
    remember('zdbf-auto-guild', guildId);
    autos = null;
    resources = null;
    render();
    loadGuild();
  });

  function fillPicker() {
    mount(picker, (servers || []).map((s) => h('option', { value: s.id, text: s.name, selected: s.id === guildId || null })));
  }

  async function editAutomation(existing, templateId) {
    const template = catalogue.templates.find((t) => t.id === (existing?.template || templateId));
    if (!template) {
      return;
    }
    const config = existing?.config || {};
    const controls = [];
    const fields = h('div', { class: 'auto-fields' });
    let actionsEdit = null;
    const values = { ...Object.fromEntries(template.params.map((p) => [p.key, p.default])), ...config };
    for (const param of template.params) {
      if (param.kind === 'actions') {
        actionsEdit = actionsEditor(catalogue, config[param.key], resources);
        controls.push([param, { read: actionsEdit.read, node: h('div', { class: 'field' }, h('span', { text: param.label }), actionsEdit.node) }]);
      } else {
        controls.push([param, paramControl(param, config[param.key], resources)]);
      }
    }
    const visible = () => {
      for (const [param, control] of controls) {
        if (param.show_if) {
          const other = controls.find(([p]) => p.key === param.show_if.key);
          const current = other ? other[1].read() : values[param.show_if.key];
          control.node.hidden = !param.show_if.values.includes(String(current));
        }
      }
    };
    mount(fields, controls.map(([, c]) => c.node));
    fields.addEventListener('change', visible);
    visible();
    const conditions = h('textarea', { rows: '5', class: 'mono', spellcheck: 'false', placeholder: '[]' });
    conditions.value = existing && existing.conditions?.rules?.length ? JSON.stringify(existing.conditions, null, 2) : '';
    const name = h('input', { name: 'name', required: true, maxlength: '100', value: existing?.name || template.name });
    const result = await modal({
      title: existing ? `Edit ${existing.name}` : template.name,
      wide: true,
      body: [
        h('p', { class: 'modal-text', text: template.description }),
        h('label', { class: 'field' }, h('span', { text: 'Name' }), name),
        fields,
        h('details', { class: 'auto-conditions' }, h('summary', { text: 'Conditions (advanced)' }),
          h('p', { class: 'muted', text: 'JSON rules that must match before the automation runs, as described by /hooks conditions in Discord. Empty runs always.' }), conditions),
      ],
      actions: [{ label: 'Cancel', value: null }, {
        label: existing ? 'Save' : 'Create', primary: true, submit: true,
        run: async () => {
          const out = {};
          for (const [param, control] of controls) {
            if (!control.node.hidden) {
              out[param.key] = control.read();
            }
          }
          const args = { guild_id: guildId, name: name.value.trim(), config: out };
          if (existing) {
            args.id = existing.id;
          } else {
            args.template = template.id;
          }
          if (conditions.value.trim()) {
            args.conditions = conditions.value.trim();
          } else if (existing) {
            args.conditions = [];
          }
          const t = approvalToast('Saving the automation');
          try {
            return await run('automations.save', args, { onStatus: t.onStatus });
          } finally {
            t.note.close();
          }
        },
      }],
    }).done;
    if (result) {
      toast(existing ? 'Automation saved.' : 'Automation created.', { kind: 'ok' });
      loadGuild();
    }
  }

  async function pickTemplate() {
    const dialog = modal({
      title: 'New automation',
      wide: true,
      body: h('div', { class: 'tpl-grid' }, catalogue.templates.map((t) => h('button', {
        type: 'button', class: 'market-card tpl-card', onClick: () => dialog.close(t.id),
      }, h('strong', { text: t.name }), h('p', { class: 'market-desc', text: t.description })))),
    });
    const id = await dialog.done;
    if (id) {
      editAutomation(null, id);
    }
  }

  async function history(auto) {
    const box = h('div', null, skeleton(4));
    modal({ title: `Runs of ${auto.name}`, wide: true, body: box });
    try {
      const data = await run('automations.history', { id: auto.id });
      mount(box, data.runs.length ? table([
        { label: 'When', render: (r) => shortStamp(typeof r.at === 'number' ? r.at : iso(r.at)) },
        { label: 'Event', render: (r) => r.event },
        { label: 'Result', render: (r) => (r.ok ? pill('OK', 'ok') : pill('Failed', 'bad')) },
        { label: 'Time', class: 'num', render: (r) => `${r.ms} ms` },
        { label: 'Error', render: (r) => r.error || '' },
      ], data.runs) : h('p', { class: 'muted', text: 'It has not run yet.' }));
    } catch (error) {
      mount(box, h('p', { class: 'note', dataset: { kind: 'bad' }, text: error.message }));
    }
  }

  function renderAutomations() {
    if (!servers) {
      return h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(5)));
    }
    if (!servers.length) {
      return h('section', { class: 'card' }, empty('server', 'No servers', 'Automations live in a server. Invite the bot first.'));
    }
    const reason = blockedReason('automations', 'change automations');
    const create = button('New automation', { class: 'btn btn-primary btn-sm', disabled: reason || !catalogue || !resources ? true : null, title: reason || null, onClick: () => pickTemplate() }, 'plus');
    let list;
    if (!autos) {
      list = skeleton(4);
    } else if (!autos.length) {
      list = empty('bolt', 'No automations here', 'Welcome messages, role menus, level-ups, tickets, word filters and more.');
    } else {
      list = autos.map((a) => {
        const toggle = h('input', { type: 'checkbox', checked: a.enabled || null, disabled: reason ? true : null, 'aria-label': `Turn ${a.name} on or off` });
        toggle.addEventListener('change', async () => {
          try {
            await run('automations.toggle', { id: a.id, enabled: toggle.checked });
            a.enabled = toggle.checked;
          } catch (error) {
            toggle.checked = !toggle.checked;
            failure(error);
          }
        });
        return h('article', { class: 'ext-row', dataset: { state: a.enabled ? (a.last_error ? 'warn' : 'ok') : 'off' } },
          h('label', { class: 'switch' }, toggle, h('span', { class: 'switch-track' })),
          h('div', { class: 'ext-main' },
            h('div', { class: 'ext-name' }, h('strong', { text: a.name }), pill(a.template_name), a.enabled ? null : pill('Off')),
            h('p', { class: 'ext-meta muted', text: `${a.runs} run${a.runs === 1 ? '' : 's'}, ${a.errors} error${a.errors === 1 ? '' : 's'}${a.last_run ? `, last ${shortStamp(iso(a.last_run))}` : ''} · ID ${a.id}` }),
            a.last_error ? h('details', { class: 'ext-error' }, h('summary', { text: 'Last error' }), h('pre', { text: a.last_error })) : null),
          h('div', { class: 'ext-actions' },
            button('Runs', { class: 'btn btn-sm', onClick: () => history(a) }, 'list'),
            button('Edit', { class: 'btn btn-sm', disabled: reason || !resources ? true : null, onClick: () => editAutomation(a) }, 'edit'),
            button('', { class: 'btn btn-sm', 'aria-label': `Delete ${a.name}`, title: 'Delete', disabled: reason ? true : null, onClick: async () => {
              if (await confirm('Delete automation', `${a.name} and its run history are removed.`, { label: 'Delete', danger: true })) {
                try {
                  await run('automations.delete', { id: a.id });
                  loadGuild();
                } catch (error) {
                  failure(error);
                }
              }
            } }, 'trash')));
      });
    }
    return [
      h('div', { class: 'market-bar' }, h('label', { class: 'auto-pick' }, h('span', { class: 'muted', text: 'Server' }), picker), h('span', { class: 'log-grow' }), create),
      reason && can('automations') ? h('p', { class: 'note', dataset: { kind: 'warn' }, text: reason }) : null,
      h('section', { class: 'card' }, h('div', { class: 'card-body ext-list' }, list)),
    ];
  }

  async function editTask(existing) {
    const guilds = servers || [];
    const guild = h('select', { name: 'guild' }, guilds.map((s) => h('option', { value: s.id, text: s.name, selected: (existing?.guild_id || guildId) === s.id || null })));
    const kind = h('select', { name: 'type' }, [['message', 'Send a message'], ['hook', 'Emit an event hook'], ['log', 'Write a log line']]
      .map(([v, l]) => h('option', { value: v, text: l, selected: (existing?.type || 'message') === v || null })));
    const channel = h('select', { name: 'channel' });
    const cron = h('input', { name: 'cron', required: true, maxlength: '120', value: existing?.cron || '0 9 * * *', autocomplete: 'off', class: 'mono' });
    const cronOut = h('small', { class: 'muted' });
    const message = h('textarea', { name: 'message', rows: '3', maxlength: '2000' });
    message.value = existing?.payload?.content || existing?.payload?.message || '';
    const title = h('input', { name: 'title', maxlength: '200', value: existing?.payload?.title || '' });
    const hook = h('input', { name: 'hook', maxlength: '80', value: existing?.payload?.hook_name || 'scheduled_task' });
    const maxRuns = h('input', { name: 'max_runs', type: 'number', min: '0', value: existing?.max_runs || '' });
    const channelField = h('label', { class: 'field' }, h('span', { text: 'Channel' }), channel);
    const messageField = h('label', { class: 'field' }, h('span', { text: 'Message' }), message);
    const titleField = h('label', { class: 'field' }, h('span', { text: 'Card title' }), title, h('small', { text: 'Optional. With a title the message is sent as a card.' }));
    const hookField = h('label', { class: 'field' }, h('span', { text: 'Hook name' }), hook);
    let res = null;
    const loadChannels = async () => {
      try {
        res = await run('servers.resources', { guild_id: guild.value });
        mount(channel, res.channels.filter((c) => c.kind === 'text').map((c) => h('option', { value: c.id, text: `#${c.name}`, selected: existing?.channel_id === c.id || null, disabled: c.send ? null : true })));
      } catch (error) {
        mount(channel, h('option', { value: '', text: error.message }));
      }
    };
    const showFields = () => {
      channelField.hidden = kind.value !== 'message';
      titleField.hidden = kind.value !== 'message';
      hookField.hidden = kind.value !== 'hook';
      messageField.hidden = kind.value === 'hook';
    };
    let timer = 0;
    const preview = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const p = await run('scheduler.preview', { cron: cron.value });
          mount(cronOut, p.ok ? `${p.text}. Next: ${p.runs.slice(0, 3).map((r) => shortStamp(Date.parse(r) / 1000)).join(', ')} (${p.timezone})` : p.error);
          cronOut.dataset.kind = p.ok ? '' : 'bad';
        } catch (error) {
          mount(cronOut, error.message);
        }
      }, 350);
    };
    guild.addEventListener('change', loadChannels);
    kind.addEventListener('change', showFields);
    cron.addEventListener('input', preview);
    loadChannels();
    showFields();
    preview();
    const result = await modal({
      title: existing ? `Edit ${existing.name}` : 'New scheduled task',
      wide: true,
      body: [
        h('label', { class: 'field' }, h('span', { text: 'Name' }), h('input', { name: 'name', required: true, maxlength: '100', value: existing?.name || '' })),
        h('div', { class: 'form-grid' },
          h('label', { class: 'field' }, h('span', { text: 'Server' }), guild),
          h('label', { class: 'field' }, h('span', { text: 'What it does' }), kind)),
        h('label', { class: 'field' }, h('span', { text: 'When (cron)' }), cron, cronOut,
          h('small', { text: 'minute hour day month weekday, for example 30 18 * * fri, or @daily and @hourly.' })),
        channelField, titleField, messageField, hookField,
        h('label', { class: 'field' }, h('span', { text: 'Stop after this many runs' }), maxRuns, h('small', { text: 'Empty or 0 runs forever.' })),
      ],
      actions: [{ label: 'Cancel', value: null }, {
        label: existing ? 'Save' : 'Create', primary: true, submit: true,
        run: (form) => run('scheduler.save', {
          id: existing?.id, guild_id: guild.value, name: String(form.get('name')).trim(), cron: cron.value.trim(), type: kind.value,
          channel_id: channel.value || 0, message: message.value, title: title.value, hook_name: hook.value,
          max_runs: Number(maxRuns.value || 0),
        }),
      }],
    }).done;
    clearTimeout(timer);
    if (result) {
      toast(existing ? 'Task saved.' : 'Task created.', { kind: 'ok' });
      loadTasks();
    }
  }

  function renderTasks() {
    if (!tasks) {
      return h('section', { class: 'card' }, h('div', { class: 'card-body' }, skeleton(5)));
    }
    const reason = blockedReason('scheduler', 'change scheduled tasks');
    const act = async (type, args, text) => {
      try {
        const t = approvalToast(text);
        try {
          await run(type, args, { onStatus: t.onStatus });
        } finally {
          t.note.close();
        }
        loadTasks();
      } catch (error) {
        failure(error);
      }
    };
    return [
      h('div', { class: 'market-bar' }, h('span', { class: 'muted', text: `Times are in ${tasks.timezone}.` }), h('span', { class: 'log-grow' }),
        button('New task', { class: 'btn btn-primary btn-sm', disabled: reason || !servers?.length ? true : null, title: reason || null, onClick: () => editTask(null) }, 'plus')),
      h('section', { class: 'card' }, h('div', { class: 'card-body' }, tasks.tasks.length ? table([
        { label: 'Task', render: (t) => h('div', { class: 'bk-name' }, h('strong', { text: t.name }), t.enabled ? null : pill('Off')) },
        { label: 'Server', render: (t) => t.guild || '-' },
        { label: 'When', render: (t) => h('span', { title: t.cron }, t.cron_text || h('code', { text: t.cron })) },
        { label: 'Does', render: (t) => (t.type === 'message' ? `Message to #${t.channel || '?'}` : t.type === 'hook' ? `Hook ${t.payload.hook_name}` : 'Log line') },
        { label: 'Next run', render: (t) => (t.enabled && t.next_run ? shortStamp(iso(t.next_run)) : '-') },
        { label: 'Runs', class: 'num', render: (t) => `${t.runs}${t.max_runs ? ` / ${t.max_runs}` : ''}` },
        { label: '', class: 'num', render: (t) => h('div', { class: 'row-actions' },
          button(t.enabled ? 'Pause' : 'Resume', { class: 'btn btn-sm', disabled: reason ? true : null, onClick: () => act('scheduler.toggle', { id: t.id, enabled: !t.enabled }, 'Saving') }),
          button('Run now', { class: 'btn btn-sm', disabled: reason ? true : null, onClick: () => act('scheduler.run', { id: t.id }, `Running ${t.name}`) }),
          button('Edit', { class: 'btn btn-sm', disabled: reason ? true : null, onClick: () => editTask(t) }),
          button('', { class: 'btn btn-sm', 'aria-label': `Delete ${t.name}`, title: 'Delete', disabled: reason ? true : null, onClick: async () => {
            if (await confirm('Delete task', `${t.name} stops and is removed.`, { label: 'Delete', danger: true })) {
              act('scheduler.delete', { id: t.id }, 'Deleting');
            }
          } }, 'trash')) },
      ], tasks.tasks) : empty('clock', 'No scheduled tasks', 'Post a message every Monday, emit a hook every hour, and so on.'))),
    ];
  }

  function render() {
    mount(body, tab === 'tasks' ? renderTasks() : renderAutomations());
  }

  async function loadGuild() {
    if (!guildId) {
      return;
    }
    const wanted = guildId;
    try {
      const [list, res] = await Promise.all([run('automations.list', { guild_id: wanted }), run('servers.resources', { guild_id: wanted })]);
      if (alive && wanted === guildId) {
        autos = list.automations;
        resources = res;
      }
    } catch (error) {
      if (alive) {
        mount(body, h('section', { class: 'card' }, empty('alert', 'Automations could not be loaded', error.message)));
        return;
      }
    }
    if (alive && tab === 'automations') {
      render();
    }
  }

  async function loadTasks() {
    try {
      tasks = await run('scheduler.list');
    } catch (error) {
      if (alive && tab === 'tasks') {
        mount(body, h('section', { class: 'card' }, empty('alert', 'Scheduled tasks could not be loaded', error.message)));
      }
      return;
    }
    if (alive && tab === 'tasks') {
      render();
    }
  }

  async function load() {
    render();
    try {
      const [list, cat] = await Promise.all([run('servers.list'), run('automations.catalogue').catch(() => null)]);
      servers = list.servers;
      catalogue = cat;
    } catch (error) {
      mount(body, h('section', { class: 'card' }, empty('alert', 'Automations could not be loaded', error.message)));
      return;
    }
    if (!servers.some((s) => s.id === guildId)) {
      guildId = servers[0]?.id || '';
    }
    fillPicker();
    render();
    loadGuild();
    loadTasks();
  }

  stops.push(on('bot', () => render()));
  stops.push(subscribe('meta', () => { if (servers) { render(); } }));
  load();

  return {
    update(params) {
      const next = params[0] === 'tasks' ? 'tasks' : 'automations';
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

