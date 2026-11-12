import { session } from './store.js';

const base = document.querySelector('meta[name="zdbf-base"]')?.content || '';
const FINAL = new Set(['done', 'error', 'denied', 'expired']);

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || 'The request failed.');
    this.status = status;
    this.code = code;
  }
}

export function url(path) {
  return `${base}/${path.replace(/^\//, '')}`;
}

async function parse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (response.status === 401 && data?.error === 'auth') {
    window.location.assign(url('login.php'));
    throw new ApiError(401, 'auth', 'Your session ended.');
  }
  if (!response.ok || !data || data.ok === false) {
    throw new ApiError(response.status, data?.error || 'http', data?.message || `The website answered with HTTP ${response.status}.`);
  }
  return data;
}

export async function get(path, params = {}, options = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null) {
      query.set(key, String(value));
    }
  }
  const text = query.toString();
  const response = await fetch(url(path) + (text ? `?${text}` : ''), {
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  });
  return parse(response);
}

export async function post(path, body = {}) {
  const response = await fetch(url(path), {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf },
    body: JSON.stringify(body),
  });
  return parse(response);
}

export async function run(type, args = {}, options = {}) {
  const queued = await post('api/command.php', { type, args });
  const deadline = Date.now() + (options.timeout || 20 * 60 * 1000);
  let since = '';
  let note = '';
  while (Date.now() < deadline) {
    const result = await get('api/result.php', { id: queued.id, since, note });
    if (FINAL.has(result.status)) {
      if (result.status === 'done') {
        return result.data;
      }
      throw new ApiError(200, result.status, result.message || 'The bot could not run this.');
    }
    const told = result.note || '';
    if (result.status !== since || told !== note) {
      since = result.status;
      note = told;
      options.onStatus?.(result.status, told);
    }
  }
  throw new ApiError(200, 'timeout', 'The bot did not answer in time.');
}
