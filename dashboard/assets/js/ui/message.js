import { h, icon } from '../core/dom.js';
import { bytes, initials, stamp, time } from '../core/format.js';
import { markdown, plain } from './markdown.js';

const IMAGE_MAX_W = 420;
const IMAGE_MAX_H = 300;

function hex(color) {
  return typeof color === 'number' && color > 0 ? `#${color.toString(16).padStart(6, '0')}` : null;
}

function safeUrl(url) {
  return typeof url === 'string' && /^https:\/\//.test(url) ? url : null;
}

function image(url, alt, extra = '', width = null, height = null) {
  const src = safeUrl(url);
  if (!src) {
    return null;
  }
  const img = h('img', { class: `msg-image ${extra}`.trim(), alt: alt || '', loading: 'lazy', referrerpolicy: 'no-referrer', src });
  if (width && height) {
    const scale = Math.min(1, IMAGE_MAX_W / width, IMAGE_MAX_H / height);
    img.width = Math.round(width * scale);
    img.height = Math.round(height * scale);
  }
  return h('a', { class: 'msg-image-link', href: src, target: '_blank', rel: 'noopener noreferrer' }, img);
}

function fileChip(url, name, size) {
  const href = safeUrl(url);
  return h(href ? 'a' : 'span', { class: 'file-chip', href, target: href ? '_blank' : null, rel: href ? 'noopener noreferrer' : null },
    icon('file'), h('span', { class: 'file-name', text: name || 'file' }), size ? h('small', { text: bytes(size) }) : null);
}

function avatar(user) {
  const node = h('span', { class: 'avatar msg-avatar', 'aria-hidden': 'true' }, initials(user.name));
  const src = safeUrl(user.avatar);
  if (src) {
    const img = h('img', { alt: '', referrerpolicy: 'no-referrer', src });
    img.addEventListener('load', () => node.replaceChildren(img));
  }
  return node;
}

export function renderComponents(nodes, refs) {
  return (nodes || []).map((node) => {
    switch (node.t) {
      case 'container': {
        const card = h('div', { class: 'dc-card' }, renderComponents(node.items, refs));
        const accent = hex(node.accent);
        if (accent) {
          card.style.setProperty('--card-accent', accent);
          card.dataset.accent = 'true';
        }
        return card;
      }
      case 'section':
        return h('div', { class: 'dc-section' },
          h('div', { class: 'dc-section-text' }, renderComponents(node.items, refs)),
          node.accessory ? h('div', { class: 'dc-accessory' }, renderComponents([node.accessory], refs)) : null);
      case 'text':
        return h('div', { class: 'dc-text md' }, markdown(node.content, refs));
      case 'sep':
        return h('hr', { class: node.visible ? 'dc-sep' : 'dc-gap' });
      case 'thumb':
        return image(node.url, node.alt, 'msg-thumb');
      case 'gallery':
        return h('div', { class: 'dc-gallery' }, (node.items || []).map((item) => image(item.url, item.alt)));
      case 'file':
        return fileChip(node.url, node.name, node.size);
      case 'row':
        return h('div', { class: 'dc-row' }, renderComponents(node.items, refs));
      case 'button': {
        const url = safeUrl(node.url);
        const label = [node.emoji && !node.emoji.startsWith('<') ? `${node.emoji} ` : '', node.label || ''].join('').trim() || 'Button';
        return url
          ? h('a', { class: 'dc-button', dataset: { style: 'link' }, href: url, target: '_blank', rel: 'noopener noreferrer' }, label, icon('external'))
          : h('span', { class: 'dc-button', dataset: { style: node.style, off: String(Boolean(node.disabled)) }, title: 'Buttons are used in Discord' }, label);
      }
      case 'select':
        return h('span', { class: 'dc-select', title: 'Menus are used in Discord' }, h('span', { text: node.placeholder || 'Select' }), icon('down'));
      default:
        return h('span', { class: 'dc-unknown', text: 'Unsupported element' });
    }
  });
}

function embed(data, refs) {
  const box = h('div', { class: 'dc-embed' });
  const color = hex(data.color);
  if (color) {
    box.style.setProperty('--card-accent', color);
    box.dataset.accent = 'true';
  }
  const titleUrl = safeUrl(data.url);
  box.append(...[
    data.author ? h('div', { class: 'dc-embed-author', text: data.author.name }) : null,
    data.title ? h(titleUrl ? 'a' : 'div', { class: 'dc-embed-title', href: titleUrl, target: titleUrl ? '_blank' : null, rel: titleUrl ? 'noopener noreferrer' : null }, markdown(data.title, refs)) : null,
    data.description ? h('div', { class: 'md' }, markdown(data.description, refs)) : null,
    data.fields?.length ? h('div', { class: 'dc-fields' }, data.fields.map((field) => h('div', { class: 'dc-field', dataset: { inline: String(field.inline) } },
      h('div', { class: 'dc-field-name' }, markdown(field.name, refs)), h('div', { class: 'md' }, markdown(field.value, refs))))) : null,
    image(data.image, ''),
    data.footer || data.at ? h('div', { class: 'dc-embed-foot', text: [data.footer, data.at ? stamp(data.at) : null].filter(Boolean).join(' · ') }) : null,
  ].filter(Boolean));
  const thumb = image(data.thumbnail, '', 'msg-thumb');
  return thumb ? h('div', { class: 'dc-embed-wrap' }, box, thumb) : box;
}

function reactionChip(reaction, onReact) {
  const face = reaction.id
    ? h('img', { class: 'md-emoji', alt: `:${reaction.name}:`, loading: 'lazy', referrerpolicy: 'no-referrer',
      src: `https://cdn.discordapp.com/emojis/${reaction.id}.${reaction.animated ? 'gif' : 'webp'}?size=48` })
    : h('span', { text: reaction.emoji });
  return h('button', {
    type: 'button', class: 'reaction', 'aria-pressed': String(Boolean(reaction.me)), disabled: onReact ? null : true,
    title: reaction.me ? 'Remove the bot\'s reaction' : 'React as the bot',
    onClick: () => onReact?.(reaction.id ? `${reaction.animated ? 'a' : ''}:${reaction.name}:${reaction.id}` : reaction.emoji, Boolean(reaction.me)),
  }, face, h('span', { class: 'reaction-count', text: String(reaction.count) }));
}

export function renderMessage(message, options = {}) {
  const refs = message.mentions || {};
  if (message.system) {
    return h('article', { class: 'msg msg-system', dataset: { id: message.id } },
      icon('info'), h('span', { class: 'msg-system-text' }, h('strong', { text: message.author.name }), ` ${message.system}`),
      h('time', { title: stamp(message.at), text: time(message.at) }));
  }
  const author = h('strong', { class: 'msg-author', text: message.author.name });
  const color = hex(message.author.color);
  if (color) {
    author.style.setProperty('--author', color);
    author.dataset.colored = 'true';
  }
  const body = [];
  if (message.content) {
    body.push(h('div', { class: 'msg-content md' }, markdown(message.content, refs),
      message.edited_at ? h('span', { class: 'msg-edited', title: stamp(message.edited_at), text: ' (edited)' }) : null));
  }
  const media = (message.attachments || []).map((a) => ((a.type || '').startsWith('image/') || (a.w && a.h && !(a.type || '').startsWith('video/'))
    ? (a.spoiler ? fileChip(a.url, `Spoiler: ${a.name}`, a.size) : image(a.url, a.name, '', a.w, a.h))
    : fileChip(a.url, a.name, a.size)));
  if (media.length) {
    body.push(h('div', { class: 'msg-attachments' }, media));
  }
  for (const item of message.embeds || []) {
    body.push(embed(item, refs));
  }
  if (message.components?.length) {
    body.push(h('div', { class: 'dc-components' }, renderComponents(message.components, refs)));
  }
  for (const sticker of message.stickers || []) {
    body.push(h('span', { class: 'file-chip', text: `Sticker: ${sticker.name}` }));
  }
  if (message.reactions?.length) {
    body.push(h('div', { class: 'msg-reactions' }, message.reactions.map((r) => reactionChip(r, options.onReact))));
  }
  const tools = (options.tools || []).filter(Boolean).map((tool) => h('button', {
    type: 'button', class: 'icon-btn msg-tool', title: tool.label, 'aria-label': tool.label, dataset: { danger: String(Boolean(tool.danger)) },
    onClick: (event) => tool.run(event.currentTarget),
  }, icon(tool.icon)));
  const openUrl = safeUrl(message.url);
  if (openUrl) {
    tools.push(h('a', { class: 'icon-btn msg-tool', href: openUrl, target: '_blank', rel: 'noopener noreferrer', title: 'Open in Discord', 'aria-label': 'Open in Discord' }, icon('external')));
  }
  return h('article', { class: `msg ${options.compact ? 'msg-compact' : ''} ${message.own ? 'msg-own' : ''}`.trim(), dataset: { id: message.id } },
    message.reply ? h('div', { class: 'msg-reply' }, icon('reply'),
      h('strong', { text: message.reply.author || 'a message' }), h('span', { text: message.reply.excerpt ? plain(message.reply.excerpt, 110) : 'Open the original in Discord' })) : null,
    h('div', { class: 'msg-gutter' }, options.compact
      ? h('time', { class: 'msg-hover-time', title: stamp(message.at), text: time(message.at) })
      : avatar(message.author)),
    h('div', { class: 'msg-main' },
      options.compact ? null : h('header', { class: 'msg-head' }, author,
        message.author.bot ? h('span', { class: 'msg-tag', text: 'Bot' }) : null,
        h('time', { title: stamp(message.at), text: stamp(message.at) }),
        message.pinned ? h('span', { class: 'msg-pin', title: 'Pinned' }, icon('pin')) : null),
      body),
    tools.length ? h('div', { class: 'msg-tools' }, tools) : null);
}

export function sameGroup(previous, message) {
  return Boolean(previous) && !previous.system && !message.system && !message.reply
    && previous.author.id === message.author.id && message.at - previous.at < 420;
}
