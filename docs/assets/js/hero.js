// Hero scene: Agent A emits one sentence that travels into Agent B's 32-layer tower.
// The pulse flares at layer 24 and the score above the tower flips from 8 to 4.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const N_LAYERS = 32;
const HOT = 24;
const TOWER_H = 6.4;
const CYCLE = 7.5; // seconds per whisper

const pointVert = /* glsl */ `
  attribute float aLayer;
  attribute float aAngle;
  attribute float aRadius;
  attribute float aRand;
  uniform float uTime;
  uniform float uPulse;
  uniform float uHot;
  uniform float uPR;
  uniform float uFlare;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float t = uLayerNorm(aLayer);
    float dir = mod(aLayer, 2.0) < 1.0 ? 1.0 : -1.0;
    float a = aAngle + uTime * (0.06 + 0.04 * aRand) * dir;
    float wob = sin(aAngle * 5.0 + uTime * 1.3 + aLayer) * 0.05;
    float r = aRadius + wob;
    float y = (t - 0.5) * ${TOWER_H.toFixed(2)} + sin(aAngle * 3.0 + uTime) * 0.025;
    vec3 p = vec3(cos(a) * r, y, sin(a) * r);

    float d = (aLayer - uPulse);
    float glow = exp(-d * d / 2.2);
    float isHot = 1.0 - step(0.5, abs(aLayer - uHot));

    vec3 cA = vec3(0.22, 0.88, 1.0);
    vec3 cB = vec3(0.65, 0.55, 0.98);
    vec3 cS = vec3(1.0, 0.36, 0.48);
    vec3 base = mix(cA, cB, smoothstep(0.0, 1.0, t)) * 0.5;
    vec3 col = base + vec3(0.8, 0.85, 1.0) * glow * 0.7;
    col = mix(col, cS * (0.75 + uFlare * 0.9), isHot);

    vColor = col;
    vAlpha = 0.16 + glow * 0.45 + isHot * (0.25 + uFlare * 0.25);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float size = (1.0 + aRand * 1.3) * (1.0 + glow * 1.0 + isHot * (0.4 + uFlare * 0.7));
    gl_PointSize = size * uPR * (30.0 / -mv.z);
  }
`.replace("uLayerNorm(aLayer)", `(aLayer / ${(N_LAYERS - 1).toFixed(1)})`);

const pointFrag = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float a = smoothstep(0.5, 0.0, d);
    a *= a;
    gl_FragColor = vec4(vColor, a * vAlpha);
  }
`;

function softDot() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.3, "rgba(255,255,255,0.6)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function scoreTexture(text, color, sub) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 256;
  const g = c.getContext("2d");
  g.textAlign = "center";
  g.fillStyle = color;
  g.shadowColor = color;
  g.shadowBlur = 16;
  g.font = "700 150px 'Space Grotesk', system-ui, sans-serif";
  g.fillText(text, 256, 165);
  g.shadowBlur = 0;
  g.font = "500 34px 'JetBrains Mono', monospace";
  g.fillStyle = "rgba(220,224,255,0.75)";
  g.fillText(sub, 256, 225);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function initHero(canvas) {
  const small = window.matchMedia("(max-width: 860px)").matches;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  const PR = Math.min(window.devicePixelRatio, small ? 1.5 : 2);
  renderer.setPixelRatio(PR);
  renderer.setClearColor(0x04050d, 1);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x04050d, 0.035);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  camera.position.set(0, 0.4, 14);

  const world = new THREE.Group();
  scene.add(world);
  const tower = new THREE.Group();
  world.add(tower);

  // ---- tower of layers ----
  const perLayer = small ? 110 : 170;
  const count = N_LAYERS * perLayer;
  const aLayer = new Float32Array(count), aAngle = new Float32Array(count),
        aRadius = new Float32Array(count), aRand = new Float32Array(count);
  for (let l = 0, i = 0; l < N_LAYERS; l++) {
    const t = l / (N_LAYERS - 1);
    const baseR = 1.25 + Math.sin(t * Math.PI) * 0.55;
    for (let k = 0; k < perLayer; k++, i++) {
      aLayer[i] = l;
      aAngle[i] = (k / perLayer) * Math.PI * 2 + Math.random() * 0.05;
      aRadius[i] = baseR + (Math.random() - 0.5) * 0.18;
      aRand[i] = Math.random();
    }
  }
  const tg = new THREE.BufferGeometry();
  tg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  tg.setAttribute("aLayer", new THREE.BufferAttribute(aLayer, 1));
  tg.setAttribute("aAngle", new THREE.BufferAttribute(aAngle, 1));
  tg.setAttribute("aRadius", new THREE.BufferAttribute(aRadius, 1));
  tg.setAttribute("aRand", new THREE.BufferAttribute(aRand, 1));
  tg.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 6);
  const towerMat = new THREE.ShaderMaterial({
    vertexShader: pointVert, fragmentShader: pointFrag,
    uniforms: { uTime: { value: 0 }, uPulse: { value: -10 }, uHot: { value: HOT - 1 }, uPR: { value: PR }, uFlare: { value: 0 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  tower.add(new THREE.Points(tg, towerMat));

  // residual stream: a thin luminous core
  const coreGeo = new THREE.CylinderGeometry(0.035, 0.035, TOWER_H + 0.6, 8, 1, true);
  const coreMat = new THREE.MeshBasicMaterial({ color: 0x8f86ff, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false });
  tower.add(new THREE.Mesh(coreGeo, coreMat));

  // L24 halo ring
  const hotY = ((HOT - 1) / (N_LAYERS - 1) - 0.5) * TOWER_H;
  const hotR = 1.25 + Math.sin(((HOT - 1) / (N_LAYERS - 1)) * Math.PI) * 0.55;
  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(hotR + 0.32, 0.012, 8, 160),
    new THREE.MeshBasicMaterial({ color: 0xff5c7a, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending })
  );
  halo.rotation.x = Math.PI / 2;
  halo.position.y = hotY;
  tower.add(halo);

  // Agent B crown + score sprite
  const crown = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.32, 1),
    new THREE.MeshBasicMaterial({ color: 0xa78bfa, wireframe: true, transparent: true, opacity: 0.9 })
  );
  crown.position.y = TOWER_H / 2 + 0.75;
  tower.add(crown);
  const crownCore = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 16), new THREE.MeshBasicMaterial({ color: 0xb9a8ff }));
  crown.add(crownCore);

  const tex8 = scoreTexture("8", "#9fb4ff", "no history");
  const tex4 = scoreTexture("4", "#ff5c7a", "+ one sentence");
  const score = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex8, transparent: true, depthWrite: false }));
  score.scale.set(3.4, 1.7, 1);
  score.position.y = TOWER_H / 2 + 2.0;
  tower.add(score);

  // ---- Agent A ----
  const agentA = new THREE.Group();
  const aShell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.62, 1),
    new THREE.MeshBasicMaterial({ color: 0x38e1ff, wireframe: true, transparent: true, opacity: 0.75 })
  );
  const aCore = new THREE.Mesh(new THREE.SphereGeometry(0.22, 24, 24), new THREE.MeshBasicMaterial({ color: 0x5fd8f5 }));
  agentA.add(aShell, aCore);
  const dotTex = softDot();
  const auraGeo = new THREE.BufferGeometry();
  const auraN = 260, auraPos = new Float32Array(auraN * 3);
  for (let i = 0; i < auraN; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(0.7 + Math.random() * 0.5);
    auraPos.set([v.x, v.y, v.z], i * 3);
  }
  auraGeo.setAttribute("position", new THREE.BufferAttribute(auraPos, 3));
  const aura = new THREE.Points(auraGeo, new THREE.PointsMaterial({ map: dotTex, color: 0x38e1ff, size: 0.07, transparent: true, opacity: 0.6, depthWrite: false, blending: THREE.AdditiveBlending }));
  agentA.add(aura);
  world.add(agentA);

  // ---- the whisper: a packet of particles ----
  const P = small ? 90 : 160;
  const pPos = new Float32Array(P * 3);
  const pOff = new Float32Array(P), pJit = [];
  for (let i = 0; i < P; i++) {
    pOff[i] = Math.random() * 0.22;
    pJit.push(new THREE.Vector3().randomDirection().multiplyScalar(Math.random() * 0.22));
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
  const pMat = new THREE.PointsMaterial({ map: dotTex, color: 0xff6d88, size: 0.12, transparent: true, opacity: 1, depthWrite: false, blending: THREE.AdditiveBlending });
  const packet = new THREE.Points(pGeo, pMat);
  packet.frustumCulled = false;
  world.add(packet);

  // faint guide path
  let curve;
  const guide = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xff5c7a, transparent: true, opacity: 0.18 }));
  world.add(guide);

  // ---- star dust ----
  const S = small ? 900 : 1800;
  const sPos = new Float32Array(S * 3);
  for (let i = 0; i < S; i++) {
    const r = 12 + Math.random() * 40;
    const v = new THREE.Vector3().randomDirection().multiplyScalar(r);
    sPos.set([v.x, v.y * 0.6, v.z - 10], i * 3);
  }
  const sGeo = new THREE.BufferGeometry();
  sGeo.setAttribute("position", new THREE.BufferAttribute(sPos, 3));
  const stars = new THREE.Points(sGeo, new THREE.PointsMaterial({ map: dotTex, color: 0x9aa6ff, size: 0.14, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(stars);

  // ---- post ----
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), small ? 0.7 : 0.85, 0.5, 0.18);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---- layout ----
  const layout = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const narrow = w < 860;
    tower.position.set(narrow ? 0.6 : 4.3, narrow ? 0.4 : -0.6, 0);
    tower.scale.setScalar(narrow ? 0.62 : 0.8);
    agentA.position.set(narrow ? -1.9 : 1.7, narrow ? -3.0 : -2.7, 1.2);
    agentA.scale.setScalar(narrow ? 0.6 : 0.8);
    const base = new THREE.Vector3(0, -TOWER_H / 2 - 0.25, 0).multiplyScalar(tower.scale.x).add(tower.position);
    const a = agentA.position.clone();
    curve = new THREE.CatmullRomCurve3([
      a,
      new THREE.Vector3((a.x + base.x) / 2, Math.min(a.y, base.y) - 1.1, 1.6),
      new THREE.Vector3(base.x - 0.2, base.y - 0.6, 0.6),
      base,
    ]);
    guide.geometry.dispose();
    guide.geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(80));
  };
  layout();
  window.addEventListener("resize", layout);

  // ---- interaction ----
  const mouse = new THREE.Vector2();
  window.addEventListener("pointermove", (e) => {
    mouse.set(e.clientX / window.innerWidth - 0.5, e.clientY / window.innerHeight - 0.5);
  });

  let visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 }).observe(canvas);

  const clock = new THREE.Clock();
  const tmp = new THREE.Vector3();
  let lastState = 0;

  const frame = () => {
    requestAnimationFrame(frame);
    if (!visible) return;
    const t = reduce ? 3.0 : clock.getElapsedTime();
    towerMat.uniforms.uTime.value = t;

    // one whisper per cycle: 0-0.38 travel, 0.38-0.88 climb, 0.88-1 rest
    const ph = (t % CYCLE) / CYCLE;
    const travel = Math.min(ph / 0.38, 1);
    const climb = THREE.MathUtils.clamp((ph - 0.38) / 0.5, 0, 1);
    const pulseLayer = ph < 0.38 ? -10 : climb * (N_LAYERS + 4) - 2;
    towerMat.uniforms.uPulse.value = pulseLayer;
    const flare = Math.exp(-Math.pow(pulseLayer - (HOT - 1), 2) / 3);
    towerMat.uniforms.uFlare.value = flare + 0.15 * Math.sin(t * 2.0) + 0.15;
    halo.material.opacity = 0.35 + flare * 0.65;
    halo.scale.setScalar(1 + flare * 0.18);

    // packet particles
    const head = ph < 0.38 ? travel * 1.22 : 2;
    const sc = tower.scale.x;
    for (let i = 0; i < P; i++) {
      const u = head - pOff[i];
      if (u >= 0 && u <= 1) {
        curve.getPointAt(Math.min(u, 1), tmp);
        const spread = 0.35 + Math.sin(u * Math.PI) * 0.9;
        tmp.addScaledVector(pJit[i], spread);
      } else if (ph >= 0.38 && ph < 0.92) {
        // inside the tower: ride the residual stream upward with the pulse
        const yN = THREE.MathUtils.clamp(pulseLayer / (N_LAYERS - 1), 0, 1.05) - pOff[i] * 0.4;
        const ang = i * 2.39996 + t * 2.0;
        const rr = 0.12 + pOff[i] * 1.2;
        tmp.set(Math.cos(ang) * rr, (yN - 0.5) * TOWER_H, Math.sin(ang) * rr).multiplyScalar(sc).add(tower.position);
      } else {
        tmp.set(0, -999, 0);
      }
      pPos[i * 3] = tmp.x; pPos[i * 3 + 1] = tmp.y; pPos[i * 3 + 2] = tmp.z;
    }
    pGeo.attributes.position.needsUpdate = true;
    pMat.opacity = ph < 0.9 ? 1 : 1 - (ph - 0.9) * 10;

    // score flips once the pulse passes the top
    const state = ph > 0.84 || ph < 0.04 ? 1 : 0;
    if (state !== lastState) {
      score.material.map = state ? tex4 : tex8;
      score.material.needsUpdate = true;
      lastState = state;
    }
    const pop = ph > 0.84 ? Math.exp(-(ph - 0.84) * 30) : 0;
    score.scale.set(3.4 * (1 + pop * 0.3), 1.7 * (1 + pop * 0.3), 1);
    crownCore.scale.setScalar(1 + pop * 1.4);

    // agents breathe
    aShell.rotation.set(t * 0.3, t * 0.45, 0);
    aura.rotation.y = -t * 0.2;
    aCore.scale.setScalar(1 + (ph < 0.06 ? (0.06 - ph) * 8 : 0) + Math.sin(t * 3) * 0.04);
    crown.rotation.set(t * 0.4, t * 0.25, 0);
    stars.rotation.y = t * 0.008;

    // camera drift + scroll dolly
    const sy = Math.min(window.scrollY / window.innerHeight, 1.2);
    camera.position.x += (mouse.x * 1.4 - camera.position.x) * 0.04;
    camera.position.y += (0.4 - mouse.y * 0.9 + sy * 1.5 - camera.position.y) * 0.04;
    camera.position.z = 14 - sy * 3;
    camera.lookAt(0.6, sy * 1.2, 0);
    world.rotation.y = Math.sin(t * 0.12) * 0.08 + mouse.x * 0.08;

    composer.render();
  };
  frame();
}
