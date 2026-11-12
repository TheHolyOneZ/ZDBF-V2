import { clear, h, s } from '../core/dom.js';
import { time } from '../core/format.js';

const PLOT = { left: 38, right: 10, top: 8, bottom: 20, height: 112 };

function niceStep(raw) {
  if (!(raw > 0)) {
    return 1;
  }
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10;
  return nice * power;
}

function tickLabel(value) {
  if (value >= 10000) {
    return `${Math.round(value / 100) / 10}K`;
  }
  return String(Math.round(value * 100) / 100);
}

export function sparkline(values, options = {}) {
  const width = options.width || 104;
  const height = options.height || 30;
  const pad = 5;
  const svg = s('svg', { class: 'spark', viewBox: `0 0 ${width} ${height}`, width, height, 'aria-hidden': 'true' });
  const points = values.map((v, i) => [i, v]).filter(([, v]) => typeof v === 'number' && Number.isFinite(v));
  if (points.length < 2) {
    svg.appendChild(s('path', { class: 'spark-line', d: `M${pad} ${height / 2}H${width - pad}` }));
    return svg;
  }
  const min = Math.min(...points.map(([, v]) => v));
  const max = Math.max(...points.map(([, v]) => v));
  const span = max - min || 1;
  const last = values.length - 1 || 1;
  const x = (i) => pad + (i / last) * (width - pad * 2);
  const y = (v) => height - pad - ((v - min) / span) * (height - pad * 2);
  const d = points.map(([i, v], n) => `${n ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join('');
  const [li, lv] = points[points.length - 1];
  svg.append(
    s('path', { class: 'spark-line', d }),
    s('circle', { class: 'spark-dot', cx: x(li).toFixed(1), cy: y(lv).toFixed(1), r: 3.5 }),
  );
  return svg;
}

export function chartGroup(defs, options = {}) {
  const root = h('div', { class: 'multiples' });
  const tip = h('div', { class: 'chart-tip', hidden: true, role: 'status' });
  const tableHost = h('div', { class: 'chart-table', hidden: true });
  const charts = [];
  let points = [];
  let hover = -1;
  let hoverChart = null;
  let mode = 'chart';
  let width = 0;

  for (const def of defs) {
    const value = h('strong', { class: 'mini-value', text: '-' });
    const svg = s('svg', { class: 'plot', role: 'img', tabindex: '0' });
    const node = h('figure', { class: 'mini-chart' },
      h('figcaption', null, h('span', { class: 'mini-title', text: def.title }), value),
      svg);
    charts.push({ def, node, svg, value, x: null, y: null });
    root.appendChild(node);
    svg.addEventListener('pointermove', (event) => {
      const box = svg.getBoundingClientRect();
      setHover(nearest(event.clientX - box.left), charts.find((c) => c.svg === svg));
    });
    svg.addEventListener('pointerleave', () => setHover(-1));
    svg.addEventListener('focus', () => setHover(points.length - 1, charts.find((c) => c.svg === svg)));
    svg.addEventListener('blur', () => setHover(-1));
    svg.addEventListener('keydown', (event) => {
      const chart = charts.find((c) => c.svg === svg);
      if (event.key === 'ArrowLeft') {
        setHover(Math.max(0, (hover < 0 ? points.length : hover) - 1), chart);
        event.preventDefault();
      } else if (event.key === 'ArrowRight') {
        setHover(Math.min(points.length - 1, hover + 1), chart);
        event.preventDefault();
      } else if (event.key === 'Escape') {
        setHover(-1);
      }
    });
  }
  root.append(tip, tableHost);

  function nearest(px) {
    if (!points.length || !charts[0].x) {
      return -1;
    }
    let best = 0;
    let distance = Infinity;
    points.forEach((point, index) => {
      const d = Math.abs(charts[0].x(point.t) - px);
      if (d < distance) {
        distance = d;
        best = index;
      }
    });
    return best;
  }

  function setHover(index, origin = null) {
    hover = index;
    hoverChart = index < 0 ? null : origin;
    for (const chart of charts) {
      const cross = chart.svg.querySelector('.cross');
      const dot = chart.svg.querySelector('.cross-dot');
      const point = points[index];
      const v = point ? point.values[chart.def.key] : null;
      if (!cross || !point || !chart.x) {
        cross?.setAttribute('visibility', 'hidden');
        dot?.setAttribute('visibility', 'hidden');
        continue;
      }
      const px = chart.x(point.t).toFixed(1);
      cross.setAttribute('x1', px);
      cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      if (typeof v === 'number') {
        dot.setAttribute('cx', px);
        dot.setAttribute('cy', chart.y(v).toFixed(1));
        dot.setAttribute('visibility', 'visible');
      } else {
        dot.setAttribute('visibility', 'hidden');
      }
    }
    const point = points[index];
    if (!point || !origin || mode !== 'chart') {
      tip.hidden = true;
      return;
    }
    clear(tip);
    tip.appendChild(h('div', { class: 'tip-time', text: time(point.t, true) }));
    for (const chart of charts) {
      const v = point.values[chart.def.key];
      tip.appendChild(h('div', { class: 'tip-row' },
        h('strong', { text: typeof v === 'number' ? chart.def.format(v) : 'no data' }),
        h('span', { text: chart.def.title })));
    }
    tip.hidden = false;
    const rootBox = root.getBoundingClientRect();
    const plotBox = origin.svg.getBoundingClientRect();
    const px = plotBox.left - rootBox.left + origin.x(point.t);
    const tipWidth = tip.offsetWidth;
    const left = px + 14 + tipWidth > rootBox.width ? px - 14 - tipWidth : px + 14;
    tip.style.setProperty('left', `${Math.max(0, left)}px`);
    tip.style.setProperty('top', `${plotBox.top - rootBox.top + 4}px`);
  }

  function draw(chart) {
    const { svg, def } = chart;
    const w = Math.max(160, Math.floor(chart.node.clientWidth));
    const hgt = PLOT.height;
    clear(svg);
    svg.setAttribute('viewBox', `0 0 ${w} ${hgt}`);
    svg.setAttribute('width', w);
    svg.setAttribute('height', hgt);
    const series = points.map((p) => p.values[def.key]);
    const numbers = series.filter((v) => typeof v === 'number' && Number.isFinite(v));
    const latest = numbers.length ? numbers[numbers.length - 1] : null;
    chart.value.textContent = latest == null ? '-' : def.format(latest);
    svg.setAttribute('aria-label', `${def.title}, ${options.range || 'recent'}. ${latest == null ? 'No data yet' : `Now ${def.format(latest)}`}.`);
    const x0 = PLOT.left;
    const x1 = w - PLOT.right;
    const y0 = hgt - PLOT.bottom;
    const y1 = PLOT.top;
    const max = Math.max(def.min || 0, ...numbers, 0);
    const step = niceStep((max || 1) / 2);
    const top = step * 2 >= max ? step * 2 : step * 3;
    const t0 = points.length ? points[0].t : 0;
    const t1 = points.length ? points[points.length - 1].t : 1;
    chart.x = (t) => (t1 === t0 ? x1 : x0 + ((t - t0) / (t1 - t0)) * (x1 - x0));
    chart.y = (v) => y0 - (Math.min(v, top) / top) * (y0 - y1);
    for (let tick = step; tick <= top + 1e-9; tick += step) {
      const py = chart.y(tick).toFixed(1);
      svg.append(
        s('line', { class: 'grid', x1: x0, x2: x1, y1: py, y2: py }),
        s('text', { class: 'tick', x: x0 - 8, y: py, dy: '0.32em', 'text-anchor': 'end' }, tickLabel(tick)),
      );
    }
    svg.append(
      s('line', { class: 'axis', x1: x0, x2: x1, y1: y0, y2: y0 }),
      s('text', { class: 'tick', x: x0 - 8, y: y0, dy: '0.32em', 'text-anchor': 'end' }, '0'),
    );
    if (points.length) {
      const fresh = Date.now() / 1000 - t1 < 30;
      svg.append(
        s('text', { class: 'tick', x: x0, y: hgt - 4 }, time(t0)),
        s('text', { class: 'tick', x: x1, y: hgt - 4, 'text-anchor': 'end' }, fresh ? 'now' : time(t1)),
      );
    }
    if (numbers.length < 2) {
      svg.appendChild(s('text', { class: 'tick', x: (x0 + x1) / 2, y: (y0 + y1) / 2, 'text-anchor': 'middle' }, 'Collecting data'));
      return;
    }
    let line = '';
    let area = '';
    let open = false;
    let startX = 0;
    let lastX = 0;
    points.forEach((p) => {
      const v = p.values[def.key];
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        if (open) {
          area += `L${lastX} ${y0}L${startX} ${y0}Z`;
          open = false;
        }
        return;
      }
      const px = chart.x(p.t).toFixed(1);
      const py = chart.y(v).toFixed(1);
      if (!open) {
        line += `M${px} ${py}`;
        area += `M${px} ${py}`;
        startX = px;
        open = true;
      } else {
        line += `L${px} ${py}`;
        area += `L${px} ${py}`;
      }
      lastX = px;
    });
    if (open) {
      area += `L${lastX} ${y0}L${startX} ${y0}Z`;
    }
    let end = null;
    for (let i = points.length - 1; i >= 0 && !end; i--) {
      const v = points[i].values[def.key];
      if (typeof v === 'number') {
        end = [chart.x(points[i].t).toFixed(1), chart.y(v).toFixed(1)];
      }
    }
    const now = performance.now();
    chart.born = chart.born || now;
    const age = now - chart.born;
    const first = age < 900;
    const stroke = s('path', { class: first ? 'line line-in' : 'line', d: line });
    const fill = s('path', { class: first ? 'area area-in' : 'area', d: area });
    if (first) {
      stroke.setAttribute('pathLength', '1');
      stroke.style.animationDelay = `${-age}ms`;
      fill.style.animationDelay = `${-age}ms`;
    }
    svg.append(
      fill,
      stroke,
      s('circle', { class: 'end-dot', cx: end[0], cy: end[1], r: 4 }),
      s('line', { class: 'cross', y1, y2: y0, visibility: 'hidden' }),
      s('circle', { class: 'cross-dot', r: 4, visibility: 'hidden' }),
      s('rect', { class: 'hit', x: x0, y: y1, width: Math.max(0, x1 - x0), height: y0 - y1 }),
    );
  }

  function drawTable() {
    clear(tableHost);
    const head = h('tr', null, h('th', { scope: 'col', text: 'Time' }), defs.map((d) => h('th', { scope: 'col', class: 'n', text: d.title })));
    const rows = points.slice(-40).reverse().map((p) => h('tr', null,
      h('td', { text: time(p.t, true) }),
      defs.map((d) => h('td', { class: 'n', text: typeof p.values[d.key] === 'number' ? d.format(p.values[d.key]) : '-' }))));
    tableHost.appendChild(h('table', { class: 'table table-compact' }, h('thead', null, head), h('tbody', null, rows)));
  }

  function render() {
    if (mode === 'table') {
      drawTable();
      return;
    }
    for (const chart of charts) {
      draw(chart);
    }
    if (hover >= 0) {
      setHover(Math.min(hover, points.length - 1), hoverChart);
    }
  }

  const observer = new ResizeObserver(() => {
    requestAnimationFrame(() => {
      const next = root.clientWidth;
      if (next !== width) {
        width = next;
        render();
      }
    });
  });
  observer.observe(root);

  return {
    element: root,
    update(next) {
      points = next;
      render();
    },
    setMode(next) {
      mode = next;
      tableHost.hidden = mode !== 'table';
      for (const chart of charts) {
        chart.node.hidden = mode === 'table';
      }
      tip.hidden = true;
      render();
    },
    destroy() {
      observer.disconnect();
    },
  };
}

export function rankedBars(items, format) {
  const max = Math.max(1, ...items.map((item) => item.value));
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
  return h('ol', { class: 'bars' }, items.map((item) => h('li', {
    class: 'bar-row',
    title: `${item.label}: ${format(item.value)} (${Math.round((item.value / total) * 100)}% of these)`,
    vars: { '--share': String(item.value / max) },
  },
  h('span', { class: 'bar-label', text: item.label }),
  h('span', { class: 'bar-track' }, h('span', { class: 'bar-fill' }), h('span', { class: 'bar-value', text: format(item.value) })))));
}

export function meter(label, ratio, detail, options = {}) {
  const clamped = Math.max(0, Math.min(1, ratio || 0));
  const level = clamped >= (options.bad ?? 0.9) ? 'bad' : clamped >= (options.warn ?? 0.75) ? 'warn' : 'ok';
  const names = { ok: '', warn: 'High', bad: 'Critical' };
  return h('div', { class: 'meter-row', dataset: { level } },
    h('div', { class: 'meter-head' },
      h('span', { class: 'meter-label', text: label }),
      h('span', { class: 'meter-detail' }, names[level] ? h('em', { text: names[level] }) : null, detail)),
    h('div', { class: 'meter', role: 'meter', 'aria-label': label, 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(clamped * 100)) },
      h('span', { class: 'meter-fill', vars: { '--w': `${(clamped * 100).toFixed(1)}%` } })));
}
