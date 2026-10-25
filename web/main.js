/**
 * main.js - Frontend Silvia Avatar AI (App Entry Point)
 *
 * Mengoordinasikan modul:
 *   - js/scene.js       : Scene, Camera, Lighting, OrbitControls
 *   - js/avatar.js      : VRM & VRMA Animations (AnimationBlender)
 *   - js/expressions.js : Emosi, Auto-Blink & Lip-Sync Morph Targets
 *   - js/audio.js       : Web Audio API & Analyser
 *   - js/websocket.js   : Komunikasi Server & Antrean Audio
 *   - js/ui.js          : HUD, Subtitle, Debug Panel & Resource Monitor
 */

import * as THREE from 'three';
import { initScene } from './js/scene.js';
import {
  loadVRM,
  loadAnimations,
  updateAvatarAnimation,
  updateAvatarVRM,
  playAnimation,
  animationClips,
  blender,
  vrm,
} from './js/avatar.js';
import {
  setEmotionConfig,
  setEmotion,
  updateBlink,
  updateExpressions,
  getExpressionSnapshot,
} from './js/expressions.js';
import { initAudioContext, updateLipSync, setManualMouth, audioCtx } from './js/audio.js';
import { connectWS, sendWS } from './js/websocket.js';
import {
  initUIListeners,
  buildDebugPanel,
  showToast,
  updateFps,
  updatePerfStats,
} from './js/ui.js';

let appConfig = null;

// ============================================================
// Konfigurasi Target FPS Render
// Default: 30 FPS. Ubah di sini (misal 30, 45, 60, atau null untuk uncapped)
// ============================================================
export let RENDER_FPS = 30;
let renderInterval = 1 / RENDER_FPS;

/**
 * Ubah target FPS render secara dinamis.
 * @param {number|null} fps - Target FPS atau null/0 untuk tanpa batasan
 */
export function setRenderFps(fps) {
  RENDER_FPS = fps && fps > 0 ? fps : null;
  renderInterval = RENDER_FPS ? 1 / RENDER_FPS : 0;
  console.log(`[Render] Target FPS diatur ke: ${RENDER_FPS ?? 'Uncapped'}`);
}
// Ekspos ke global window untuk kemudahan pengujian / live tweak
window.setRenderFps = setRenderFps;

// ============================================================
// Render Loop & Visibilitas / Fokus Jendela
// ============================================================
const { scene, camera, renderer, controls } = initScene();
const clock = new THREE.Clock();

let renderAccumulator = 0;
let renderedFrames    = 0;
let actualFps         = 0;
let lastFpsTime       = performance.now();
let lastDrawCalls     = 0;
let lastTriangles     = 0;
let isRenderPaused    = false;

function renderLoop() {
  // 1. Dapatkan delta time nyata
  const rawDt = clock.getDelta();
  // Batasi dt maksimum 0.1 detik agar kembali fokus/tab tidak menyebabkan lonjakan animasi
  const dt    = Math.min(rawDt, 0.1);

  // 2. Akumulasi waktu render
  renderAccumulator += dt;

  // ── Urutan update per frame (SANGAT PENTING) ──────────────────────────
  // Logika dan animasi selalu diperbarui setiap frame dengan dt nyata agar kecepatan
  // gerakan, interpolasi, kedipan, fisika rambut/baju (springBone), dan audio tetap sinkron.
  // 1. Hitung transformasi tulang dari animasi (blender & mixer)
  updateAvatarAnimation(dt);

  // 2. Kedipan mata otomatis
  updateBlink(dt);

  // 3. Audio lip-sync analyser
  updateLipSync(dt);

  // 4. Hitung & set bobot emosi, blink, dan mulut ke expressionManager
  updateExpressions(vrm, dt);

  // 5. Terapkan ke model VRM (termasuk expressionManager.update() dan springBone)
  // Dipanggil SETELAH expressions agar langsung diterapkan di frame yang sama
  updateAvatarVRM(dt);

  // 6. Orbit controls damping
  controls.update();

  // 7. Render grafis hanya jika sudah waktunya sesuai target FPS
  const targetInterval = renderInterval;
  if (!targetInterval || renderAccumulator >= targetInterval) {
    if (targetInterval) {
      renderAccumulator -= targetInterval;
      // Bila akumulator tertinggal jauh akibat lag, batasi agar tidak memicu render beruntun
      if (renderAccumulator > targetInterval) {
        renderAccumulator = 0;
      }
    }

    renderer.render(scene, camera);
    lastDrawCalls = renderer.info.render.calls;
    lastTriangles = renderer.info.render.triangles;
    renderedFrames++;
  }

  // Hitung FPS render aktual setiap detik
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    actualFps = Math.round((renderedFrames * 1000) / (now - lastFpsTime));
    updateFps(actualFps);
    renderedFrames = 0;
    lastFpsTime = now;
  }
}

// ── Pengelolaan Tab Hidden & Window Blur/Focus ──────────────────────────
function pauseRenderLoop() {
  if (isRenderPaused) return;
  isRenderPaused = true;
  renderer.setAnimationLoop(null);
  updateFps(0);
}

function resumeRenderLoop() {
  if (!isRenderPaused) return;
  isRenderPaused = false;
  // Buang akumulasi waktu selama jeda agar getDelta frame berikutnya bersih
  clock.getDelta();
  renderAccumulator = 0;
  renderedFrames = 0;
  lastFpsTime = performance.now();
  renderer.setAnimationLoop(renderLoop);
}

function checkTabAndWindowFocus() {
  const isVisible = !document.hidden;
  const isFocused = typeof document.hasFocus === 'function' ? document.hasFocus() : true;

  if (isVisible && isFocused) {
    resumeRenderLoop();
  } else {
    pauseRenderLoop();
  }
}

// Pantau Page Visibility API dan event blur/focus jendela
document.addEventListener('visibilitychange', checkTabAndWindowFocus);
window.addEventListener('blur', checkTabAndWindowFocus);
window.addEventListener('focus', checkTabAndWindowFocus);

// Mulai loop awal
renderer.setAnimationLoop(renderLoop);

// ============================================================
// Inisialisasi Aplikasi
// ============================================================
async function init() {
  initUIListeners({
    onSendText:    (text) => sendWS({ type: 'user_text', text }),
    onMouthSlider: (val)  => setManualMouth(val),
  });

  // Ambil konfigurasi dari backend
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    appConfig = await resp.json();
    setEmotionConfig(appConfig.emotion_expression);
  } catch (e) {
    showToast('Gagal mengambil konfigurasi: ' + e.message);
    document.getElementById('start-status').textContent =
      'Gagal terhubung ke server (' + e.message + ')';
    return;
  }

  if (!appConfig.vrm_url) {
    document.getElementById('start-status').textContent =
      'File .vrm tidak ditemukan di folder assets/.';
    showToast('File .vrm tidak ditemukan. Letakkan file .vrm dan restart server.');
    return;
  }

  // Peringatan jika Idle.vrma tidak ditemukan
  if (!appConfig.idle_url) {
    showToast('⚠ Idle.vrma tidak ditemukan – menggunakan idle prosedural.');
    console.warn('[Init] idle_url tidak tersedia di /api/config – pakai idle prosedural.');
  }

  // 1. Muat Model VRM
  document.getElementById('start-status').textContent = 'Memuat model VRM...';
  try {
    await loadVRM(appConfig.vrm_url, scene, camera);
  } catch (e) {
    document.getElementById('start-status').textContent = 'Gagal muat VRM: ' + e.message;
    showToast('Gagal memuat model VRM: ' + e.message);
    return;
  }

  // 2. Set konfigurasi emosi SEBELUM loadAnimations (diperlukan oleh discoverExpressions)
  setEmotionConfig(appConfig.emotion_expression);

  // 3. Muat Animasi VRMA
  document.getElementById('start-status').textContent = 'Memuat animasi...';
  await loadAnimations(appConfig.animations, appConfig.idle_url ?? null);

  // 4. Set Emosi Awal
  setEmotion('neutral');

  // 5. Bangun Panel Uji Debug (setelah animasi dimuat agar daftar lengkap)
  buildDebugPanel({
    animationClips,
    appConfig,
    onPlayAnimation: (name)    => playAnimation(name),
    onSetEmotion:    (em)      => setEmotion(em),
    getBlenderState: ()        => ({
      weights:     blender?.getWeights()     ?? {},
      totalWeight: blender?.getTotalWeight() ?? 0,
      active:      blender?.getActiveName()  ?? '-',
    }),
    getExprSnapshot: () => getExpressionSnapshot(),
    getRenderStats:  () => ({
      fps:         actualFps,
      targetFps:   RENDER_FPS,
      drawCalls:   lastDrawCalls,
      triangles:   lastTriangles,
      pixelRatio:  renderer?.getPixelRatio() ?? 1,
      isPaused:    isRenderPaused,
    }),
    onSetRenderFps: (fps) => setRenderFps(fps),
  });

  // Ekspos fungsi kontrol timeScale ke global untuk tombol slow-mo di ui.js
  window._setTimeScale = (scale) => {
    if (blender) blender.timeScale = scale;
    console.log(`[Debug] timeScale diatur ke ${scale}`);
  };

  // 6. Polling Awal Statistik Sistem
  fetch('/api/stats')
    .then((r)  => r.json())
    .then((s)  => updatePerfStats(s))
    .catch(() => {});

  // 7. Hubungkan WebSocket
  connectWS();

  document.getElementById('start-status').textContent = 'Siap!';
}

// Overlay Start Listener
document.getElementById('btn-start').onclick = async () => {
  initAudioContext();
  if (audioCtx?.state === 'suspended') await audioCtx.resume();
  document.getElementById('overlay-start').style.display = 'none';
};

init();
