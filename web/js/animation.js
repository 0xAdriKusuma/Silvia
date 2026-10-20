/**
 * js/animation.js - AnimationBlender berbobot-ternormalisasi
 *
 * Prinsip utama:
 *  - Semua action di-play() SEKALI dan enabled=true selamanya.
 *  - Pengendalian HANYA via setEffectiveWeight(w).
 *  - Jumlah bobot semua action = 1 di setiap frame (normalisasi).
 *  - Idle = LoopRepeat, berjalan terus sebagai lapisan dasar.
 *  - Animasi sekali-putar = LoopOnce + clampWhenFinished=true.
 *  - Tidak ada stop(), reset() saat berjalan, stopAllAction(), atau setTimeout.
 */

import * as THREE from 'three';

// ─── Parameter tuning (ubah di sini) ───────────────────────────────────────
const FADE_IN   = 0.3;   // detik naik ke target bobot 1
const FADE_OUT  = 0.5;   // detik turun ke bobot 0
const BLEND_OUT = 0.5;   // detik sebelum akhir animasi mulai blend-out (maks 40% durasi)
const WEIGHT_EPSILON = 0.001; // bobot di bawah ini dianggap nol
// ────────────────────────────────────────────────────────────────────────────

/**
 * AnimationBlender - mengelola bobot semua AnimationAction secara terpusat.
 *
 * Cara pakai:
 *   const blender = new AnimationBlender(mixer);
 *   blender.addIdle(idleClip);
 *   blender.addOneShot('greetings', clip);
 *   // per frame:
 *   blender.update(dt);
 *   mixer.update(dt);
 */
export class AnimationBlender {
  constructor(mixer) {
    this._mixer = mixer;

    /** @type {{ name: string, action: THREE.AnimationAction, isIdle: boolean,
     *            weight: number, targetWeight: number, duration: number }[]} */
    this._entries = [];

    /** Nama animasi sekali-putar yang sedang aktif (null = hanya idle) */
    this._activeOneShotName = null;

    /** Pengali kecepatan waktu (1.0 = normal, 0.1 = slow-mo debug) */
    this.timeScale = 1.0;
  }

  // ─── Setup ───────────────────────────────────────────────────────────────

  /**
   * Tambahkan clip idle (LoopRepeat). Harus dipanggil sebelum addOneShot.
   * @param {THREE.AnimationClip} clip
   */
  addIdle(clip) {
    const action = this._mixer.clipAction(clip);
    action.setLoop(THREE.LoopRepeat, Infinity);
    action.clampWhenFinished = false;
    action.enabled = true;
    // Idle mulai dengan bobot 1 (akan dinormalisasi)
    action.setEffectiveWeight(1);
    action.play();

    this._entries.push({
      name: '__idle__',
      action,
      isIdle: true,
      weight: 1,
      targetWeight: 1,
      duration: clip.duration,
    });
    return this;
  }

  /**
   * Tambahkan clip animasi sekali-putar.
   * @param {string} name
   * @param {THREE.AnimationClip} clip
   */
  addOneShot(name, clip) {
    const action = this._mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.enabled = true;
    // Mulai berhenti di frame 0, bobot 0, paused
    action.time = 0;
    action.paused = true;
    action.setEffectiveWeight(0);
    action.play(); // play() dipanggil sekali agar mixer mengenali action

    this._entries.push({
      name,
      action,
      isIdle: false,
      weight: 0,
      targetWeight: 0,
      duration: clip.duration,
    });
    return this;
  }

  // ─── Trigger ─────────────────────────────────────────────────────────────

  /**
   * Picu animasi sekali-putar. Jika animasi yang sama masih aktif (bobot>0.5),
   * abaikan. Jika animasi lain sedang aktif, lakukan crossfade.
   * @param {string} name
   */
  trigger(name) {
    const entry = this._entries.find((e) => e.name === name);
    if (!entry) {
      console.warn(`[AnimationBlender] Animasi '${name}' tidak ditemukan.`);
      return;
    }

    // Abaikan jika animasi yang sama masih aktif
    if (this._activeOneShotName === name && entry.weight > 0.5) {
      console.log(`[AnimationBlender] Animasi '${name}' masih aktif, diabaikan.`);
      return;
    }

    // Reset action ke frame 0 dan pastikan tidak paused
    entry.action.time = 0;
    entry.action.paused = false;

    // Semua one-shot lain → target ke 0
    for (const e of this._entries) {
      if (!e.isIdle && e.name !== name) {
        e.targetWeight = 0;
      }
    }

    // Idle → target ke 0 (sementara animasi aktif)
    const idleEntry = this._entries.find((e) => e.isIdle);
    if (idleEntry) idleEntry.targetWeight = 0;

    // Animasi yang dipicu → target ke 1
    entry.targetWeight = 1;
    this._activeOneShotName = name;
  }

  // ─── Update per frame ────────────────────────────────────────────────────

  /**
   * Perbarui bobot semua action. Dipanggil SEBELUM mixer.update(dt).
   * @param {number} dt delta-time (sudah dibatasi maks 0.1 detik)
   */
  update(dt) {
    const scaledDt = dt * this.timeScale;

    const idleEntry   = this._entries.find((e) => e.isIdle);
    const activeEntry = this._activeOneShotName
      ? this._entries.find((e) => e.name === this._activeOneShotName)
      : null;

    // ── Cek apakah animasi aktif perlu mulai blend-out ──────────────────
    if (activeEntry) {
      const blendOutStart = Math.max(
        activeEntry.duration - Math.min(BLEND_OUT, activeEntry.duration * 0.4),
        0,
      );
      const t = activeEntry.action.time;

      if (t >= blendOutStart && activeEntry.targetWeight > 0) {
        // Mulai blend-out → idle naik kembali
        activeEntry.targetWeight = 0;
        if (idleEntry) idleEntry.targetWeight = 1;
      }

      // Jika bobot animasi sudah memudar mendekati 0 dan targetnya 0 -> tandai selesai
      if (activeEntry.weight < WEIGHT_EPSILON && activeEntry.targetWeight === 0) {
        this._finishOneShot(activeEntry);
      }
    } else {
      // Tidak ada animasi aktif -> idle harus target 1
      if (idleEntry) idleEntry.targetWeight = 1;
    }

    // ── Ramp bobot menuju target ─────────────────────────────────────────
    for (const e of this._entries) {
      const diff = e.targetWeight - e.weight;
      if (Math.abs(diff) < 0.0001) {
        e.weight = e.targetWeight;
        continue;
      }
      // Gunakan fade rate berbeda untuk naik dan turun
      const rate = diff > 0 ? (1 / FADE_IN) : (1 / FADE_OUT);
      const step = diff * Math.min(1, rate * scaledDt);
      e.weight = Math.max(0, Math.min(1, e.weight + step));
    }

    // ── Normalisasi: jumlah bobot = 1 ───────────────────────────────────
    let total = 0;
    for (const e of this._entries) total += e.weight;

    if (total < WEIGHT_EPSILON) {
      // Paksa idle jika semua bobot nol (seharusnya tidak terjadi)
      if (idleEntry) {
        idleEntry.weight = 1;
        idleEntry.targetWeight = 1;
        console.warn('[AnimationBlender] Semua bobot nol – paksa idle=1');
      }
      total = 1;
    }

    // Terapkan bobot yang sudah dinormalisasi ke three.js action
    for (const e of this._entries) {
      const normalizedWeight = e.weight / total;
      e.action.setEffectiveWeight(normalizedWeight);

      // Pastikan action one-shot berbobot tidak paused
      if (!e.isIdle && normalizedWeight > WEIGHT_EPSILON && e.action.paused) {
        e.action.paused = false;
      }
    }

    // Bersihkan semua one-shot yang sudah sepenuhnya memudar ke 0
    for (const e of this._entries) {
      if (!e.isIdle && e.weight < WEIGHT_EPSILON && e.targetWeight === 0) {
        if (!e.action.paused) {
          e.action.paused = true;
          e.action.time = 0;
        }
        if (this._activeOneShotName === e.name) {
          this._activeOneShotName = null;
        }
      }
    }

    // ── Debug: peringatkan jika jumlah raw menyimpang >0.01 ─────────────
    // (periksa effective weight yang sudah diterapkan)
    let effectiveTotal = 0;
    for (const e of this._entries) effectiveTotal += e.action.getEffectiveWeight();
    if (Math.abs(effectiveTotal - 1) > 0.01 && effectiveTotal > 0) {
      console.warn(
        `[AnimationBlender] Jumlah effectiveWeight: ${effectiveTotal.toFixed(4)} (seharusnya 1)`,
      );
    }
  }

  /**
   * Mulai transisi mulus kembali ke idle untuk semua animasi.
   */
  returnToIdle() {
    const idleEntry = this._entries.find((e) => e.isIdle);
    if (idleEntry) idleEntry.targetWeight = 1;
    for (const e of this._entries) {
      if (!e.isIdle) {
        e.targetWeight = 0;
      }
    }
  }

  /** Selesaikan animasi sekali-putar: paused, time=0, bersihkan state */
  _finishOneShot(entry) {
    entry.action.paused = true;
    entry.action.time = 0;
    entry.weight = 0;
    entry.targetWeight = 0;
    if (this._activeOneShotName === entry.name) {
      this._activeOneShotName = null;
    }
  }

  // ─── Getter untuk debug HUD ──────────────────────────────────────────────

  /** Kembalikan snapshot bobot saat ini untuk HUD debug */
  getWeights() {
    const out = {};
    for (const e of this._entries) {
      out[e.name] = {
        raw: parseFloat(e.weight.toFixed(4)),
        effective: parseFloat(e.action.getEffectiveWeight().toFixed(4)),
      };
    }
    return out;
  }

  /** Total effective weight semua action (harus mendekati 1) */
  getTotalWeight() {
    let t = 0;
    for (const e of this._entries) t += e.action.getEffectiveWeight();
    return t;
  }

  /** Nama animasi aktif saat ini */
  getActiveName() {
    return this._activeOneShotName ?? '__idle__';
  }

  /** Apakah sedang ada animasi one-shot aktif */
  isPlayingOneShot() {
    return this._activeOneShotName !== null;
  }
}
