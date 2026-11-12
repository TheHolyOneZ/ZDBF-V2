import { add, button, h, icon } from '../core/dom.js';
import { refract } from './refract.js';

export function modal(options) {
  const dialog = h('dialog', { class: `modal ${options.wide ? 'modal-wide' : ''}`.trim(), 'aria-labelledby': 'modal-title' });
  const body = h('div', { class: 'modal-body' });
  const foot = h('div', { class: 'modal-foot' });
  const error = h('p', { class: 'form-error', role: 'alert', hidden: true });
  let settled = false;
  let resolve;
  const done = new Promise((r) => { resolve = r; });

  function close(value = null) {
    if (settled) {
      return;
    }
    settled = true;
    dialog.classList.add('leaving');
    setTimeout(() => {
      lens();
      dialog.close();
      dialog.remove();
      resolve(value);
    }, 140);
  }

  function fail(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  const form = h('form', { class: 'modal-card', method: 'dialog', novalidate: true },
    h('header', { class: 'modal-head' },
      h('h2', { id: 'modal-title', text: options.title }),
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Close', onClick: () => close(null) }, icon('x'))),
    body, error, foot);
  dialog.appendChild(form);
  add(body, options.body);
  const actions = options.actions || [{ label: 'Close' }];
  for (const action of actions) {
    const node = button(action.label, {
      class: `btn ${action.primary ? 'btn-primary' : ''} ${action.danger ? 'btn-danger' : ''}`.trim(),
      type: action.submit ? 'submit' : 'button',
    });
    if (!action.submit) {
      node.addEventListener('click', () => close(action.value ?? null));
    }
    foot.appendChild(node);
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = actions.find((a) => a.submit);
    if (!submit) {
      return;
    }
    if (!form.reportValidity()) {
      return;
    }
    const trigger = foot.querySelector('button[type="submit"]');
    trigger.disabled = true;
    fail('');
    try {
      const value = await submit.run(new FormData(form), form);
      close(value ?? true);
    } catch (problem) {
      fail(problem?.message || 'That did not work.');
      trigger.disabled = false;
    }
  });
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close(null);
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      close(null);
    }
  });
  const active = document.activeElement;
  const trigger = active instanceof HTMLElement && active !== document.body ? active.getBoundingClientRect() : null;
  document.body.appendChild(dialog);
  dialog.showModal();
  const lens = refract(form, { rim: 24, scale: 56 });
  if (trigger && trigger.width) {
    const box = form.getBoundingClientRect();
    form.style.transformOrigin = `${trigger.left + trigger.width / 2 - box.left}px ${trigger.top + trigger.height / 2 - box.top}px`;
  }
  return { done, close, body, form, fail };
}

export function confirm(title, message, options = {}) {
  return modal({
    title,
    body: h('p', { class: 'modal-text', text: message }),
    actions: [
      { label: options.cancel || 'Cancel', value: false },
      { label: options.label || 'Confirm', value: true, primary: !options.danger, danger: options.danger },
    ],
  }).done.then(Boolean);
}

export function field(label, props = {}, hint = null) {
  const input = props.options
    ? h('select', { ...props, options: null, value: null }, props.options.map((o) => h('option', { value: o.value, selected: o.value === props.value || null, text: o.label })))
    : h('input', props);
  return h('label', { class: 'field' }, h('span', { text: label }), input, hint ? h('small', { text: hint }) : null);
}
