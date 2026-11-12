import * as THREE from '../../vendor/three.js';
import { FIELD_GLSL } from './field.js';

const FIELD_VERTEX = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FIELD_FRAGMENT = `
uniform float uAspect;
uniform vec3 uGlow;
varying vec2 vUv;
${FIELD_GLSL}
void main() {
  vec2 p = (vUv - 0.5) * vec2(uAspect, 1.0);
  vec3 col = fieldColor(p, gl_FragCoord.xy);
  vec2 away = p - uGlow.xy;
  float near = exp(-dot(away, away) / (uGlow.z * uGlow.z));
  float halo = exp(-dot(away, away) / (uGlow.z * uGlow.z * 5.0));
  vec3 beam = mix(vec3(0.553, 0.49, 1.0), vec3(0.36, 0.88, 1.0), smoothstep(-0.1, 0.5, away.y - away.x * 0.6) * 0.7);
  col = mix(col + beam * (near * 0.3 + halo * 0.1), col - (vec3(1.0) - beam) * (near * 0.22 + halo * 0.06), uLight);
  gl_FragColor = vec4(col, 1.0);
}`;

function markShape() {
  const shape = new THREE.Shape();
  const points = [[-1, 1.3], [1, 1.3], [1, 0.8], [-0.39, -0.8], [1, -0.8], [1, -1.3], [-1, -1.3], [-1, -0.8], [0.39, 0.8], [-1, 0.8]];
  shape.moveTo(points[0][0], points[0][1]);
  for (const [x, y] of points.slice(1)) {
    shape.lineTo(x, y);
  }
  shape.closePath();
  return shape;
}

function studio(renderer, light) {
  const scene = new THREE.Scene();
  const room = new THREE.Mesh(new THREE.BoxGeometry(20, 20, 20),
    new THREE.MeshBasicMaterial({ color: light ? 0x8f93b8 : 0x0c0e1c, side: THREE.BackSide }));
  scene.add(room);
  const panel = (color, strength, x, y, z, w, h) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.1), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(strength) }));
    mesh.position.set(x, y, z);
    mesh.lookAt(0, 0, 0);
    scene.add(mesh);
  };
  panel(0xffffff, 14, -5, 6, 4, 6, 3);
  panel(0x8d7dff, 16, 7, 1, 3, 2.5, 9);
  panel(0x5ce1ff, 12, -7, -3, -2, 2.5, 7);
  panel(0xffffff, 6, 2, -7, 5, 7, 2.5);
  panel(0x8d7dff, 9, 0, 3, -8, 9, 4);
  panel(0xffffff, 10, 0, 0.5, 8, 3, 6);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const map = pmrem.fromScene(scene, 0.03).texture;
  pmrem.dispose();
  scene.traverse((node) => {
    if (node.isMesh) {
      node.geometry.dispose();
      node.material.dispose();
    }
  });
  return map;
}

export function createScene(canvas, options = {}) {
  const still = options.mode === 'still';
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
  } catch (error) {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = options.light ? 1.75 : 1;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
  camera.position.set(0, 0, 9);

  const uniforms = {
    uTime: { value: 40 },
    uLight: { value: options.light ? 1 : 0 },
    uPointer: { value: [0, 0] },
    uRipples: { value: new Float32Array(32) },
    uAspect: { value: 1 },
    uGlow: { value: [0, 0, 0.3] },
  };
  const backdrop = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
    new THREE.ShaderMaterial({ uniforms, vertexShader: FIELD_VERTEX, fragmentShader: FIELD_FRAGMENT, depthWrite: false, toneMapped: false }));
  backdrop.position.z = -6;
  scene.add(backdrop);

  let environment = studio(renderer, options.light);
  scene.environment = environment;

  const geometry = new THREE.ExtrudeGeometry(markShape(), { depth: 0.62, bevelEnabled: true, bevelThickness: 0.09, bevelSize: 0.09, bevelSegments: 6, curveSegments: 4 });
  geometry.center();
  const glass = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    roughness: 0.04,
    metalness: 0,
    transmission: 1,
    thickness: 1.1,
    ior: 1.46,
    dispersion: 6,
    attenuationColor: new THREE.Color(options.light ? 0x9486ff : 0xb9b0ff),
    attenuationDistance: options.light ? 1.3 : 7,
    specularIntensity: 1,
    iridescence: 1,
    iridescenceIOR: 1.32,
    iridescenceThicknessRange: [120, 460],
    clearcoat: 1,
    clearcoatRoughness: 0.06,
    envMapIntensity: options.light ? 0.9 : 1.5,
  });
  const mark = new THREE.Mesh(geometry, glass);
  const rig = new THREE.Group();
  rig.add(mark);
  scene.add(rig);

  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const started = performance.now();
  let frame = 0;
  let last = 0;
  let dead = false;

  function layout() {
    const width = canvas.clientWidth || window.innerWidth;
    const height = canvas.clientHeight || window.innerHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const depth = camera.position.z - backdrop.position.z;
    const tall = 2 * Math.tan((camera.fov * Math.PI) / 360) * depth;
    backdrop.scale.set(tall * camera.aspect, tall, 1);
    uniforms.uAspect.value = camera.aspect;
    const view = 2 * Math.tan((camera.fov * Math.PI) / 360) * camera.position.z;
    const box = options.card ? options.card.getBoundingClientRect() : null;
    const free = box ? box.left : width;
    const side = Boolean(box) && free > width * 0.38;
    const roomy = document.body.classList.contains('auth-roomy');
    if (side) {
      const size = Math.min(0.92, Math.max(0.45, ((free / width) * view * camera.aspect) / 3.1));
      rig.position.set((free / 2 / width - 0.5) * view * camera.aspect, 0, 0);
      rig.scale.setScalar(size);
    } else {
      rig.position.set(0, view / 2 - 0.95, 0);
      rig.scale.setScalar(0.46);
    }
    rig.visible = side || !roomy;
    uniforms.uGlow.value = [rig.position.x / view, rig.position.y / view, rig.visible ? (side ? 0.3 : 0.2) : 0.0001];
  }

  function draw() {
    const t = (performance.now() - started) / 1000;
    pointer.x += (pointer.tx - pointer.x) * 0.05;
    pointer.y += (pointer.ty - pointer.y) * 0.05;
    uniforms.uTime.value = 40 + t;
    uniforms.uPointer.value = [pointer.x, pointer.y];
    mark.rotation.y = -0.5 + Math.sin(t * 0.32) * 0.34 + pointer.x * 0.5;
    mark.rotation.x = 0.16 + Math.sin(t * 0.21) * 0.07 - pointer.y * 0.3;
    mark.rotation.z = -0.06;
    mark.position.y = Math.sin(t * 0.5) * 0.07;
    renderer.render(scene, camera);
  }

  function loop(stamp) {
    if (dead) {
      return;
    }
    frame = requestAnimationFrame(loop);
    if (stamp - last < 1000 / 40 - 2) {
      return;
    }
    last = stamp;
    draw();
  }

  function start() {
    if (!still && !frame && !document.hidden) {
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

  function onResize() {
    layout();
    if (still) {
      draw();
    }
  }

  function onPointer(event) {
    pointer.tx = event.clientX / window.innerWidth - 0.5;
    pointer.ty = 0.5 - event.clientY / window.innerHeight;
  }

  window.addEventListener('resize', onResize);
  document.addEventListener('visibilitychange', onVisibility);
  if (!still) {
    window.addEventListener('pointermove', onPointer, { passive: true });
  }
  layout();
  draw();
  start();

  return {
    setLight(light) {
      uniforms.uLight.value = light ? 1 : 0;
      environment.dispose();
      environment = studio(renderer, light);
      scene.environment = environment;
      glass.envMapIntensity = light ? 0.9 : 1.5;
      glass.attenuationDistance = light ? 1.3 : 7;
      glass.attenuationColor.set(light ? 0x9486ff : 0xb9b0ff);
      renderer.toneMappingExposure = light ? 1.75 : 1;
      draw();
    },
    destroy() {
      dead = true;
      stop();
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pointermove', onPointer);
      document.removeEventListener('visibilitychange', onVisibility);
      geometry.dispose();
      glass.dispose();
      environment.dispose();
      renderer.dispose();
    },
  };
}
