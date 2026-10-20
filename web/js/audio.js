/**
 * js/audio.js - Web Audio API & Analyser untuk Lip-Sync
 */

const MOUTH_NOISE_GATE = 0.015;      // ambang bawah lip-sync
const MOUTH_GAIN = 2.2;              // penguatan amplitudo -> bobot mulut
const MOUTH_MAX = 0.7;               // batas atas bobot mulut
const MOUTH_RISE = 15.0;             // kecepatan naik mulut (per detik)
const MOUTH_FALL = 5.0;              // kecepatan turun mulut (per detik)

export let audioCtx = null;
let analyserNode = null;
let analyserBuffer = null;

let mouthWeight = 0;     // bobot 'aa' saat ini
let mouthTarget = 0;     // bobot target dari audio analyser
let manualMouth = 0;     // dari slider debug

/**
 * Inisialisasi AudioContext (setelah interaksi user, misal klik "Mulai").
 */
export function initAudioContext() {
  if (audioCtx) return audioCtx;
  audioCtx = new AudioContext();
  analyserNode = audioCtx.createAnalyser();
  analyserNode.fftSize = 256;
  analyserNode.smoothingTimeConstant = 0.5;
  analyserNode.connect(audioCtx.destination);
  analyserBuffer = new Float32Array(analyserNode.frequencyBinCount);
  return audioCtx;
}

/**
 * Putar audio MP3 (ArrayBuffer) dan kembalikan Promise yang resolve saat selesai.
 */
export function playAudioBuffer(arrayBuffer) {
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
 * Update amplitudo audio analyser -> mouthWeight (dipanggil di render loop).
 */
export function updateLipSync(dt) {
  if (!analyserNode) {
    mouthTarget = 0;
    return;
  }
  analyserNode.getFloatTimeDomainData(analyserBuffer);
  let rms = 0;
  for (let i = 0; i < analyserBuffer.length; i++) {
    rms += analyserBuffer[i] * analyserBuffer[i];
  }
  rms = Math.sqrt(rms / analyserBuffer.length);

  const raw = rms < MOUTH_NOISE_GATE ? 0 : Math.min(rms * MOUTH_GAIN, MOUTH_MAX);
  mouthTarget = raw;

  // Smoothing: naik cepat, turun lambat
  const speed = mouthWeight < mouthTarget ? MOUTH_RISE : MOUTH_FALL;
  mouthWeight += (mouthTarget - mouthWeight) * Math.min(1, speed * dt);
}

export function setManualMouth(val) {
  manualMouth = val;
}

export function getEffectiveMouth() {
  return Math.max(manualMouth, mouthWeight);
}
