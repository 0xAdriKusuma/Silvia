/**
 * main.js - Frontend Silvia Avatar AI (App Entry Point)
 *
 * Mengoordinasikan modul:
 *   - js/scene.js       : Scene, Camera, Lighting, OrbitControls
 *   - js/avatar.js      : VRM & VRMA Animations (Looping Idle & Gestures)
 *   - js/expressions.js : Emosi, Auto-Blink & Lip-Sync Morph Targets
 *   - js/audio.js       : Web Audio API & Analyser
 *   - js/websocket.js   : Komunikasi Server & Antrean Audio
 *   - js/ui.js          : HUD, Subtitle, Debug Panel & Resource Monitor
 */

import * as THREE from 'three';
import { initScene } from './js/scene.js';
import { loadVRM, loadAnimations, updateAvatar, playAnimation, animationClips, vrm } from './js/avatar.js';
import { setEmotionConfig, setEmotion, updateBlink, updateExpressions } from './js/expressions.js';
import { initAudioContext, updateLipSync, setManualMouth, audioCtx } from './js/audio.js';
import { connectWS, sendWS } from './js/websocket.js';
import { initUIListeners, buildDebugPanel, showToast, updateFps, updatePerfStats } from './js/ui.js';

let appConfig = null;

// ============================================================
// Render Loop
// ============================================================
const { scene, camera, renderer, controls } = initScene();
const clock = new THREE.Clock();

let frameCount = 0;
let lastFpsTime = performance.now();

renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();

  // Hitung FPS
  frameCount++;
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    const fps = Math.round((frameCount * 1000) / (now - lastFpsTime));
    updateFps(fps);
    frameCount = 0;
    lastFpsTime = now;
  }

  // 1. Animasi avatar & mixer
  updateAvatar(dt);

  // 2. Kedipan mata otomatis
  updateBlink(dt);

  // 3. Audio lip-sync analyser
  updateLipSync(dt);

  // 4. Ekspresi wajah & mulut
  updateExpressions(vrm, dt);

  // 5. Orbit controls & render
  controls.update();
  renderer.render(scene, camera);
});

// ============================================================
// Inisialisasi Aplikasi
// ============================================================
async function init() {
  initUIListeners({
    onSendText: (text) => sendWS({ type: 'user_text', text }),
    onMouthSlider: (val) => setManualMouth(val),
  });

  // Ambil konfigurasi dari backend
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    appConfig = await resp.json();
    setEmotionConfig(appConfig.emotion_expression);
  } catch (e) {
    showToast('Gagal mengambil konfigurasi: ' + e.message);
    document.getElementById('start-status').textContent = 'Gagal terhubung ke server (' + e.message + ')';
    return;
  }

  if (!appConfig.vrm_url) {
    document.getElementById('start-status').textContent = 'File .vrm tidak ditemukan di folder assets/.';
    showToast('File .vrm tidak ditemukan. Letakkan file .vrm dan restart server.');
    return;
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

  // 2. Muat Animasi VRMA
  document.getElementById('start-status').textContent = 'Memuat animasi...';
  await loadAnimations(appConfig.animations);

  // 3. Set Emosi Awal
  setEmotion('neutral');

  // 4. Bangun Panel Uji Debug
  buildDebugPanel({
    animationClips,
    appConfig,
    onPlayAnimation: (name) => playAnimation(name),
    onSetEmotion: (em) => setEmotion(em),
  });

  // 5. Polling Awal Statistik Sistem
  fetch('/api/stats')
    .then((r) => r.json())
    .then((stats) => updatePerfStats(stats))
    .catch(() => {});

  // 6. Hubungkan WebSocket
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
