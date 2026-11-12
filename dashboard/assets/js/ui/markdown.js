import { h } from '../core/dom.js';
import { ago, stamp, time } from '../core/format.js';

const INLINE = new RegExp([
  '(`+)([\\s\\S]*?[^`])\\1(?!`)',
  '\\*\\*([\\s\\S]+?)\\*\\*(?!\\*)',
  '__([\\s\\S]+?)__(?!_)',
  '~~([\\s\\S]+?)~~',
  '\\|\\|([\\s\\S]+?)\\|\\|',
  '\\*([^\\s*][\\s\\S]*?)\\*(?!\\*)',
  '(?<![A-Za-z0-9])_([^\\s_][\\s\\S]*?)_(?![A-Za-z0-9])',
  '\\[([^\\]\\n]{1,300})\\]\\((https?:\\/\\/[^\\s)]{1,1000})\\)',
  '<(https?:\\/\\/[^\\s>]{1,1000})>',
  '(https?:\\/\\/[^\\s<]+[^\\s<.,;:!?)\\]\'"])',
  '<@!?(\\d{5,25})>',
  '<@&(\\d{5,25})>',
  '<#(\\d{5,25})>',
  '<(a?):([A-Za-z0-9_]{2,32}):(\\d{5,25})>',
  '<t:(-?\\d{1,13})(?::([tTdDfFR]))?>',
  '(@everyone|@here)',
].join('|'), 'g');

function link(url, children) {
  return h('a', { class: 'md-link', href: url, target: '_blank', rel: 'noopener noreferrer' }, children);
}

function mention(text, color = null) {
  const node = h('span', { class: 'md-mention', text });
  if (color) {
    node.style.setProperty('--mention', `#${color.toString(16).padStart(6, '0')}`);
    node.dataset.colored = 'true';
  }
  return node;
}

function timestamp(seconds, style) {
  const text = style === 'R' ? ago(seconds) : style === 't' || style === 'T' ? time(seconds, style === 'T') : stamp(seconds);
  return h('time', { class: 'md-time', title: stamp(seconds), text });
}

function inline(text, refs, depth = 0) {
  const out = [];
  if (!text) {
    return out;
  }
  if (depth > 6) {
    return [text];
  }
  let last = 0;
  INLINE.lastIndex = 0;
  const pattern = new RegExp(INLINE.source, 'g');
  let m;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) {
      out.push(text.slice(last, m.index));
    }
    last = pattern.lastIndex;
    const nested = (value) => inline(value, refs, depth + 1);
    if (m[1] !== undefined) {
      out.push(h('code', { class: 'md-code', text: m[2] }));
    } else if (m[3] !== undefined) {
      out.push(h('strong', null, nested(m[3])));
    } else if (m[4] !== undefined) {
      out.push(h('u', null, nested(m[4])));
    } else if (m[5] !== undefined) {
      out.push(h('s', null, nested(m[5])));
    } else if (m[6] !== undefined) {
      const spoiler = h('span', { class: 'md-spoiler', role: 'button', tabindex: '0', 'aria-label': 'Spoiler, activate to reveal' }, nested(m[6]));
      const reveal = () => spoiler.classList.add('revealed');
      spoiler.addEventListener('click', reveal);
      spoiler.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          reveal();
        }
      });
      out.push(spoiler);
    } else if (m[7] !== undefined) {
      out.push(h('em', null, nested(m[7])));
    } else if (m[8] !== undefined) {
      out.push(h('em', null, nested(m[8])));
    } else if (m[9] !== undefined) {
      out.push(link(m[10], nested(m[9])));
    } else if (m[11] !== undefined) {
      out.push(link(m[11], m[11]));
    } else if (m[12] !== undefined) {
      out.push(link(m[12], m[12]));
    } else if (m[13] !== undefined) {
      out.push(mention(`@${refs.users?.[m[13]] || 'unknown user'}`));
    } else if (m[14] !== undefined) {
      const role = refs.roles?.[m[14]];
      out.push(mention(`@${role?.name || 'unknown role'}`, role?.color || null));
    } else if (m[15] !== undefined) {
      out.push(mention(`#${refs.channels?.[m[15]] || 'unknown channel'}`));
    } else if (m[18] !== undefined) {
      out.push(h('img', {
        class: 'md-emoji', alt: `:${m[17]}:`, title: `:${m[17]}:`, loading: 'lazy', referrerpolicy: 'no-referrer',
        src: `https://cdn.discordapp.com/emojis/${m[18]}.${m[16] ? 'gif' : 'webp'}?size=48`,
      }));
    } else if (m[19] !== undefined) {
      out.push(timestamp(Number(m[19]), m[20] || 'f'));
    } else if (m[21] !== undefined) {
      out.push(mention(m[21]));
    }
  }
  if (last < text.length) {
    out.push(text.slice(last));
  }
  return out;
}

function lines(text, target, refs) {
  const rows = text.replace(/^\n+|\n+$/g, '').split('\n');
  if (rows.length === 1 && rows[0] === '') {
    return;
  }
  let plain = [];
  let list = null;
  let quote = [];
  const flushPlain = () => {
    if (plain.length) {
      target.appendChild(h('span', { class: 'md-text' }, inline(plain.join('\n'), refs)));
      plain = [];
    }
  };
  const flushQuote = () => {
    if (quote.length) {
      target.appendChild(h('blockquote', { class: 'md-quote' }, inline(quote.join('\n'), refs)));
      quote = [];
    }
  };
  const flush = () => {
    flushPlain();
    flushQuote();
    list = null;
  };
  for (const row of rows) {
    let m;
    if ((m = /^(#{1,3})\s+(.+)$/.exec(row))) {
      flush();
      target.appendChild(h('div', { class: `md-h md-h${m[1].length}` }, inline(m[2], refs)));
    } else if ((m = /^-#\s+(.+)$/.exec(row))) {
      flush();
      target.appendChild(h('div', { class: 'md-sub' }, inline(m[1], refs)));
    } else if ((m = /^>\s?(.*)$/.exec(row))) {
      flushPlain();
      list = null;
      quote.push(m[1]);
    } else if ((m = /^(\s*)(?:[-*]|(\d{1,9})\.)\s+(.+)$/.exec(row))) {
      flushPlain();
      flushQuote();
      const ordered = m[2] !== undefined;
      if (!list || list.dataset.ordered !== String(ordered)) {
        list = h(ordered ? 'ol' : 'ul', { class: 'md-list', dataset: { ordered: String(ordered) }, start: ordered ? m[2] : null });
        target.appendChild(list);
      }
      list.appendChild(h('li', null, inline(m[3], refs)));
    } else {
      flushQuote();
      list = null;
      plain.push(row);
    }
  }
  flush();
}

export function markdown(text, refs = {}) {
  const root = document.createDocumentFragment();
  const source = String(text || '');
  const fence = /```(?:([A-Za-z0-9_+#.-]{1,20})\n)?([\s\S]*?)```/g;
  let last = 0;
  let m;
  while ((m = fence.exec(source)) !== null) {
    lines(source.slice(last, m.index), root, refs);
    root.appendChild(h('pre', { class: 'md-pre' }, h('code', { text: m[2].replace(/^\n|\n$/g, '') })));
    last = fence.lastIndex;
  }
  lines(source.slice(last), root, refs);
  return root;
}

export function plain(text, limit = 140) {
  const flat = String(text || '').replace(/```[\s\S]*?```/g, ' [code] ').replace(/<a?:([A-Za-z0-9_]+):\d+>/g, ':$1:')
    .replace(/[*_~`|>#]/g, '').replace(/\s+/g, ' ').trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}
