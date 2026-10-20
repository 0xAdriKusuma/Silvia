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
// Render Loop
// ============================================================
const { scene, camera, renderer, controls } = initScene();
const clock = new THREE.Clock();

let frameCount   = 0;
let lastFpsTime  = performance.now();

renderer.setAnimationLoop(() => {
  // Batasi dt maksimum 0.1 detik agar tab tidak aktif tidak menyebabkan lonjakan
  const rawDt = clock.getDelta();
  const dt    = Math.min(rawDt, 0.1);

  // Hitung FPS
  frameCount++;
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    const fps = Math.round((frameCount * 1000) / (now - lastFpsTime));
    updateFps(fps);
    frameCount  = 0;
    lastFpsTime = now;
  }

  // ── Urutan update per frame (SANGAT PENTING) ──────────────────────────
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

  // 6. Orbit controls & render
  controls.update();
  renderer.render(scene, camera);
});

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
