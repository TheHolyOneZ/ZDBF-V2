const topics = new Map();
const listeners = new Map();

export const session = {
  user: null,
  csrf: '',
  version: '',
  hold: 20,
  oauth: false,
  capabilities: { bot: [], web: [] },
  bot: { paired: false, online: false, seen_at: null },
  connection: 'ok',
};

export const bus = new EventTarget();

export function emit(name, detail) {
  bus.dispatchEvent(new CustomEvent(name, { detail }));
}

export function on(name, handler) {
  const wrapped = (event) => handler(event.detail);
  bus.addEventListener(name, wrapped);
  return () => bus.removeEventListener(name, wrapped);
}

export function topic(name) {
  return topics.get(name)?.data ?? null;
}

export function topicAge(name) {
  return topics.get(name)?.at ?? null;
}

export function setTopic(name, entry) {
  topics.set(name, entry);
  for (const handler of listeners.get(name) || []) {
    handler(entry.data, entry);
  }
}

export function subscribe(name, handler) {
  if (!listeners.has(name)) {
    listeners.set(name, new Set());
  }
  listeners.get(name).add(handler);
  const current = topics.get(name);
  if (current) {
    handler(current.data, current);
  }
  return () => listeners.get(name)?.delete(handler);
}

export function can(capability) {
  const caps = session.user?.capabilities || [];
  return caps.includes('*') || caps.includes(capability);
}

export function botAllows(capability) {
  const meta = topic('meta');
  const entry = meta?.capabilities?.find((item) => item.name === capability);
  return Boolean(entry?.active);
}
