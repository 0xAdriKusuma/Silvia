/**
 * js/expressions.js - Ekspresi Wajah, Emosi, Blink & Mulut
 */

import { getEffectiveMouth } from './audio.js';

const EXPR_LERP_SPEED = 8.0;         // kecepatan transisi ekspresi (per detik)
const BLINK_INTERVAL_MIN = 2.5;      // interval kedip min (detik)
const BLINK_INTERVAL_MAX = 5.5;      // interval kedip max (detik)
const BLINK_DURATION = 0.15;         // durasi kedip (detik)

export const availableExprs = new Set();
let targetExpression = {};
let currentExprWeights = {};
let emotionMapConfig = {};

// Blink state
let blinkTimer = 0;
let blinkDuration = 0;
let blinkActive = false;
let nextBlinkIn = randomBetween(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

export function setEmotionConfig(config) {
  emotionMapConfig = config || {};
}

/**
 * Deteksi ekspresi yang benar-benar ada di model VRM.
 */
export function discoverExpressions(vrm) {
  availableExprs.clear();
  const em = vrm?.expressionManager;
  if (!em) {
    console.warn('[Expr] Model tidak punya expressionManager.');
    return;
  }
  const names = em.expressions?.map((e) => e.expressionName) ?? [];
  names.forEach((n) => availableExprs.add(n));
  console.log('[Expr] Ekspresi tersedia:', [...availableExprs].join(', '));
}

/**
 * Set target ekspresi berdasarkan nama emosi.
 */
export function setEmotion(emotionName) {
  const exprMap = emotionMapConfig[emotionName] ?? {};
  targetExpression = {};
  for (const [expr, weight] of Object.entries(exprMap)) {
    if (availableExprs.has(expr)) {
      targetExpression[expr] = weight;
    }
  }
}

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

/**
 * Terapkan bobot ekspresi ke expressionManager (dipanggil di render loop).
 */
export function updateExpressions(vrm, dt) {
  const em = vrm?.expressionManager;
  if (!em) return;

  const combined = { ...targetExpression };

  // Kedipan otomatis
  if (availableExprs.has('blink')) {
    combined['blink'] = (combined['blink'] ?? 0) + blinkWeight();
    combined['blink'] = Math.min(combined['blink'], 1.0);
  }

  // Mulut lip-sync
  const mouthVal = getEffectiveMouth();
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
    try {
      em.setValue(expr, next);
    } catch (_) {}
  }
}
