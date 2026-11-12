const query = window.matchMedia('(prefers-reduced-motion: reduce)');
const GLASS = '.card, .stat, .rail, .topbar';

export const T = { micro: 0.18, ui: 0.32, page: 0.6, hero: 0.9 };

let lib = null;
let loading = null;

export function reduced() {
  return query.matches;
}

export function load() {
  if (!loading) {
    loading = import('../../vendor/gsap.js').then((module) => {
      module.CustomEase.create('glass', 'M0,0 C0.14,0.82 0.22,1.035 0.48,1.014 0.7,1 0.86,1 1,1');
      module.gsap.defaults({ duration: T.ui, ease: 'glass' });
      lib = module;
      return module;
    }).catch(() => null);
  }
  return loading;
}

export function tween(el, to, format, ms = 600) {
  const from = Number(el.dataset.value);
  el.dataset.value = String(to);
  if (reduced() || Number.isNaN(from) || from === to || !Number.isFinite(to)) {
    el.textContent = format(to);
    return;
  }
  const start = performance.now();
  const token = String(start);
  el.dataset.tween = token;
  const step = (now) => {
    if (el.dataset.tween !== token) {
      return;
    }
    const progress = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(2, -10 * progress);
    el.textContent = format(progress < 1 ? from + (to - from) * eased : to);
    if (progress < 1) {
      requestAnimationFrame(step);
    }
  };
  requestAnimationFrame(step);
}

export function stagger(nodes, step = 24) {
  if (reduced()) {
    return;
  }
  const list = [...nodes].slice(0, 8);
  if (lib) {
    lib.gsap.from(list, {
      y: 16, autoAlpha: 0, duration: T.page, ease: 'expo.out', stagger: step / 1000,
      clearProps: 'transform,opacity,visibility',
    });
    return;
  }
  list.forEach((node, index) => {
    node.style.setProperty('--delay', `${index * step}ms`);
    node.classList.add('rise');
  });
}

export function arrive(node) {
  if (reduced()) {
    return;
  }
  if (lib) {
    lib.gsap.from(node, { y: 10, autoAlpha: 0, duration: T.ui, ease: 'expo.out', clearProps: 'transform,opacity,visibility' });
    return;
  }
  node.classList.add('rise');
}

export function settle(container, change) {
  if (reduced() || !lib) {
    change();
    return;
  }
  const state = lib.Flip.getState([...container.children]);
  change();
  lib.Flip.from(state, { duration: T.ui, ease: 'glass', targets: [...container.children] });
}

export function leave(node) {
  if (reduced() || !lib || !node.firstChild) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    lib.gsap.to(node, { autoAlpha: 0, filter: 'blur(6px)', duration: T.micro, ease: 'power2.in', overwrite: true, onComplete: resolve });
  });
}

function title(node) {
  if (!node || !node.textContent.trim()) {
    return;
  }
  const split = lib.SplitText.create(node, { type: 'chars', mask: 'chars' });
  lib.gsap.from(split.chars, {
    yPercent: 115, duration: 0.8, ease: 'expo.out', stagger: 0.024,
    onComplete: () => split.revert(),
  });
}

export function enter(outlet, page) {
  if (!lib) {
    outlet.style.removeProperty('opacity');
    outlet.style.removeProperty('visibility');
    outlet.style.removeProperty('filter');
    return;
  }
  lib.gsap.killTweensOf(outlet);
  lib.gsap.set(outlet, { clearProps: 'opacity,visibility,filter' });
  if (reduced()) {
    return;
  }
  lib.gsap.from(page, { y: 12, autoAlpha: 0, duration: T.page, ease: 'expo.out', clearProps: 'transform,opacity,visibility' });
  title(page.querySelector('.page-head h1'));
}

export function tilt(nodes) {
  const stops = [];
  if (!reduced() && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    load().then((module) => {
      if (!module || stops.dead) {
        return;
      }
      for (const node of nodes) {
        module.gsap.set(node, { transformPerspective: 900 });
        const rx = module.gsap.quickTo(node, 'rotationX', { duration: 0.5, ease: 'power3.out' });
        const ry = module.gsap.quickTo(node, 'rotationY', { duration: 0.5, ease: 'power3.out' });
        const move = (event) => {
          const box = node.getBoundingClientRect();
          ry(((event.clientX - box.left) / box.width - 0.5) * 5);
          rx((0.5 - (event.clientY - box.top) / box.height) * 5);
        };
        const rest = () => {
          rx(0);
          ry(0);
        };
        node.addEventListener('pointermove', move);
        node.addEventListener('pointerleave', rest);
        stops.push(() => {
          node.removeEventListener('pointermove', move);
          node.removeEventListener('pointerleave', rest);
        });
      }
    });
  }
  return () => {
    stops.dead = true;
    stops.forEach((stop) => stop());
  };
}

export function magnetic() {
  if (reduced() || !window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    return;
  }
  const pulls = new WeakMap();
  let held = null;
  const pick = (target) => (target instanceof Element ? target.closest('.btn-primary:not(.btn-sm):not([disabled])') : null);
  document.addEventListener('pointermove', (event) => {
    if (!lib) {
      return;
    }
    const button = pick(event.target);
    if (held && held !== button) {
      const pull = pulls.get(held);
      pull.x(0);
      pull.y(0);
      held = null;
    }
    if (!button) {
      return;
    }
    if (!pulls.has(button)) {
      pulls.set(button, {
        x: lib.gsap.quickTo(button, 'x', { duration: 0.4, ease: 'power3.out' }),
        y: lib.gsap.quickTo(button, 'y', { duration: 0.4, ease: 'power3.out' }),
      });
    }
    const box = button.getBoundingClientRect();
    const pull = pulls.get(button);
    pull.x((event.clientX - box.left - box.width / 2) * 0.08);
    pull.y((event.clientY - box.top - box.height / 2) * 0.22);
    held = button;
  }, { passive: true });
}

export function glassLight() {
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    return;
  }
  let lit = null;
  let pending = null;
  let queued = false;
  document.addEventListener('pointermove', (event) => {
    pending = event;
    if (queued) {
      return;
    }
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const glass = pending.target instanceof Element ? pending.target.closest(GLASS) : null;
      if (lit && lit !== glass) {
        lit.style.setProperty('--lit', '0');
      }
      if (glass) {
        const box = glass.getBoundingClientRect();
        glass.style.setProperty('--px', `${pending.clientX - box.left}px`);
        glass.style.setProperty('--py', `${pending.clientY - box.top}px`);
        glass.style.setProperty('--lit', '1');
      }
      lit = glass;
    });
  }, { passive: true });
}
