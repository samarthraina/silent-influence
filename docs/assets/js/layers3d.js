// 3D explorer: Llama's lens layers as a stack of luminous plates. Brightness and colour
// follow the recorded Jacobian-Lens JSD; the selected layer slides out of the stack and
// its promoted / suppressed tokens float around it.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const GAP = 0.26;
const SIZE = 3.0;
const GRID = 17;

const vert = /* glsl */ `
  attribute float aRand;
  uniform float uTime;
  uniform float uI;
  uniform float uSel;
  uniform float uPR;
  varying float vA;
  void main() {
    vec3 p = position;
    float w = sin(p.x * 2.2 + uTime * 1.6 + aRand * 6.28) * cos(p.z * 2.0 + uTime * 1.2);
    p.y += w * 0.03 * (0.4 + uI);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float flick = 0.75 + 0.25 * sin(uTime * 3.0 + aRand * 40.0);
    vA = (0.12 + uI * 0.5) * flick * (1.0 + uSel * 0.9);
    gl_PointSize = (1.1 + aRand * 1.0 + uI * 2.0 + uSel * 1.2) * uPR * (24.0 / -mv.z);
  }
`;
const frag = /* glsl */ `
  uniform vec3 uColor;
  varying float vA;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(uColor, a * a * vA);
  }
`;

// deep indigo -> cyan -> violet -> coral
const RAMP = [[0, 0x2b2f6e], [0.3, 0x38e1ff], [0.65, 0xa78bfa], [1, 0xff5c7a]].map(([s, c]) => [s, new THREE.Color(c)]);
function ramp(x) {
  for (let i = 1; i < RAMP.length; i++) {
    if (x <= RAMP[i][0]) {
      const [s0, c0] = RAMP[i - 1], [s1, c1] = RAMP[i];
      return c0.clone().lerp(c1, (x - s0) / (s1 - s0));
    }
  }
  return RAMP[RAMP.length - 1][1].clone();
}
export const jsdColor = (x) => "#" + ramp(x).getHexString();

export function initLayers({ canvas, labelsEl, layers, eligible, excluded, selected, onSelect }) {
  const small = window.matchMedia("(max-width: 860px)").matches;
  const PR = Math.min(window.devicePixelRatio, small ? 1.5 : 2);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(PR);
  renderer.setClearColor(0x020208, 1);

  const labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.style.position = "absolute";
  labelRenderer.domElement.style.inset = "0";
  labelsEl.appendChild(labelRenderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
  camera.position.set(7.2, 5.0, 8.4);

  const controls = new OrbitControls(camera, canvas);
  controls.enableZoom = false;
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.55;
  controls.minPolarAngle = 0.5;
  controls.maxPolarAngle = 2.2;
  controls.target.set(0, 0.9, 0);
  canvas.style.touchAction = "pan-y";

  const maxJ = Math.max(...layers.map((l) => l.jsd));
  const stack = new THREE.Group();
  scene.add(stack);
  const n = layers.length;
  const plates = [];

  const gridGeo = (() => {
    const pos = [], rnd = [];
    for (let i = 0; i < GRID; i++) for (let j = 0; j < GRID; j++) {
      const x = (i / (GRID - 1) - 0.5) * SIZE + (Math.random() - 0.5) * 0.06;
      const z = (j / (GRID - 1) - 0.5) * SIZE + (Math.random() - 0.5) * 0.06;
      pos.push(x, 0, z);
      rnd.push(Math.random());
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("aRand", new THREE.Float32BufferAttribute(rnd, 1));
    return g;
  })();
  const edgeGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(SIZE + 0.18, 0.02, SIZE + 0.18));
  const hitGeo = new THREE.BoxGeometry(SIZE + 0.2, GAP * 0.9, SIZE + 0.2);
  const hitMat = new THREE.MeshBasicMaterial({ visible: false });

  layers.forEach((L, i) => {
    const norm = Math.sqrt(L.jsd / maxJ); // sqrt keeps small layers visible
    const isExcl = excluded.includes(L.layer);
    const color = isExcl ? new THREE.Color(0x5b6088) : ramp(norm);
    const g = new THREE.Group();
    g.position.y = (i - (n - 1) / 2) * GAP;
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag,
      uniforms: { uTime: { value: 0 }, uI: { value: isExcl ? norm * 0.35 : norm }, uSel: { value: 0 }, uPR: { value: PR }, uColor: { value: color } },
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const pts = new THREE.Points(gridGeo, mat);
    const edgeMat = isExcl
      ? new THREE.LineDashedMaterial({ color: 0x5b6088, dashSize: 0.12, gapSize: 0.1, transparent: true, opacity: 0.5 })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.18 + norm * 0.55 });
    const edge = new THREE.LineSegments(edgeGeo, edgeMat);
    if (isExcl) edge.computeLineDistances();
    const fill = new THREE.Mesh(
      new THREE.PlaneGeometry(SIZE, SIZE),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.008 + norm * 0.03, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending })
    );
    fill.rotation.x = -Math.PI / 2;
    const hit = new THREE.Mesh(hitGeo, hitMat);
    hit.userData.layer = L.layer;
    g.add(pts, edge, fill, hit);
    stack.add(g);
    plates.push({ L, g, mat, edge, fill, hit, baseY: g.position.y, norm, isExcl, slide: 0 });
  });

  // eligible band bracket
  const bandIdx = layers.map((l, i) => (l.layer >= eligible[0] && l.layer <= eligible[1] ? i : -1)).filter((i) => i >= 0);
  const y0 = plates[bandIdx[0]].baseY, y1 = plates[bandIdx[bandIdx.length - 1]].baseY;
  const bx = -SIZE / 2 - 0.55, bz = SIZE / 2 + 0.2;
  const bracket = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(bx + 0.18, y0, bz), new THREE.Vector3(bx, y0, bz),
      new THREE.Vector3(bx, y1, bz), new THREE.Vector3(bx + 0.18, y1, bz),
    ]),
    new THREE.LineBasicMaterial({ color: 0x38e1ff, transparent: true, opacity: 0.6 })
  );
  stack.add(bracket);
  const mkLabel = (html, cls) => {
    const el = document.createElement("div");
    el.className = cls;
    el.innerHTML = html;
    return new CSS2DObject(el);
  };
  const bandLabel = mkLabel(`eligible band L${eligible[0]}–L${eligible[1]}`, "l3-label");
  bandLabel.position.set(bx - 0.1, (y0 + y1) / 2, bz);
  bandLabel.center.set(1, 0.5);
  if (!small) stack.add(bandLabel);
  const exclIdx = plates.findIndex((p) => p.isExcl);
  if (exclIdx >= 0 && !small) {
    const ex = mkLabel("final layers · excluded", "l3-label");
    ex.position.set(SIZE / 2 + 0.3, plates[n - 1].baseY + 0.25, -SIZE / 2);
    ex.center.set(0, 0.5);
    stack.add(ex);
  }

  // selected layer label + floating tokens
  const selLabel = mkLabel("", "l3-label hot");
  selLabel.center.set(0, 0.5);
  stack.add(selLabel);
  let tokenObjs = [];

  const SLIDE = small ? 0.9 : 1.5;
  let current = selected;

  function setTokens(tokens) {
    tokenObjs.forEach((o) => { o.parent && o.parent.remove(o); o.element.remove(); });
    tokenObjs = [];
    const p = plates.find((q) => q.L.layer === current);
    // on phones the panel beside the stage already lists the tokens
    if (!p || !tokens || small) return;
    const up = tokens.promoted.slice(0, small ? 3 : 4), dn = tokens.suppressed.slice(0, small ? 2 : 3);
    const mk = (tok, cls, k, total, dir) => {
      const o = mkLabel("", "l3-tok " + cls);
      o.element.textContent = tok[0];
      // promoted tokens stack upward on one side, suppressed downward on the other
      o.userData = { x: dir * (SIZE * 0.5 + 1.0 + (k % 2) * 0.35), y: dir * (0.45 + k * 0.4), z: -dir * 0.4, k };
      o.element.style.opacity = "0";
      o.element.style.transition = "opacity .5s " + (k * 0.08) + "s";
      requestAnimationFrame(() => (o.element.style.opacity = "1"));
      p.g.add(o);
      tokenObjs.push(o);
    };
    up.forEach((t, k) => mk(t, "up", k, up.length, 1));
    dn.forEach((t, k) => mk(t, "down", k, dn.length, -1));
  }

  function select(layer, tokens) {
    current = layer;
    plates.forEach((p) => (p.mat.uniforms.uSel.value = p.L.layer === layer ? 1 : 0));
    const p = plates.find((q) => q.L.layer === layer);
    selLabel.element.textContent = `L${layer} · ${p.L.jsd.toFixed(3)} bits`;
    selLabel.removeFromParent();
    p.g.add(selLabel);
    selLabel.position.set(small ? -0.6 : SIZE / 2 + 0.25, small ? 0.45 : 0, SIZE / 2);
    setTokens(tokens);
  }

  // ---- picking ----
  const ray = new THREE.Raycaster();
  const ptr = new THREE.Vector2();
  let downAt = null, hover = null;
  const pick = (e) => {
    const r = canvas.getBoundingClientRect();
    ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    const hits = ray.intersectObjects(plates.map((p) => p.hit));
    return hits.length ? hits[0].object.userData.layer : null;
  };
  canvas.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; controls.autoRotate = false; });
  canvas.addEventListener("pointerup", (e) => {
    if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 6) {
      const l = pick(e);
      if (l != null) onSelect(l);
    }
    downAt = null;
    clearTimeout(canvas._ar);
    canvas._ar = setTimeout(() => (controls.autoRotate = true), 4000);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    hover = pick(e);
    canvas.style.cursor = hover != null ? "pointer" : "grab";
  });
  canvas.addEventListener("pointerleave", () => (hover = null));

  // ---- post ----
  let composer = null, bloom = null;
  if (!small) {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.6, 0.45, 0.32);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
  }

  const layout = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    labelRenderer.setSize(w, h);
    if (composer) { composer.setSize(w, h); bloom.resolution.set(w, h); }
    camera.aspect = w / h;
    camera.position.setLength(w < 560 ? 19 : 15.5);
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(layout).observe(canvas);
  layout();

  let visible = false;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { rootMargin: "100px" }).observe(canvas);

  const clock = new THREE.Clock();
  const frame = () => {
    requestAnimationFrame(frame);
    if (!visible) return;
    const t = clock.getElapsedTime();
    controls.update();
    plates.forEach((p) => {
      p.mat.uniforms.uTime.value = t;
      const target = p.L.layer === current ? SLIDE : p.L.layer === hover ? 0.35 : 0;
      p.slide += (target - p.slide) * 0.09;
      p.g.position.x = p.slide;
      const s = 1 + (p.L.layer === current ? 0.08 : 0);
      p.g.scale.x += (s - p.g.scale.x) * 0.1;
      p.g.scale.z = p.g.scale.x;
      p.edge.material.opacity = p.L.layer === current ? 1 : p.L.layer === hover ? 0.9 : p.isExcl ? 0.5 : 0.18 + p.norm * 0.55;
    });
    tokenObjs.forEach((o) => {
      const u = o.userData;
      o.position.set(u.x, u.y + Math.sin(t * 1.3 + u.k) * 0.05, u.z);
    });
    if (composer) composer.render(); else renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
  };
  frame();

  return { select };
}
