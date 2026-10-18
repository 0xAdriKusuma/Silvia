/**
 * main.js - Frontend Silvia Avatar AI
 *
 * Tanggung jawab:
 *   - Muat VRM + animasi VRMA via Three.js
 *   - Idle prosedural (pose santai + napas)
 *   - Ekspresi wajah (emosi, blink, lip-sync)
 *   - WebSocket (terima baris audio/metadata dari server)
 *   - Web Audio API (putar audio, analisa amplitudo untuk lip-sync)
 *   - Panel uji
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import {
  VRMAnimationLoaderPlugin,
  VRMLookAtQuaternionProxy,
  createVRMAnimationClip,
} from '@pixiv/three-vrm-animation';

// ============================================================
// Konstanta
// ============================================================
const WS_URL = `ws://${location.host}/ws`;
const FADE_DURATION = 0.25;          // crossfade animasi (detik)
const IDLE_DURATION = 5.0;           // durasi satu siklus idle (detik)
const EXPR_LERP_SPEED = 8.0;         // kecepatan transisi ekspresi (per detik)
const BLINK_INTERVAL_MIN = 2.5;      // interval kedip min (detik)
const BLINK_INTERVAL_MAX = 5.5;      // interval kedip max (detik)
const BLINK_DURATION = 0.15;         // durasi kedip (detik)
const MOUTH_NOISE_GATE = 0.015;      // ambang bawah lip-sync
const MOUTH_GAIN = 1.5;              // penguatan amplitudo -> bobot mulut
const MOUTH_MAX = 0.7;               // batas atas bobot mulut
const MOUTH_RISE = 15.0;            // kecepatan naik mulut (per detik)
const MOUTH_FALL = 5.0;             // kecepatan turun mulut (per detik)
const EXPR_RETURN_DELAY = 0.6;       // detik setelah audio selesai baru balik neutral

// ============================================================
// State Global
// ============================================================
let vrm = null;
let mixer = null;
let idleAction = null;
let currentAction = null;
let appConfig = null;          // data dari /api/config
let animationClips = {};       // { nama: THREE.AnimationClip }
let availableExprs = new Set();// ekspresi yang benar-benar ada di model

// Ekspresi target saat ini (diisi dari emosi tag LLM)
let targetExpression = {};
// Ekspresi sedang aktif (lerp menuju target)
let currentExprWeights = {};

// Helper
function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

// Blink state
let blinkTimer = 0;
let blinkDuration = 0;
let blinkActive = false;
let nextBlinkIn = randomBetween(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);

// Lip-sync state
let mouthWeight = 0;     // bobot 'aa' saat ini
let mouthTarget = 0;     // bobot target dari audio analyser
let manualMouth = 0;     // dari slider debug

// Audio
let audioCtx = null;
let analyserNode = null;
let analyserBuffer = null;

// WebSocket
let ws = null;
let wsReady = false;

// Antrian pemutaran baris
const lineQueue = [];
let isPlayingLine = false;

// Timer untuk kembali ke neutral setelah speaking
let returnNeutralTimer = null;

// ============================================================
// Three.js Setup
// ============================================================
const canvasWrap = document.getElementById('canvas-wrap');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
canvasWrap.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d0f14);

// Pencahayaan
const dirLight = new THREE.DirectionalLight(0xffffff, Math.PI * 0.9);
dirLight.position.set(1, 2, 2);
scene.add(dirLight);
scene.add(new THREE.AmbientLight(0x8890cc, 0.8));

// Kamera (gaya streamer: pinggang ke atas)
const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 50);
camera.position.set(0, 1.35, 2.6);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.2, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.8;
controls.maxDistance = 6;
controls.maxPolarAngle = Math.PI * 0.72;
controls.update();

// Resize handler
function onResize() {
  const w = canvasWrap.clientWidth, h = canvasWrap.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(onResize).observe(canvasWrap);
onResize();

// ============================================================
// Loader VRM
// ============================================================
const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));
loader.register((p) => new VRMAnimationLoaderPlugin(p));

/**
 * Muat model VRM dari URL.
 */
async function loadVRM(url) {
  const gltf = await loader.loadAsync(url);
  const nextVrm = gltf.userData.vrm;
  if (!nextVrm) throw new Error('Bukan file VRM yang valid: ' + url);

  VRMUtils.rotateVRM0(nextVrm); // rotasi VRM 0.x -> menghadap +Z

  if (vrm) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose?.(vrm.scene);
  }
  if (mixer) mixer.stopAllAction();

  vrm = nextVrm;
  vrm.scene.traverse((o) => { o.frustumCulled = false; });

  // Lookup-at: mata mengikuti kamera
  if (vrm.lookAt) {
    const proxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
    proxy.name = 'lookAtQuaternionProxy';
    vrm.scene.add(proxy);
    vrm.lookAt.target = camera;
  }

  scene.add(vrm.scene);

  // Mixer baru
  mixer = new THREE.AnimationMixer(vrm.scene);
  mixer.addEventListener('finished', onAnimationFinished);

  // Catat ekspresi yang tersedia
  discoverExpressions();

  // Buat idle clip prosedural & mulai
  idleAction = createIdleAction();
  idleAction.play();
  currentAction = idleAction;

  // Bingkai kamera ke model
  frameCamera();

  console.log('[VRM] Model dimuat:', url);
}

/**
 * Muat semua animasi VRMA dari config.
 */
async function loadAnimations(animationsMap) {
  animationClips = {};
  for (const [name, url] of Object.entries(animationsMap)) {
    try {
      const gltf = await loader.loadAsync(url);
      const va = gltf.userData.vrmAnimations?.[0];
      if (!va) throw new Error('Tidak ada VRMAnimation di file');
      if (!vrm) throw new Error('VRM belum dimuat');
      const clip = createVRMAnimationClip(va, vrm);
      clip.name = name;
      animationClips[name] = clip;
      console.log(`[VRMA] Dimuat: ${name}`);
    } catch (e) {
      console.warn(`[VRMA] Gagal memuat animasi '${name}':`, e.message);
    }
  }
}

// ============================================================
// Idle Prosedural (Three.AnimationClip)
// ============================================================
/**
 * Buat AnimationClip idle prosedural.
 * Target bone menggunakan nama node normalisasi VRM agar
 * crossfade lewat mixer yang sama dengan VRMA berjalan otomatis.
 */
function createIdleAction() {
  if (!vrm || !mixer) return null;

  const humanoid = vrm.humanoid;
  const T = IDLE_DURATION;

  // Helper: buat track QuaternionKeyframe untuk satu bone
  function boneTrack(boneName, keyTimes, keyValues) {
    const node = humanoid.getNormalizedBoneNode(boneName);
    if (!node) return null;
    return new THREE.QuaternionKeyframeTrack(
      `${node.name}.quaternion`,
      keyTimes,
      keyValues,
      THREE.InterpolateSmooth,
    );
  }

  const tracks = [];

  // ---------- Pose dasar santai: lengan diturunkan ke samping ----------
  // VRM menghadap +Z setelah rotateVRM0.
  // LeftUpperArm : rotasi sumbu -Z (mendekat ke tubuh dari sisi kiri)
  // RightUpperArm: rotasi sumbu +Z (mendekat ke tubuh dari sisi kanan)
  // Siku sedikit tertekuk (rotasi -Z kecil pada forearm)

  const larmQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08, 0.05, -1.15));
  const rarmQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08, -0.05, 1.15));
  const lforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -0.25));
  const rforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, 0.25));

  const staticArr = (q) => [q.x, q.y, q.z, q.w, q.x, q.y, q.z, q.w];

  const larm = boneTrack('leftUpperArm', [0, T], staticArr(larmQ));
  const rarm = boneTrack('rightUpperArm', [0, T], staticArr(rarmQ));
  const lfore = boneTrack('leftLowerArm', [0, T], staticArr(lforeQ));
  const rfore = boneTrack('rightLowerArm', [0, T], staticArr(rforeQ));

  if (larm) tracks.push(larm);
  if (rarm) tracks.push(rarm);
  if (lfore) tracks.push(lfore);
  if (rfore) tracks.push(rfore);

  // ---------- Napas (spine naik-turun ~0.25 Hz, satu siklus = T) ----------
  const breathSteps = 9;
  const breathTimes = Array.from({ length: breathSteps }, (_, i) => (i / (breathSteps - 1)) * T);
  const spineBreath = [];
  for (let i = 0; i < breathSteps; i++) {
    const phase = (i / (breathSteps - 1)) * Math.PI * 2;
    const amp = 0.018;
    const q = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(Math.sin(phase) * amp, 0, 0)
    );
    spineBreath.push(q.x, q.y, q.z, q.w);
  }
  const spineTrack = boneTrack('spine', breathTimes, spineBreath);
  if (spineTrack) tracks.push(spineTrack);

  // Chest sedikit mengikuti spine (setengah amplitudo)
  const chestBreath = [];
  for (let i = 0; i < breathSteps; i++) {
    const phase = (i / (breathSteps - 1)) * Math.PI * 2;
    const amp = 0.01;
    const q = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(Math.sin(phase) * amp, 0, 0)
    );
    chestBreath.push(q.x, q.y, q.z, q.w);
  }
  const chestTrack = boneTrack('chest', breathTimes, chestBreath);
  if (chestTrack) tracks.push(chestTrack);

  // ---------- Kepala goyang kecil ----------
  const headSteps = 5;
  const headTimes = Array.from({ length: headSteps }, (_, i) => (i / (headSteps - 1)) * T);
  const headVals = [];
  for (let i = 0; i < headSteps; i++) {
    const phase = (i / (headSteps - 1)) * Math.PI * 2;
    const q = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(0.04 + Math.sin(phase * 0.5) * 0.015, Math.sin(phase * 0.3) * 0.025, 0)
    );
    headVals.push(q.x, q.y, q.z, q.w);
  }
  const headTrack = boneTrack('head', headTimes, headVals);
  if (headTrack) tracks.push(headTrack);

  if (!tracks.length) {
    console.warn('[Idle] Tidak ada bone ditemukan; idle tidak aktif.');
    return null;
  }

  const clip = new THREE.AnimationClip('idle', T, tracks);
  const action = mixer.clipAction(clip);
  action.setLoop(THREE.LoopRepeat, Infinity);
  action.clampWhenFinished = false;
  return action;
}

// ============================================================
// Animasi VRMA
// ============================================================
/**
 * Mainkan animasi sekali-putar dengan crossfade dari/ke idle.
 */
function playAnimation(name) {
  if (!vrm || !mixer) return;
  const clip = animationClips[name];
  if (!clip) {
    console.warn(`[VRMA] Animasi '${name}' tidak ada di model ini, dilewati.`);
    return;
  }

  const prev = currentAction;
  const next = mixer.clipAction(clip);
  next.setLoop(THREE.LoopOnce, 1);
  next.clampWhenFinished = false;
  next.enabled = true;
  next.reset().fadeIn(FADE_DURATION).play();

  if (prev && prev !== next) {
    prev.fadeOut(FADE_DURATION);
  }

  currentAction = next;
}

/**
 * Kembali ke idle dengan crossfade.
 */
function returnToIdle() {
  if (!idleAction || currentAction === idleAction) return;
  const prev = currentAction;
  idleAction.enabled = true;
  idleAction.reset().fadeIn(FADE_DURATION).play();
  if (prev) prev.fadeOut(FADE_DURATION);
  currentAction = idleAction;
}

function onAnimationFinished(e) {
  if (e.action !== currentAction) return;
  if (e.action !== idleAction) {
    returnToIdle();
  }
}

// ============================================================
// Ekspresi Wajah
// ============================================================
/**
 * Deteksi ekspresi yang benar-benar ada di model.
 */
function discoverExpressions() {
  availableExprs.clear();
  const em = vrm?.expressionManager;
  if (!em) { console.warn('[Expr] Model tidak punya expressionManager.'); return; }

  const names = em.expressions?.map((e) => e.expressionName) ?? [];
  names.forEach((n) => availableExprs.add(n));
  console.log('[Expr] Ekspresi tersedia:', [...availableExprs].join(', '));
}

/**
 * Set target ekspresi dari peta emosi (dari config emotion_expression).
 */
function setEmotion(emotionName) {
  if (!appConfig) return;
  const exprMap = appConfig.emotion_expression[emotionName] ?? {};
  targetExpression = {};
  for (const [expr, weight] of Object.entries(exprMap)) {
    if (availableExprs.has(expr)) {
      targetExpression[expr] = weight;
    }
  }
}

/**
 * Terapkan semua bobot ekspresi ke expressionManager (via lerp per frame).
 * Dipanggil di render loop.
 */
function updateExpressions(dt) {
  const em = vrm?.expressionManager;
  if (!em) return;

  // Gabungkan: target emosi + blink + mulut
  const combined = { ...targetExpression };

  // Blink override (kecuali sleepy sudah mengatur relaxed)
  if (availableExprs.has('blink')) {
    combined['blink'] = (combined['blink'] ?? 0) + blinkWeight();
    combined['blink'] = Math.min(combined['blink'], 1.0);
  }

  // Mulut lip-sync
  const mouthVal = Math.max(manualMouth, mouthWeight);
  if (availableExprs.has('aa') && mouthVal > 0.001) {
    combined['aa'] = mouthVal;
  }

  // Lerp semua ekspresi
  for (const expr of availableExprs) {
    const target = combined[expr] ?? 0;
    currentExprWeights[expr] = currentExprWeights[expr] ?? 0;
    const cur = currentExprWeights[expr];
    const next = cur + (target - cur) * Math.min(1, EXPR_LERP_SPEED * dt);
    currentExprWeights[expr] = next;
    try { em.setValue(expr, next); } catch (_) { }
  }
}

// ============================================================
// Kedipan Otomatis
// ============================================================
function blinkWeight() {
  if (!blinkActive) return 0;
  // Blink: segitiga naik 0->0.5 lalu turun 0.5->1 dalam BLINK_DURATION
  const half = BLINK_DURATION / 2;
  const t = blinkDuration;
  return t < half ? t / half : 1 - (t - half) / half;
}

function updateBlink(dt) {
  blinkTimer += dt;
  if (blinkActive) {
    blinkDuration += dt;
    if (blinkDuration >= BLINK_DURATION) {
      blinkActive = false;
      blinkDuration = 0;
      nextBlinkIn = randomBetween(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);
      blinkTimer = 0;
    }
  } else {
    if (blinkTimer >= nextBlinkIn) {
      blinkActive = true;
      blinkDuration = 0;
      blinkTimer = 0;
    }
  }
}

// ============================================================
// Lip-Sync (Web Audio API)
// ============================================================
/**
 * Inisialisasi AudioContext (dipanggil setelah klik overlay).
 */
function initAudioContext() {
  if (audioCtx) return;
  audioCtx = new AudioContext();
  analyserNode = audioCtx.createAnalyser();
  analyserNode.fftSize = 256;
  analyserNode.smoothingTimeConstant = 0.5;
  analyserNode.connect(audioCtx.destination);
  analyserBuffer = new Float32Array(analyserNode.frequencyBinCount);
}

/**
 * Putar audio MP3 (bytes) dan kembalikan Promise yang resolve saat selesai.
 */
function playAudioBuffer(arrayBuffer) {
  return new Promise((resolve) => {
    if (!audioCtx) { resolve(); return; }
    audioCtx.decodeAudioData(arrayBuffer, (decoded) => {
      const src = audioCtx.createBufferSource();
      src.buffer = decoded;
      src.connect(analyserNode);
      src.start(0);
      src.onended = resolve;
    }, (err) => {
      console.error('[Audio] Gagal decode:', err);
      resolve();
    });
  });
}

/**
 * Update amplitudo dari analyser -> mouthTarget (dipanggil di render loop).
 */
function updateLipSync(dt) {
  if (!analyserNode) { mouthTarget = 0; return; }
  analyserNode.getFloatTimeDomainData(analyserBuffer);
  let rms = 0;
  for (let i = 0; i < analyserBuffer.length; i++) rms += analyserBuffer[i] * analyserBuffer[i];
  rms = Math.sqrt(rms / analyserBuffer.length);

  const raw = rms < MOUTH_NOISE_GATE ? 0 : Math.min(rms * MOUTH_GAIN, MOUTH_MAX);
  mouthTarget = raw;

  // Smoothing: naik cepat, turun lambat
  const speed = mouthWeight < mouthTarget ? MOUTH_RISE : MOUTH_FALL;
  mouthWeight += (mouthTarget - mouthWeight) * Math.min(1, speed * dt);
}

// ============================================================
// Kamera Framing
// ============================================================
function frameCamera() {
  if (!vrm) return;
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const fov = THREE.MathUtils.degToRad(camera.fov);
  // Frame pinggang ke atas: target di ~60% tinggi model
  const targetY = box.min.y + size.y * 0.6;
  controls.target.set(0, targetY, 0);
  const dist = (size.y * 0.55) / Math.tan(fov / 2);
  camera.position.set(0, targetY + 0.05, dist);
  controls.update();
}

// ============================================================
// WebSocket
// ============================================================
let wsReconnectTimer = null;

function connectWS() {
  if (ws && ws.readyState < 2) ws.close();
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsReady = true;
    console.log('[WS] Terhubung');
    setStatusUI('listening');
  };

  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleWSMessage(msg);
  };

  ws.onerror = (e) => console.warn('[WS] Error:', e);

  ws.onclose = () => {
    wsReady = false;
    setStatusUI('disconnected');
    // Auto-reconnect 3 detik
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWS, 3000);
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'status':
      setStatusUI(msg.state);
      break;
    case 'user_text':
      showUserText(msg.text);
      break;
    case 'line':
      // Masukkan ke antrian; pemutaran berurutan
      lineQueue.push(msg);
      processLineQueue();
      break;
    case 'turn_end':
      // Ditangani di processLineQueue setelah antrean kosong
      lineQueue.push({ type: 'turn_end' });
      processLineQueue();
      break;
    case 'error':
      showToast(msg.message);
      break;
  }
}

// ============================================================
// Antrean Pemutaran Baris
// ============================================================
async function processLineQueue() {
  if (isPlayingLine) return;
  if (!lineQueue.length) return;
  isPlayingLine = true;

  while (lineQueue.length > 0) {
    const item = lineQueue.shift();

    if (item.type === 'turn_end') {
      // Semua baris selesai: kembalikan ke neutral & idle
      clearTimeout(returnNeutralTimer);
      returnNeutralTimer = setTimeout(() => {
        setEmotion('neutral');
        returnToIdle();
      }, EXPR_RETURN_DELAY * 1000);

      // Beritahu server bahwa pemutaran selesai
      sendWS({ type: 'playback_done' });
      break;
    }

    if (item.type !== 'line') continue;

    // 1. Set ekspresi emosi
    setEmotion(item.emotion);
    clearTimeout(returnNeutralTimer);

    // 2. Picu animasi VRMA (jika ada)
    if (item.animation) {
      playAnimation(item.animation);
    }

    // 3. Update subtitle
    setSubtitle(item.jp, item.id);
    setStatusUI('speaking');

    // 4. Putar audio
    if (item.audio) {
      const binStr = atob(item.audio);
      const buf = new ArrayBuffer(binStr.length);
      const view = new Uint8Array(buf);
      for (let i = 0; i < binStr.length; i++) view[i] = binStr.charCodeAt(i);
      await playAudioBuffer(buf);
    }
  }

  isPlayingLine = false;
  processLineQueue(); // proses baris baru yang mungkin masuk saat sedang memutar
}

function sendWS(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

// ============================================================
// UI Helpers
// ============================================================
const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const subtitleJp = document.getElementById('subtitle-jp');
const subtitleId = document.getElementById('subtitle-id');
const userTextEl = document.getElementById('user-text');

const STATUS_LABELS = {
  listening: 'Mendengarkan...',
  transcribing: 'Mentranskripsi...',
  thinking: 'Berpikir...',
  speaking: 'Berbicara...',
  disconnected: 'Terputus – menyambung kembali...',
};

function setStatusUI(state) {
  statusPill.dataset.state = state;
  statusText.textContent = STATUS_LABELS[state] ?? state;
}

function setSubtitle(jp, id) {
  subtitleJp.textContent = jp ?? '';
  subtitleId.textContent = id ?? '';
}

let userTextTimer = null;
function showUserText(text) {
  userTextEl.textContent = '🎤 ' + text;
  userTextEl.classList.add('visible');
  clearTimeout(userTextTimer);
  userTextTimer = setTimeout(() => userTextEl.classList.remove('visible'), 8000);
}

const toast = document.getElementById('toast');
let toastTimer = null;
function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 5000);
}

// ============================================================
// Panel Uji
// ============================================================
function buildDebugPanel() {
  // Tombol animasi
  const animBtns = document.getElementById('anim-btns');
  animBtns.innerHTML = '';
  for (const name of Object.keys(animationClips)) {
    const btn = document.createElement('button');
    btn.className = 'dbg-btn';
    btn.textContent = name;
    btn.onclick = () => playAnimation(name);
    animBtns.appendChild(btn);
  }
  if (!animBtns.children.length) {
    animBtns.innerHTML = '<span style="font-size:12px;color:var(--muted)">Tidak ada animasi dimuat.</span>';
  }

  // Tombol emosi
  const emotionBtns = document.getElementById('emotion-btns');
  emotionBtns.innerHTML = '';
  const emotions = appConfig?.emotions ?? [];
  for (const em of emotions) {
    const btn = document.createElement('button');
    btn.className = 'dbg-btn';
    btn.textContent = em;
    btn.onclick = () => setEmotion(em);
    emotionBtns.appendChild(btn);
  }

  // Animasi yang hilang
  const missing = appConfig?.missing_animations ?? [];
  const missingSection = document.getElementById('missing-anim-section');
  if (missing.length) {
    missingSection.style.display = '';
    document.getElementById('missing-anim-list').textContent = missing.join(', ');
  }
}

// Slider mulut manual
const mouthSlider = document.getElementById('mouth-slider');
const mouthVal = document.getElementById('mouth-val');
mouthSlider.oninput = (e) => {
  manualMouth = Number(e.target.value) / 100;
  mouthVal.textContent = `${e.target.value}%`;
};

// Toggle panel uji
const debugPanel = document.getElementById('debug-panel');
document.getElementById('btn-debug-toggle').onclick = () => {
  debugPanel.classList.toggle('hidden');
};
window.addEventListener('keydown', (e) => {
  if (e.key === 'd' || e.key === 'D') {
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
    debugPanel.classList.toggle('hidden');
  }
});

// Toggle terjemahan
const btnToggleId = document.getElementById('btn-toggle-id');
btnToggleId.onclick = () => {
  const hidden = subtitleId.classList.toggle('hidden');
  btnToggleId.textContent = hidden ? 'Tampilkan terjemahan' : 'Sembunyikan terjemahan';
};

// Input teks
const textInput = document.getElementById('text-input');
const btnSend = document.getElementById('btn-send');

function sendTextInput() {
  const text = textInput.value.trim();
  if (!text) return;
  sendWS({ type: 'user_text', text });
  showUserText(text);
  textInput.value = '';
}

btnSend.onclick = sendTextInput;
textInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTextInput(); }
});

// ============================================================
// Render Loop
// ============================================================
const clock = new THREE.Clock();

renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();

  // 1. Update mixer animasi VRMA/idle
  if (mixer) mixer.update(dt);

  // 2. Update blink
  updateBlink(dt);

  // 3. Update lip-sync (amplitudo -> mouthWeight)
  updateLipSync(dt);

  // 4. Update ekspresi (lerp ke target)
  updateExpressions(dt);

  // 5. Update VRM (spring bones, dll.)
  if (vrm) vrm.update(dt);

  // 6. Update orbit controls
  controls.update();

  // 7. Render
  renderer.render(scene, camera);
});

// ============================================================
// Inisialisasi Utama
// ============================================================
async function init() {
  // Ambil konfigurasi dari server
  let cfg;
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }
    cfg = await resp.json();
    appConfig = cfg;
  } catch (e) {
    showToast('Gagal mengambil konfigurasi server: ' + e.message);
    document.getElementById('start-status').textContent = 'Gagal konek ke server (' + e.message + ')';
    return;
  }

  if (!cfg.vrm_url) {
    document.getElementById('start-status').textContent =
      'File .vrm tidak ditemukan di folder assets/.';
    showToast('File .vrm tidak ditemukan di assets/. Letakkan file .vrm dan restart server.');
    return;
  }

  // Muat VRM
  document.getElementById('start-status').textContent = 'Memuat model VRM...';
  try {
    await loadVRM(cfg.vrm_url);
  } catch (e) {
    document.getElementById('start-status').textContent = 'Gagal muat VRM: ' + e.message;
    showToast('Gagal memuat model VRM: ' + e.message);
    return;
  }

  // Muat animasi VRMA
  document.getElementById('start-status').textContent = 'Memuat animasi...';
  await loadAnimations(cfg.animations);

  // Set ekspresi awal
  setEmotion('neutral');

  // Tampilkan info animasi hilang
  if (cfg.missing_animations?.length) {
    console.warn('[Config] Animasi tidak ditemukan:', cfg.missing_animations.join(', '));
  }

  // Build panel uji
  buildDebugPanel();

  // Hubungkan WebSocket
  connectWS();

  document.getElementById('start-status').textContent = 'Siap!';
}

// Overlay "Mulai" -> buka AudioContext lalu hide overlay
document.getElementById('btn-start').onclick = async () => {
  initAudioContext();
  if (audioCtx?.state === 'suspended') await audioCtx.resume();
  document.getElementById('overlay-start').style.display = 'none';
};

// Jalankan init (muat VRM di background, overlay tetap tampil dulu)
init();
