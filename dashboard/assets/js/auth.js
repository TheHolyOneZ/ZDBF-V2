import { fieldMode } from './ui/field.js';

const root = document.documentElement;
const canvas = document.getElementById('scene');
const card = document.querySelector('.auth-card');
const mode = fieldMode();

async function start() {
  if (!canvas || mode === 'off') {
    canvas?.remove();
    return;
  }
  let scene = null;
  try {
    const { createScene } = await import('./ui/scene.js');
    scene = createScene(canvas, { mode, card, light: root.getAttribute('data-theme') === 'light' });
  } catch (error) {
    scene = null;
  }
  if (!scene) {
    canvas.remove();
    return;
  }
  document.body.dataset.scene = 'on';
}

if (card && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
  card.addEventListener('pointermove', (event) => {
    const box = card.getBoundingClientRect();
    card.style.setProperty('--px', `${event.clientX - box.left}px`);
    card.style.setProperty('--py', `${event.clientY - box.top}px`);
    card.style.setProperty('--lit', '1');
  }, { passive: true });
  card.addEventListener('pointerleave', () => card.style.setProperty('--lit', '0'));
}

requestAnimationFrame(() => requestAnimationFrame(start));
