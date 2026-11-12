const number = new Intl.NumberFormat('en-US');
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });
const clockSeconds = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const dateTime = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const shortDateTime = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export function num(value) {
  return value == null || Number.isNaN(value) ? '-' : number.format(value);
}

export function compact(value) {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  return Math.abs(value) < 10000 ? number.format(Math.round(value * 10) / 10) : compactFormat.format(value);
}

export function fixed(value, digits = 1) {
  return value == null || Number.isNaN(value) ? '-' : Number(value).toFixed(digits);
}

export function bytes(value) {
  if (value == null) {
    return '-';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return `${unit === 0 ? size : size.toFixed(size >= 100 ? 0 : 1)} ${units[unit]}`;
}

export function duration(seconds) {
  if (seconds == null) {
    return '-';
  }
  let rest = Math.max(0, Math.floor(seconds));
  const parts = [];
  for (const [suffix, size] of [['d', 86400], ['h', 3600], ['m', 60], ['s', 1]]) {
    const value = Math.floor(rest / size);
    rest -= value * size;
    if (value || (suffix === 's' && !parts.length)) {
      parts.push(`${value}${suffix}`);
    }
  }
  return parts.slice(0, 2).join(' ');
}

export function ago(timestamp, now = Date.now() / 1000) {
  if (!timestamp) {
    return 'never';
  }
  const diff = Math.max(0, now - timestamp);
  if (diff < 5) {
    return 'just now';
  }
  if (diff < 60) {
    return `${Math.floor(diff)}s ago`;
  }
  if (diff < 3600) {
    return `${Math.floor(diff / 60)}m ago`;
  }
  if (diff < 86400) {
    return `${Math.floor(diff / 3600)}h ago`;
  }
  return `${Math.floor(diff / 86400)}d ago`;
}

export function time(timestamp, seconds = false) {
  return timestamp ? (seconds ? clockSeconds : clock).format(new Date(timestamp * 1000)) : '-';
}

export function stamp(timestamp) {
  return timestamp ? dateTime.format(new Date(timestamp * 1000)) : '-';
}

export function shortStamp(timestamp) {
  return timestamp ? shortDateTime.format(new Date(timestamp * 1000)) : '-';
}

export function initials(name) {
  const clean = String(name || '?').replace(/[^\p{L}\p{N} ]/gu, ' ').trim();
  const parts = clean.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '?') + (parts[1]?.[0] || '')).toUpperCase();
}
