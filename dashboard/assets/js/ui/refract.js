const NS = 'http://www.w3.org/2000/svg';
const MAP = [
  ['rgb(128,128,0)', (w, h) => [0, 0, w, h]],
  ['rgb(255,128,0)', (w, h, rim) => [0, 0, rim, h]],
  ['rgb(0,128,0)', (w, h, rim) => [w - rim, 0, rim, h]],
  ['rgb(128,255,0)', (w, h, rim) => [0, 0, w, rim]],
  ['rgb(128,0,0)', (w, h, rim) => [0, h - rim, w, rim]],
];

let host = null;
let serial = 0;
let able = null;

function svg(name, attrs, parent) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  parent.appendChild(node);
  return node;
}

export function supported() {
  if (able === null) {
    const connection = navigator.connection;
    able = Boolean(navigator.userAgentData)
      && typeof CSS !== 'undefined' && CSS.supports('backdrop-filter', 'url(#a) blur(1px)')
      && window.matchMedia('(min-width: 901px) and (pointer: fine)').matches
      && !(connection && connection.saveData)
      && !(navigator.deviceMemory && navigator.deviceMemory <= 2);
  }
  return able;
}

export function refract(node, options = {}) {
  if (!node || !supported()) {
    return () => {};
  }
  if (!host) {
    host = svg('svg', { class: 'refract-defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false' }, document.body);
  }
  const id = `refract-${++serial}`;
  const filter = svg('filter', { id, x: 0, y: 0, filterUnits: 'userSpaceOnUse', primitiveUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB' }, host);
  const floods = MAP.map(([color], index) => svg('feFlood', { 'flood-color': color, result: `f${index}` }, filter));
  const merge = svg('feMerge', { result: 'merged' }, filter);
  floods.forEach((_, index) => svg('feMergeNode', { in: `f${index}` }, merge));
  const soften = svg('feGaussianBlur', { in: 'merged', result: 'map' }, filter);
  svg('feDisplacementMap', { in: 'SourceGraphic', in2: 'map', scale: options.scale || 44, xChannelSelector: 'R', yChannelSelector: 'G' }, filter);

  function size() {
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    if (!w || !h) {
      return;
    }
    const rim = Math.min(options.rim || 22, w / 5, h / 5);
    filter.setAttribute('width', w);
    filter.setAttribute('height', h);
    soften.setAttribute('stdDeviation', rim * 0.4);
    floods.forEach((flood, index) => {
      const [x, y, fw, fh] = MAP[index][1](w, h, rim);
      flood.setAttribute('x', x);
      flood.setAttribute('y', y);
      flood.setAttribute('width', fw);
      flood.setAttribute('height', fh);
    });
  }

  size();
  const watch = new ResizeObserver(size);
  watch.observe(node);
  node.style.backdropFilter = `url(#${id}) var(--refract-blur)`;
  return () => {
    watch.disconnect();
    node.style.removeProperty('backdrop-filter');
    filter.remove();
  };
}
