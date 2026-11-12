import { run } from '../core/api.js';
import { button, clear, h, icon, mount } from '../core/dom.js';
import { bytes, initials } from '../core/format.js';
import { watch } from '../core/live.js';
import { replace } from '../core/router.js';
import { botAllows, can, on, session, subscribe } from '../core/store.js';
import { plain } from '../ui/markdown.js';
import { renderMessage, sameGroup } from '../ui/message.js';
import { confirm } from '../ui/modal.js';
import { arrive } from '../ui/motion.js';
import { empty, skeleton } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

const KIND_ICONS = { text: 'hash', news: 'megaphone', voice: 'volume', stage: 'volume', forum: 'forum' };
const QUICK = ['👍', '❤️', '😂', '🎉', '👀', '✅', '❌', '🔥'];
const MAX_FILES = 3;
const MAX_BYTES = 3 * 1024 * 1024;

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    return false;
  }
  return true;
}

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] || ''));
    reader.addEventListener('error', () => reject(new Error(`${file.name} could not be read.`)));
    reader.readAsDataURL(file);
  });
}

export default function chat(page, context) {
  const stops = [];
  let alive = true;
  let tree = null;
  let filter = '';
  let channelId = context.params[0] || recall('zdbf-chat-channel') || null;
  let channel = null;
  let messages = [];
  let more = false;
  let loading = false;
  let replyTo = null;
  let editing = null;
  let files = [];
  let unwatch = null;
  let unseen = 0;
  let request = 0;
  const handlers = new Map();

  function listen(id) {
    if (!handlers.has(id)) {
      handlers.set(id, on(`event:chat.${id}`, (event) => {
        if (id === channelId) {
          apply(event);
        }
      }));
    }
  }

  const search = h('input', { class: 'tree-search', type: 'text', placeholder: 'Find a channel', 'aria-label': 'Find a channel', autocomplete: 'off' });
  const treeBody = h('div', { class: 'tree-body' }, skeleton(8));
  const treePane = h('aside', { class: 'chat-tree' },
    h('div', { class: 'tree-head' }, search,
      h('button', { type: 'button', class: 'icon-btn', title: 'Reload channels', 'aria-label': 'Reload channels', onClick: () => loadTree(true) }, icon('refresh'))),
    treeBody);

  const title = h('div', { class: 'chat-title' });
  const scroll = h('div', { class: 'chat-scroll', tabindex: '0' });
  const list = h('div', { class: 'chat-list', role: 'log', 'aria-live': 'off' });
  const older = h('div', { class: 'chat-older' });
  const jump = h('button', { type: 'button', class: 'chat-jump', hidden: true, onClick: () => toBottom(true) });
  const composer = h('div', { class: 'composer-wrap' });
  scroll.append(older, list);
  const mainPane = h('section', { class: 'chat-main' },
    h('header', { class: 'chat-head' },
      h('button', { type: 'button', class: 'icon-btn chat-back', 'aria-label': 'Back to channels', onClick: () => { root.dataset.pane = 'tree'; } }, icon('left')),
      title),
    h('div', { class: 'chat-body' }, scroll, jump),
    composer);
  const root = h('div', { class: 'chat', dataset: { pane: channelId ? 'messages' : 'tree' } }, treePane, mainPane);
  page.appendChild(root);

  const allowed = can('chat.read') && botAllows('chat.read');

  function nearBottom() {
    return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120;
  }

  function toBottom(force = false) {
    if (force || nearBottom()) {
      scroll.scrollTop = scroll.scrollHeight;
      unseen = 0;
      jump.hidden = true;
    }
  }

  function findChannel(id) {
    if (!tree || !id) {
      return null;
    }
    for (const guild of tree.guilds) {
      const found = guild.channels.find((c) => c.id === id) || guild.threads.find((t) => t.id === id);
      if (found) {
        return { ...found, guild: guild.name };
      }
    }
    const dm = tree.dms.find((d) => d.id === id);
    return dm ? { ...dm, name: `@${dm.name}`, read: true, send: true, kind: 'dm', guild: null } : null;
  }

  function renderTree() {
    if (!tree) {
      return;
    }
    const query = filter.trim().toLowerCase();
    const match = (name) => !query || name.toLowerCase().includes(query);
    const row = (item, iconName, extra = '') => h('button', {
      type: 'button', class: `tree-item ${extra}`.trim(), disabled: item.read ? null : true,
      'aria-current': item.id === channelId ? 'true' : null,
      title: item.read ? item.name : 'The bot cannot read this channel',
      onClick: () => open(item.id),
    }, icon(item.read ? iconName : 'lock'), h('span', { text: item.name }));
    const sections = [];
    for (const guild of tree.guilds) {
      const rows = [];
      let category = Symbol('none');
      for (const item of guild.channels) {
        const threads = guild.threads.filter((t) => t.parent === item.id && !t.archived);
        const visibleThreads = threads.filter((t) => match(t.name));
        if (!match(item.name) && !visibleThreads.length) {
          continue;
        }
        if (item.category !== category) {
          category = item.category;
          if (category) {
            rows.push(h('div', { class: 'tree-category', text: category }));
          }
        }
        rows.push(item.kind === 'forum'
          ? h('div', { class: 'tree-item tree-static' }, icon('forum'), h('span', { text: item.name }))
          : row(item, KIND_ICONS[item.kind] || 'hash'));
        for (const thread of visibleThreads) {
          rows.push(row(thread, 'thread', 'tree-thread'));
        }
      }
      if (rows.length) {
        const badge = h('span', { class: 'avatar tree-icon', 'aria-hidden': 'true' }, initials(guild.name));
        if (guild.icon) {
          const img = h('img', { alt: '', referrerpolicy: 'no-referrer', src: guild.icon });
          img.addEventListener('load', () => badge.replaceChildren(img));
        }
        sections.push(h('section', { class: 'tree-guild' }, h('header', null, badge, h('strong', { text: guild.name })), rows));
      }
    }
    const dms = tree.dms.filter((d) => match(d.name));
    if (dms.length) {
      sections.push(h('section', { class: 'tree-guild' }, h('header', null, h('span', { class: 'avatar tree-icon' }, icon('user')), h('strong', { text: 'Direct messages' })),
        dms.map((d) => row({ ...d, name: d.name, read: true }, 'user'))));
    }
    mount(treeBody, sections.length ? sections : h('p', { class: 'muted tree-empty', text: query ? 'No channel matches.' : 'The bot is in no server yet.' }));
  }

  async function loadTree(announce = false) {
    try {
      tree = await run('chat.tree');
    } catch (error) {
      if (alive) {
        mount(treeBody, h('p', { class: 'muted tree-empty', text: error.message }));
      }
      return;
    }
    if (!alive) {
      return;
    }
    renderTree();
    renderTitle();
    if (announce) {
      toast('Channels reloaded.', { kind: 'ok' });
    }
  }

  function renderTitle() {
    const info = channel || findChannel(channelId);
    if (!info) {
      mount(title, h('strong', { text: 'Chat' }));
      return;
    }
    mount(title,
      icon(info.kind === 'dm' ? 'user' : KIND_ICONS[info.kind] || 'hash'),
      h('strong', { text: info.name.replace(/^#/, '') }),
      info.guild ? h('span', { class: 'muted', text: info.guild }) : null,
      info.topic ? h('span', { class: 'chat-topic', title: info.topic, text: plain(info.topic, 120) }) : null);
  }

  function reactTo(message, emoji, remove) {
    run('chat.react', { channel_id: channelId, message_id: message.id, emoji, remove }).catch(failure);
  }

  function reactionPicker(message, anchor) {
    document.querySelector('.react-pop')?.remove();
    const input = h('input', { type: 'text', placeholder: 'Other emoji', 'aria-label': 'Other emoji', maxlength: '60' });
    const pop = h('div', { class: 'react-pop', role: 'dialog', 'aria-label': 'React as the bot' },
      h('div', { class: 'react-quick' }, QUICK.map((emoji) => h('button', { type: 'button', class: 'react-emoji', text: emoji, onClick: () => { pop.remove(); reactTo(message, emoji, false); } }))),
      input);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && input.value.trim()) {
        pop.remove();
        reactTo(message, input.value.trim(), false);
      } else if (event.key === 'Escape') {
        pop.remove();
      }
    });
    const box = anchor.getBoundingClientRect();
    document.body.appendChild(pop);
    pop.style.setProperty('top', `${Math.max(8, box.top - pop.offsetHeight - 6)}px`);
    pop.style.setProperty('left', `${Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, box.right - pop.offsetWidth))}px`);
    const close = (event) => {
      if (!pop.contains(event.target)) {
        pop.remove();
        document.removeEventListener('pointerdown', close, true);
      }
    };
    document.addEventListener('pointerdown', close, true);
  }

  async function remove(message) {
    const yes = await confirm('Delete this message?', plain(message.content, 160) || 'The message is removed from Discord.', { label: 'Delete', danger: true });
    if (!yes) {
      return;
    }
    try {
      await run(message.own ? 'chat.delete' : 'chat.delete_any', { channel_id: channelId, message_id: message.id });
    } catch (error) {
      failure(error);
    }
  }

  function toolsFor(message) {
    const sendOk = can('chat.send') && botAllows('chat.send');
    const moderate = can('chat.moderate') && botAllows('chat.moderate') && channel?.can?.manage;
    return [
      sendOk && channel?.can?.send ? { icon: 'reply', label: 'Reply', run: () => { editing = null; replyTo = message; renderComposer(); } } : null,
      sendOk && channel?.can?.react ? { icon: 'smile', label: 'React', run: (anchor) => reactionPicker(message, anchor) } : null,
      sendOk && message.own && message.content && !message.card ? { icon: 'edit', label: 'Edit', run: () => { replyTo = null; editing = message; renderComposer(); } } : null,
      moderate ? { icon: 'pin', label: message.pinned ? 'Unpin' : 'Pin', run: () => run('chat.pin', { channel_id: channelId, message_id: message.id, unpin: message.pinned }).catch(failure) } : null,
      (sendOk && message.own) || moderate ? { icon: 'trash', label: 'Delete', danger: true, run: () => remove(message) } : null,
    ];
  }

  function node(message, index) {
    const sendOk = can('chat.send') && botAllows('chat.send') && channel?.can?.react;
    return renderMessage(message, {
      compact: sameGroup(messages[index - 1], message),
      tools: toolsFor(message),
      onReact: sendOk ? (emoji, mine) => reactTo(message, emoji, mine) : null,
    });
  }

  function renderList() {
    clear(list);
    if (!messages.length) {
      list.appendChild(h('p', { class: 'muted chat-empty', text: 'No messages here yet.' }));
    }
    messages.forEach((message, index) => list.appendChild(node(message, index)));
    mount(older, more ? button('Load older messages', { class: 'btn btn-sm', onClick: loadOlder }) : null);
  }

  function refresh(index) {
    for (const i of [index, index + 1]) {
      const message = messages[i];
      const current = message ? list.querySelector(`[data-id="${message.id}"]`) : null;
      if (message && current) {
        current.replaceWith(node(message, i));
      }
    }
  }

  function upsert(message, fromEvent = false) {
    const index = messages.findIndex((m) => m.id === message.id);
    if (index >= 0) {
      if (!message.reactions?.length && messages[index].reactions?.length && fromEvent) {
        message.reactions = messages[index].reactions;
      }
      messages[index] = message;
      refresh(index);
      return;
    }
    const stick = nearBottom();
    list.querySelector('.chat-empty')?.remove();
    messages.push(message);
    const fresh = node(message, messages.length - 1);
    list.appendChild(fresh);
    arrive(fresh);
    if (stick || message.own) {
      toBottom(true);
    } else {
      unseen++;
      jump.textContent = `${unseen} new message${unseen === 1 ? '' : 's'}`;
      jump.hidden = false;
    }
  }

  function apply(event) {
    const data = event.data;
    if (!data) {
      return;
    }
    if (data.type === 'message' || data.type === 'edit') {
      if (data.type === 'edit' && !messages.some((m) => m.id === data.message.id)) {
        return;
      }
      upsert(data.message, true);
    } else if (data.type === 'delete') {
      for (const id of data.ids) {
        const index = messages.findIndex((m) => m.id === id);
        if (index >= 0) {
          messages.splice(index, 1);
          list.querySelector(`[data-id="${id}"]`)?.remove();
          refresh(index);
        }
      }
    } else if (data.type === 'reaction' || data.type === 'reactions_cleared') {
      const index = messages.findIndex((m) => m.id === data.id);
      if (index < 0) {
        return;
      }
      const message = messages[index];
      if (data.type === 'reactions_cleared') {
        message.reactions = [];
      } else {
        const found = message.reactions.find((r) => r.emoji === data.emoji);
        if (found) {
          found.count += data.delta;
          if (data.me) {
            found.me = data.delta > 0;
          }
          message.reactions = message.reactions.filter((r) => r.count > 0);
        } else if (data.delta > 0) {
          message.reactions.push({ emoji: data.emoji, id: data.emoji_id, name: data.name, animated: data.animated, count: 1, me: data.me });
        }
      }
      refresh(index);
    }
  }

  async function loadOlder() {
    if (loading || !messages.length) {
      return;
    }
    loading = true;
    const mine = request;
    const height = scroll.scrollHeight;
    try {
      const data = await run('chat.history', { channel_id: channelId, before: messages[0].id, limit: 40 });
      if (!alive || mine !== request) {
        return;
      }
      messages = data.messages.concat(messages);
      more = data.more;
      renderList();
      scroll.scrollTop = scroll.scrollHeight - height;
    } catch (error) {
      failure(error);
    } finally {
      loading = false;
    }
  }

  function renderComposer() {
    clear(composer);
    if (!channel) {
      return;
    }
    let reason = '';
    if (!can('chat.send')) {
      reason = 'Your role can read this chat but not write in it.';
    } else if (!botAllows('chat.send')) {
      reason = 'Sending is switched off on the bot (capability chat.send).';
    } else if (!channel.can.send) {
      reason = 'The bot is not allowed to send messages in this channel.';
    }
    if (reason) {
      composer.appendChild(h('p', { class: 'composer-off', text: reason }));
      return;
    }
    const input = h('textarea', {
      class: 'composer-input', rows: '1', maxlength: '2000', 'aria-label': 'Message',
      placeholder: editing ? 'Edit the message' : `Message ${channel.name.startsWith('@') ? channel.name : `#${channel.name}`} as the bot`,
    });
    if (editing) {
      input.value = editing.content;
    }
    const grow = () => {
      input.style.setProperty('height', 'auto');
      input.style.setProperty('height', `${Math.min(input.scrollHeight, 180)}px`);
    };
    const picker = h('input', { type: 'file', multiple: true, hidden: true });
    const chips = h('div', { class: 'composer-files' });
    const drawFiles = () => mount(chips, files.map((file, index) => h('span', { class: 'file-chip' }, icon('file'),
      h('span', { class: 'file-name', text: file.name }), h('small', { text: bytes(file.size) }),
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': `Remove ${file.name}`, onClick: () => { files.splice(index, 1); drawFiles(); } }, icon('x')))));
    picker.addEventListener('change', () => {
      const next = files.concat([...picker.files]);
      picker.value = '';
      if (next.length > MAX_FILES || next.reduce((sum, f) => sum + f.size, 0) > MAX_BYTES) {
        toast(`Attach up to ${MAX_FILES} files, ${MAX_BYTES / 1048576} MB in total.`, { kind: 'warn' });
        return;
      }
      files = next;
      drawFiles();
    });
    const sendButton = h('button', { type: 'button', class: 'btn btn-primary composer-send', title: 'Send', 'aria-label': editing ? 'Save' : 'Send' }, icon(editing ? 'check' : 'send'));
    const cancel = () => {
      replyTo = null;
      editing = null;
      renderComposer();
    };
    const submit = async () => {
      const content = input.value.trim();
      if (!content && !files.length) {
        return;
      }
      sendButton.disabled = true;
      try {
        if (editing) {
          const result = await run('chat.edit', { channel_id: channelId, message_id: editing.id, content });
          upsert(result.message);
        } else {
          const payload = { channel_id: channelId, content, reply_to: replyTo?.id || 0 };
          if (files.length) {
            payload.files = await Promise.all(files.map(async (file) => ({ name: file.name, data: await toBase64(file) })));
          }
          const result = await run('chat.send', payload, { onStatus: (status) => {
            if (status === 'awaiting_approval') {
              toast('Waiting for the bot owner to approve this in Discord.', { kind: 'info' });
            }
          } });
          upsert(result.message);
        }
        files = [];
        replyTo = null;
        editing = null;
        renderComposer();
      } catch (error) {
        failure(error);
        sendButton.disabled = false;
      }
    };
    sendButton.addEventListener('click', submit);
    input.addEventListener('input', grow);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit();
      } else if (event.key === 'Escape' && (replyTo || editing)) {
        cancel();
      }
    });
    const banner = replyTo || editing
      ? h('div', { class: 'composer-banner' }, icon(editing ? 'edit' : 'reply'),
        h('span', null, editing ? 'Editing a message' : ['Replying to ', h('strong', { text: replyTo.author.name })]),
        h('span', { class: 'muted composer-excerpt', text: plain((editing || replyTo).content, 90) }),
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Cancel', onClick: cancel }, icon('x')))
      : null;
    composer.append(...[banner, chips, h('div', { class: 'composer' },
      !editing && channel.can.attach ? h('button', { type: 'button', class: 'icon-btn', title: 'Attach files', 'aria-label': 'Attach files', onClick: () => picker.click() }, icon('clip')) : null,
      picker, input, sendButton)].filter(Boolean));
    drawFiles();
    grow();
    if (window.matchMedia('(min-width: 901px)').matches) {
      input.focus();
    }
  }

  async function open(id) {
    if (!id) {
      return;
    }
    const mine = ++request;
    listen(id);
    channelId = id;
    channel = null;
    messages = [];
    more = false;
    replyTo = null;
    editing = null;
    files = [];
    unseen = 0;
    jump.hidden = true;
    root.dataset.pane = 'messages';
    remember('zdbf-chat-channel', id);
    replace(`chat/${id}`);
    renderTree();
    renderTitle();
    clear(composer);
    mount(older);
    mount(list, skeleton(6));
    unwatch?.();
    unwatch = watch([`chat.${id}`]);
    try {
      const data = await run('chat.history', { channel_id: id, limit: 40 });
      if (!alive || mine !== request) {
        return;
      }
      const known = findChannel(id) || {};
      channel = { ...known, ...data.channel, kind: known.kind || 'text' };
      messages = data.messages;
      more = data.more;
      renderTitle();
      renderList();
      renderComposer();
      toBottom(true);
    } catch (error) {
      if (alive && mine === request) {
        mount(list, empty('alert', 'This channel could not be opened', error.message));
      }
    }
  }

  if (!allowed) {
    mount(page, empty('lock', 'Chat is not available',
      can('chat.read') ? 'Reading chat is switched off on the bot (capability chat.read).' : 'Your role cannot read chat.'));
    return null;
  }

  search.addEventListener('input', () => {
    filter = search.value;
    renderTree();
  });
  list.addEventListener('click', (event) => {
    if (event.target.closest('a, button, .md-spoiler')) {
      return;
    }
    const picked = event.target.closest('.msg');
    for (const node of list.querySelectorAll('.msg.active')) {
      if (node !== picked) {
        node.classList.remove('active');
      }
    }
    picked?.classList.toggle('active');
  });
  scroll.addEventListener('scroll', () => {
    if (nearBottom()) {
      unseen = 0;
      jump.hidden = true;
    }
  });
  stops.push(on('bot', () => renderComposer()));
  stops.push(subscribe('meta', () => renderComposer()));

  if (!session.bot.online) {
    mount(list, empty('clock', 'The bot is offline', 'Chat needs the bot to be connected.'));
  }
  loadTree().then(() => {
    if (alive && channelId) {
      open(channelId);
    } else if (alive) {
      mount(list, empty('chat', 'Pick a channel', 'Choose a server channel on the left to read and write as the bot.'));
    }
  });

  return {
    update(params) {
      if (params[0] && params[0] !== channelId) {
        open(params[0]);
      }
    },
    destroy() {
      alive = false;
      unwatch?.();
      document.querySelector('.react-pop')?.remove();
      for (const stop of handlers.values()) {
        stop();
      }
      stops.forEach((stop) => stop());
    },
  };
}
