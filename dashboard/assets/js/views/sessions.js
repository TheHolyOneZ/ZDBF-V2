import { get, post, url } from '../core/api.js';
import { button, h, mount } from '../core/dom.js';
import { ago, stamp } from '../core/format.js';
import { confirm } from '../ui/modal.js';
import { card, pageHead, pill, segmented, skeleton, table } from '../ui/parts.js';
import { failure, toast } from '../ui/toast.js';

function device(agent) {
  const text = agent || '';
  const browser = /Firefox\//.test(text) ? 'Firefox' : /Edg\//.test(text) ? 'Edge' : /OPR\//.test(text) ? 'Opera'
    : /Chrome\//.test(text) ? 'Chrome' : /Safari\//.test(text) ? 'Safari' : 'Unknown browser';
  const system = /Windows/.test(text) ? 'Windows' : /Android/.test(text) ? 'Android' : /iPhone|iPad/.test(text) ? 'iOS'
    : /Mac OS X/.test(text) ? 'macOS' : /Linux/.test(text) ? 'Linux' : '';
  return system ? `${browser} on ${system}` : browser;
}

export default function sessions(page) {
  let all = false;
  let alive = true;
  const box = card(null);
  const tools = h('div', { class: 'page-actions' });
  page.append(pageHead('Sessions', 'Browsers that are logged in to this dashboard.', tools), box.el);

  async function revoke(row) {
    try {
      const data = await post('api/sessions.php', { action: 'revoke', key: row.key });
      if (data.self) {
        window.location.assign(url('login.php?e=out'));
        return;
      }
      toast('The session was ended.', { kind: 'ok' });
      load();
    } catch (error) {
      failure(error);
    }
  }

  async function load() {
    mount(box.body, skeleton(4));
    let data;
    try {
      data = await get('api/sessions.php', { all: all ? '1' : null });
    } catch (error) {
      failure(error);
      return;
    }
    if (!alive) {
      return;
    }
    const others = button('Log out everywhere else', { onClick: async () => {
      if (!(await confirm('Log out everywhere else?', 'Every other browser logged in to your account has to log in again.', { label: 'Log out the others' }))) {
        return;
      }
      try {
        const result = await post('api/sessions.php', { action: 'revoke_others' });
        toast(result.count ? `${result.count} other session${result.count === 1 ? '' : 's'} ended.` : 'There were no other sessions.', { kind: 'ok' });
        load();
      } catch (error) {
        failure(error);
      }
    } }, 'logout');
    const scope = data.can_see_all
      ? segmented([{ value: 'mine', label: 'Mine' }, { value: 'all', label: 'Everyone' }], all ? 'all' : 'mine', (next) => { all = next === 'all'; load(); }, 'Whose sessions').el
      : null;
    mount(tools, scope, others);
    mount(box.body, table([
      { label: 'Browser', render: (s) => h('span', null, device(s.agent), s.current ? h('span', { class: 'gap' }, pill('This browser', 'ok')) : null) },
      all ? { label: 'User', render: (s) => s.user } : null,
      { label: 'Address', render: (s) => h('span', { class: 'muted', text: s.ip || '' }) },
      { label: 'Logged in', render: (s) => stamp(s.created_at) },
      { label: 'Last active', render: (s) => ago(s.seen_at) },
      { label: '', class: 'actions', render: (s) => button(s.current ? 'Log out' : 'End', { class: 'btn btn-sm', onClick: () => revoke(s) }) },
    ].filter(Boolean), data.sessions));
  }

  load();
  return () => { alive = false; };
}
