const form = document.getElementById('setup-form');
const row = document.getElementById('probe-row');
const text = document.getElementById('probe-text');
const block = document.getElementById('probe-block');
const submit = document.getElementById('setup-submit');

async function reachable(url, marker) {
  try {
    const response = await fetch(url, { cache: 'no-store', credentials: 'omit', redirect: 'manual' });
    if (!response.ok) {
      return false;
    }
    return (await response.text()).includes(marker);
  } catch (error) {
    return false;
  }
}

async function probe() {
  if (!form || !row) {
    return;
  }
  const base = form.dataset.base || '';
  const exposed = (await Promise.all([
    reachable(base + '/data/probe.txt', form.dataset.probe || 'zdbf-probe-'),
    reachable(base + '/app/probe.txt', 'zdbf-probe'),
  ])).some(Boolean);
  row.dataset.state = exposed ? 'bad' : 'ok';
  text.textContent = exposed
    ? 'The "data" or "app" folder can be opened from the web.'
    : 'The "data" and "app" folders cannot be opened from the web.';
  form.elements.probe.value = exposed ? 'exposed' : 'ok';
  if (block) {
    block.hidden = !exposed;
  }
  if (submit) {
    submit.disabled = exposed;
  }
}

function drivers() {
  const fields = document.getElementById('mysql-fields');
  if (!form || !fields) {
    return;
  }
  const sync = () => {
    const chosen = form.querySelector('input[name="driver"]:checked');
    fields.hidden = !chosen || chosen.value !== 'mysql';
  };
  form.addEventListener('change', sync);
  sync();
}

function copyButtons() {
  for (const button of document.querySelectorAll('[data-copy]')) {
    button.addEventListener('click', async () => {
      const source = document.getElementById(button.dataset.copy);
      if (!source) {
        return;
      }
      try {
        await navigator.clipboard.writeText(source.textContent || '');
        button.textContent = 'Copied';
      } catch (error) {
        const range = document.createRange();
        range.selectNodeContents(source);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        button.textContent = 'Press Ctrl+C';
      }
      setTimeout(() => {
        button.textContent = 'Copy';
      }, 2000);
    });
  }
}

probe();
drivers();
copyButtons();
