const VERTEX = `#version 300 es
in vec2 corner;
void main() {
  gl_Position = vec4(corner, 0.0, 1.0);
}`;

export const FIELD_GLSL = `
uniform float uTime;
uniform float uLight;
uniform vec2 uPointer;
uniform vec4 uRipples[8];

float fieldHash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

vec2 fieldGrad(vec2 cell, float spin) {
  float a = 6.2831853 * fieldHash(cell) + spin;
  return vec2(cos(a), sin(a));
}

float fieldNoise(vec2 p, float spin) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  float a = dot(fieldGrad(i, spin), f);
  float b = dot(fieldGrad(i + vec2(1.0, 0.0), spin), f - vec2(1.0, 0.0));
  float c = dot(fieldGrad(i + vec2(0.0, 1.0), spin), f - vec2(0.0, 1.0));
  float d = dot(fieldGrad(i + vec2(1.0, 1.0), spin), f - vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

vec3 fieldColor(vec2 p, vec2 pixel) {
  float t = uTime;
  p += uPointer * 0.025;

  float swell = 0.0;
  vec3 flare = vec3(0.0);
  for (int i = 0; i < 8; i++) {
    vec4 r = uRipples[i];
    float age = t - r.z;
    if (r.z > 0.0 && age > 0.0 && age < 7.0) {
      float d = length(p - r.xy);
      float front = age * 0.3;
      float band = exp(-pow((d - front) / 0.1, 2.0));
      float fade = exp(-age * 0.62);
      swell += sin((d - front) * 46.0) * band * fade;
      vec3 tone = r.w < 0.5 ? vec3(0.553, 0.49, 1.0) : (r.w < 1.5 ? vec3(0.36, 0.88, 1.0) : vec3(1.0, 0.42, 0.49));
      flare += tone * band * fade * 0.16;
    }
  }

  vec2 q = p * 0.85;
  vec2 warp = vec2(fieldNoise(q + vec2(3.1, 0.0), t * 0.09), fieldNoise(q - vec2(7.7, 2.3), t * 0.08));
  q += warp * 0.7;
  float h = fieldNoise(q * 1.25 + vec2(t * 0.012, 0.0), t * 0.1) * 0.5 + 0.5;
  h += fieldNoise(q * 2.6 + 9.0, t * 0.07) * 0.09;
  h += swell * 0.035;
  float lit = smoothstep(0.4, 0.78, h);
  float ion = smoothstep(0.52, 0.86, fieldNoise(q * 0.7 + 21.0, t * 0.06) * 0.5 + 0.5);

  float v = h * 16.0;
  float w = fwidth(v);
  float line = 1.0 - smoothstep(0.0, w * 1.4, abs(fract(v) - 0.5));
  line *= 1.0 - smoothstep(0.35, 0.9, w);

  vec3 violet = vec3(0.553, 0.49, 1.0);
  vec3 cyan = vec3(0.36, 0.88, 1.0);
  vec3 dark = vec3(0.0157, 0.0196, 0.0392);
  dark += violet * lit * 0.15;
  dark += cyan * ion * (0.03 + lit * 0.075);
  dark += mix(violet, cyan, ion) * line * (0.05 + lit * 0.13);
  dark += flare;
  dark *= 1.0 - 0.35 * smoothstep(0.35, 1.05, length(p * vec2(0.75, 1.0)));

  vec3 paper = vec3(0.957, 0.961, 0.976);
  vec3 wash = vec3(0.80, 0.78, 1.0);
  vec3 mist = vec3(0.78, 0.93, 0.98);
  vec3 lightCol = mix(paper, wash, lit * 0.55);
  lightCol = mix(lightCol, mist, ion * 0.4);
  lightCol = mix(lightCol, vec3(0.35, 0.27, 0.93), line * (0.05 + lit * 0.09));
  float flareAmount = max(flare.r, max(flare.g, flare.b)) / 0.16;
  lightCol = mix(lightCol, flare / max(flareAmount * 0.16, 0.0001) * 0.92, flareAmount * 0.2);

  vec3 col = mix(dark, lightCol, uLight);
  col += (fieldHash(pixel + fract(t)) - 0.5) / 255.0;
  return col;
}
`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uSize;
out vec4 outColor;
${FIELD_GLSL}
void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uSize) / uSize.y;
  outColor = vec4(fieldColor(p, gl_FragCoord.xy), 1.0);
}`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(message || 'shader failed');
  }
  return shader;
}

export function fieldMode() {
  const connection = navigator.connection;
  if (connection && connection.saveData) {
    return 'off';
  }
  if (navigator.deviceMemory && navigator.deviceMemory <= 2) {
    return 'off';
  }
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    return 'still';
  }
  return 'live';
}

export function createField(canvas, options = {}) {
  const mode = options.mode || fieldMode();
  const scale = options.scale || 0.6;
  const fps = options.fps || 30;
  const idle = { ripple() {}, setLight() {}, destroy() {}, mode: 'off' };
  if (mode === 'off') {
    canvas.hidden = true;
    return idle;
  }
  const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
  if (!gl) {
    canvas.hidden = true;
    return idle;
  }
  let program;
  try {
    program = gl.createProgram();
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || 'link failed');
    }
  } catch (error) {
    canvas.hidden = true;
    return idle;
  }
  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const corner = gl.getAttribLocation(program, 'corner');
  gl.enableVertexAttribArray(corner);
  gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);

  const uniform = (name) => gl.getUniformLocation(program, name);
  const uSize = uniform('uSize');
  const uTime = uniform('uTime');
  const uLight = uniform('uLight');
  const uPointer = uniform('uPointer');
  const uRipples = uniform('uRipples');

  const ripples = new Float32Array(32);
  let slot = 0;
  let light = options.light ? 1 : 0;
  let lightTarget = light;
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const started = performance.now() - 40000;
  let frame = 0;
  let last = 0;
  let dead = false;

  function now() {
    return (performance.now() - started) / 1000;
  }

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5) * scale;
    const width = Math.max(2, Math.round(canvas.clientWidth * ratio));
    const height = Math.max(2, Math.round(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
    }
  }

  function draw() {
    resize();
    pointer.x += (pointer.tx - pointer.x) * 0.06;
    pointer.y += (pointer.ty - pointer.y) * 0.06;
    light += (lightTarget - light) * 0.12;
    gl.uniform2f(uSize, canvas.width, canvas.height);
    gl.uniform1f(uTime, now());
    gl.uniform1f(uLight, light);
    gl.uniform2f(uPointer, pointer.x, pointer.y);
    gl.uniform4fv(uRipples, ripples);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function loop(stamp) {
    if (dead) {
      return;
    }
    frame = requestAnimationFrame(loop);
    if (stamp - last < 1000 / fps - 2) {
      return;
    }
    last = stamp;
    draw();
  }

  function start() {
    if (mode === 'live' && !frame && !document.hidden) {
      frame = requestAnimationFrame(loop);
    }
  }

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
  }

  function onVisibility() {
    if (document.hidden) {
      stop();
    } else {
      start();
    }
  }

  function onPointer(event) {
    pointer.tx = event.clientX / window.innerWidth - 0.5;
    pointer.ty = 0.5 - event.clientY / window.innerHeight;
  }

  function onResize() {
    if (mode !== 'live') {
      draw();
    }
  }

  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('resize', onResize);
  if (mode === 'live') {
    window.addEventListener('pointermove', onPointer, { passive: true });
  }
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    stop();
  });
  draw();
  start();

  return {
    mode,
    ripple(clientX, clientY, kind = 0) {
      if (mode !== 'live') {
        return;
      }
      const height = window.innerHeight;
      ripples[slot * 4] = (clientX - window.innerWidth / 2) / height;
      ripples[slot * 4 + 1] = (height / 2 - clientY) / height;
      ripples[slot * 4 + 2] = now();
      ripples[slot * 4 + 3] = kind;
      slot = (slot + 1) % 8;
    },
    setLight(value) {
      lightTarget = value ? 1 : 0;
      if (mode !== 'live') {
        light = lightTarget;
        draw();
      }
    },
    destroy() {
      dead = true;
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pointermove', onPointer);
    },
  };
}
