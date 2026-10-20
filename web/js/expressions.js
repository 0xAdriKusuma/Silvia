/**
 * js/expressions.js - Ekspresi Wajah, Emosi, Blink & Mulut
 *
 * Semua ekspresi dikontrol KODE sepenuhnya.
 * VRMA tidak boleh menulis ekspresi (track ekspresi disaring di avatar.js).
 *
 * Prinsip:
 *  - MANAGED = daftar semua ekspresi emosi + preset standar yang ada di model.
 *  - Saat emosi berganti: semua target di-nol-kan, lalu isi dari pemetaan baru.
 *  - Per frame: lerp current → target untuk SEMUA nama di MANAGED,
 *    lalu setValue ke expressionManager untuk semua (termasuk yang bernilai 0).
 */

import { getEffectiveMouth } from './audio.js';

// ─── Parameter tuning (ubah di sini) ────────────────────────────────────────
const EXPR_RISE_SPEED = 10.0; // kecepatan naik ekspresi (per detik) ~0.1 dtk ke 1.0
const EXPR_FALL_SPEED = 14.0; // kecepatan turun ekspresi (per detik) ~0.07 dtk ke 0
const BLINK_INTERVAL_MIN = 2.5;  // interval kedip minimum (detik)
const BLINK_INTERVAL_MAX = 5.5;  // interval kedip maksimum (detik)
const BLINK_DURATION     = 0.15; // durasi satu kedipan (detik)
// ─────────────────────────────────────────────────────────────────────────────

// Preset ekspresi emosi standar VRM yang ingin kita kelola
const STANDARD_EMOTION_EXPRS = ['happy', 'angry', 'sad', 'relaxed', 'surprised'];

/** Set semua ekspresi yang benar-benar ada di model */
export const availableExprs = new Set();

/** Set ekspresi yang dikelola kode (MANAGED) */
const managedExprs = new Set();

/** Target bobot per ekspresi (0.0 – 1.0) */
let targetExpression = {};

/** Bobot saat ini per ekspresi (hasil lerp) */
let currentExprWeights = {};

/** Pemetaan emosi → ekspresi dari /api/config */
let emotionMapConfig = {};

// ─── Blink state ─────────────────────────────────────────────────────────────
let blinkTimer    = 0;
let blinkDuration = 0;
let blinkActive   = false;
let nextBlinkIn   = randomBetween(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

// ─── Setup ───────────────────────────────────────────────────────────────────

export function setEmotionConfig(config) {
  emotionMapConfig = config || {};
}

/**
 * Deteksi ekspresi yang benar-benar ada di model VRM dan bangun daftar MANAGED.
 * Dipanggil satu kali setelah model dimuat.
 */
export function discoverExpressions(vrm) {
  availableExprs.clear();
  managedExprs.clear();
  const em = vrm?.expressionManager;
  if (!em) {
    console.warn('[Expr] Model tidak punya expressionManager.');
    return;
  }

  // Daftar semua ekspresi di model
  const names = em.expressions?.map((e) => e.expressionName) ?? [];
  names.forEach((n) => availableExprs.add(n));
  console.log('[Expr] Ekspresi tersedia:', [...availableExprs].join(', '));

  // MANAGED = ekspresi dari pemetaan emosi + preset standar yang ADA di model
  // Kumpulkan dari emotionMapConfig
  for (const exprMap of Object.values(emotionMapConfig)) {
    for (const exprName of Object.keys(exprMap)) {
      if (availableExprs.has(exprName)) managedExprs.add(exprName);
    }
  }
  // Tambahkan preset standar yang ada di model
  for (const exprName of STANDARD_EMOTION_EXPRS) {
    if (availableExprs.has(exprName)) managedExprs.add(exprName);
  }

  // Inisialisasi bobot ke 0 untuk semua ekspresi yang dikelola
  for (const name of managedExprs) {
    targetExpression[name]  = 0;
    currentExprWeights[name] = 0;
  }

  console.log('[Expr] MANAGED:', [...managedExprs].join(', '));
}

// ─── Kontrol emosi ────────────────────────────────────────────────────────────

/**
 * Set emosi: nol-kan semua target, lalu isi dari pemetaan emosi baru.
 * Dipanggil saat baris baru dimulai (SEBELUM audio diputar).
 * @param {string} emotionName
 */
export function setEmotion(emotionName) {
  // Nol-kan semua target terlebih dahulu (mencegah ekspresi lama menempel)
  for (const name of managedExprs) {
    targetExpression[name] = 0;
  }

  // Isi dari pemetaan emosi baru (hanya ekspresi yang ada di model)
  const exprMap = emotionMapConfig[emotionName] ?? {};
  for (const [expr, weight] of Object.entries(exprMap)) {
    if (managedExprs.has(expr)) {
      targetExpression[expr] = weight;
    } else if (availableExprs.has(expr)) {
      // Ekspresi ada di model tapi belum di managedExprs → tambahkan
      managedExprs.add(expr);
      targetExpression[expr] = weight;
      currentExprWeights[expr] = currentExprWeights[expr] ?? 0;
    }
  }
}

// ─── Blink ────────────────────────────────────────────────────────────────────

function blinkWeight() {
  if (!blinkActive) return 0;
  const half = BLINK_DURATION / 2;
  const t = blinkDuration;
  return t < half ? t / half : 1 - (t - half) / half;
}

export function updateBlink(dt) {
  blinkTimer += dt;
  if (blinkActive) {
    blinkDuration += dt;
    if (blinkDuration >= BLINK_DURATION) {
      blinkActive   = false;
      blinkDuration = 0;
      nextBlinkIn   = randomBetween(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);
      blinkTimer    = 0;
    }
  } else {
    if (blinkTimer >= nextBlinkIn) {
      blinkActive   = true;
      blinkDuration = 0;
      blinkTimer    = 0;
    }
  }
}

// ─── Update per frame ─────────────────────────────────────────────────────────

/**
 * Terapkan bobot ekspresi ke expressionManager.
 * Dipanggil SETELAH mixer.update(dt) dan SEBELUM vrm.update(dt) di render loop.
 * @param {import('@pixiv/three-vrm').VRM} vrm
 * @param {number} dt
 */
export function updateExpressions(vrm, dt) {
  const em = vrm?.expressionManager;
  if (!em) return;

  // Blink otomatis (independen dari emosi)
  const bw = blinkWeight();
  if (availableExprs.has('blink')) {
    targetExpression['blink'] = bw;
    if (!managedExprs.has('blink')) {
      managedExprs.add('blink');
      currentExprWeights['blink'] = 0;
    }
  }

  // Lip-sync mulut (independen dari emosi)
  const mouthVal = getEffectiveMouth();
  if (availableExprs.has('aa')) {
    targetExpression['aa'] = mouthVal;
    if (!managedExprs.has('aa')) {
      managedExprs.add('aa');
      currentExprWeights['aa'] = 0;
    }
  }

  // Lerp semua ekspresi yang dikelola dan terapkan ke expressionManager
  for (const name of managedExprs) {
    const target  = targetExpression[name] ?? 0;
    const cur     = currentExprWeights[name] ?? 0;
    const diff    = target - cur;
    // Kecepatan naik dan turun berbeda agar ekspresi lama cepat memudar
    const speed   = diff > 0 ? EXPR_RISE_SPEED : EXPR_FALL_SPEED;
    const next    = cur + diff * Math.min(1, speed * dt);
    const clamped = Math.max(0, Math.min(1, next));
    currentExprWeights[name] = clamped;

    // Selalu set ke expressionManager – termasuk yang bernilai 0 (untuk reset)
    try {
      em.setValue(name, clamped);
    } catch (_) {}
  }
}

// ─── Getter untuk debug HUD ───────────────────────────────────────────────────

/**
 * Kembalikan snapshot bobot ekspresi saat ini untuk HUD debug.
 * @returns {Record<string, { current: number, target: number }>}
 */
export function getExpressionSnapshot() {
  const out = {};
  for (const name of managedExprs) {
    out[name] = {
      current: parseFloat((currentExprWeights[name] ?? 0).toFixed(3)),
      target:  parseFloat((targetExpression[name]   ?? 0).toFixed(3)),
    };
  }
  return out;
}
