/**
 * js/avatar.js - VRM Model Loader & Animation Manager
 *
 * Menggunakan AnimationBlender (animation.js) untuk sistem animasi
 * berbobot-ternormalisasi: idle selalu aktif, tidak ada T-pose flash,
 * transisi mulus tanpa stop()/reset()/stopAllAction().
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import {
  VRMAnimationLoaderPlugin,
  VRMLookAtQuaternionProxy,
  createVRMAnimationClip,
} from '@pixiv/three-vrm-animation';
import { AnimationBlender } from './animation.js';
import { discoverExpressions } from './expressions.js';
import { frameCamera } from './scene.js';

// Durasi idle prosedural jika Idle.vrma tidak tersedia
const PROCEDURAL_IDLE_DURATION = 5.0;

export let vrm = null;
export let mixer = null;
/** @type {AnimationBlender|null} */
export let blender = null;
export let animationClips = {}; // hanya animasi one-shot (bukan idle)

let idleClip = null;   // clip idle (VRMA atau prosedural)
let scene3   = null;   // referensi scene three.js

const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));
loader.register((p) => new VRMAnimationLoaderPlugin(p));

// ─── Loader ────────────────────────────────────────────────────────────────

/**
 * Muat model VRM dari URL.
 * Avatar disembunyikan (visible=false) hingga idle sudah aktif,
 * sehingga tidak pernah tampil T-pose di frame mana pun.
 */
export async function loadVRM(url, scene, camera) {
  scene3 = scene;
  const gltf = await loader.loadAsync(url);
  const nextVrm = gltf.userData.vrm;
  if (!nextVrm) throw new Error('Bukan file VRM yang valid: ' + url);

  VRMUtils.rotateVRM0(nextVrm); // rotasi VRM 0.x agar menghadap +Z

  // Hapus model lama jika ada
  if (vrm) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose?.(vrm.scene);
  }
  // Hentikan mixer lama (bukan stopAllAction – hanya hentikan animasi)
  if (mixer) {
    mixer.stopAllAction(); // aman karena model lama sudah dihapus
    blender = null;
  }

  vrm = nextVrm;
  vrm.scene.traverse((o) => { o.frustumCulled = false; });

  // Look-at: mata mengikuti kamera
  if (vrm.lookAt) {
    const proxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
    proxy.name = 'lookAtQuaternionProxy';
    vrm.scene.add(proxy);
    vrm.lookAt.target = camera;
  }

  // Sembunyikan sementara agar tidak tampil T-pose
  vrm.scene.visible = false;
  scene.add(vrm.scene);

  mixer = new THREE.AnimationMixer(vrm.scene);
  // Catatan: TIDAK daftarkan listener 'finished' – blender menangani lifecycle sendiri.

  discoverExpressions(vrm);

  // Idle prosedural langsung aktif sebagai fallback (akan diganti jika Idle.vrma berhasil)
  idleClip = createProceduralIdleClip();
  blender = new AnimationBlender(mixer);
  if (idleClip) blender.addIdle(idleClip);

  // Panggil mixer.update(0) sekali agar idle langsung diterapkan ke tulang
  blender.update(0);
  mixer.update(0);

  // Baru tampilkan avatar – tidak ada T-pose di frame pertama
  vrm.scene.visible = true;

  frameCamera(vrm);
  console.log('[VRM] Model dimuat:', url);
  return vrm;
}

/**
 * Muat semua animasi VRMA dari mapping config.
 * idle_url ditangani terpisah; animasi lain masuk sebagai one-shot.
 *
 * @param {Record<string, string>} animationsMap - { namaAnimasi: url }
 * @param {string|null} idleUrl - URL untuk Idle.vrma (dari /api/config idle_url)
 */
export async function loadAnimations(animationsMap, idleUrl) {
  animationClips = {};
  const allClips = {}; // nama → clip (sementara, untuk normalisasi track)

  // ── Muat Idle.vrma jika tersedia ────────────────────────────────────────
  let vrmaIdleClip = null;
  if (idleUrl) {
    try {
      const gltf = await loader.loadAsync(idleUrl);
      const va = gltf.userData.vrmAnimations?.[0];
      if (!va) throw new Error('Tidak ada VRMAnimation di Idle.vrma');
      if (!vrm) throw new Error('VRM belum dimuat');
      const clip = createVRMAnimationClip(va, vrm);
      clip.name = '__idle__';
      vrmaIdleClip = clip;
      console.log('[Idle] Berhasil memuat Idle.vrma');
    } catch (e) {
      console.warn('[Idle] Gagal memuat Idle.vrma, pakai idle prosedural:', e.message);
    }
  } else {
    console.warn('[Idle] idle_url tidak tersedia di config – memakai idle prosedural.');
  }

  // ── Muat animasi one-shot ────────────────────────────────────────────────
  for (const [name, url] of Object.entries(animationsMap)) {
    try {
      const gltf = await loader.loadAsync(url);
      const va = gltf.userData.vrmAnimations?.[0];
      if (!va) throw new Error('Tidak ada VRMAnimation di file');
      if (!vrm) throw new Error('VRM belum dimuat');
      const clip = createVRMAnimationClip(va, vrm);
      clip.name = name;
      allClips[name] = clip;
      console.log(`[VRMA] Dimuat: ${name}`);
    } catch (e) {
      console.warn(`[VRMA] Gagal memuat animasi '${name}':`, e.message);
    }
  }

  // ── Saring track ekspresi dari semua clip ────────────────────────────────
  // Ekspresi dikontrol sepenuhnya oleh expressions.js, bukan VRMA.
  const allClipList = vrmaIdleClip ? [vrmaIdleClip, ...Object.values(allClips)] : Object.values(allClips);

  // Log nama track pertama untuk debugging (hanya sekali)
  if (allClipList.length > 0) {
    const sampleTrackNames = allClipList[0].tracks.slice(0, 10).map((t) => t.name);
    console.log('[Avatar] Contoh nama track (clip pertama):', sampleTrackNames);
  }

  for (const clip of allClipList) {
    const before = clip.tracks.length;
    clip.tracks = clip.tracks.filter((t) => !isExpressionTrack(t.name, vrm));
    const after = clip.tracks.length;
    if (before !== after) {
      console.log(`[Avatar] Clip '${clip.name}': disaring ${before - after} track ekspresi`);
    }
  }

  // ── Normalisasi himpunan track tulang antar semua clip ───────────────────
  // Agar jumlah bobot per tulang selalu = 1 (mencegah T-pose per-tulang).
  if (vrmaIdleClip && allClipList.length > 1) {
    normalizeTrackSets([vrmaIdleClip, ...Object.values(allClips)], vrmaIdleClip);
  }

  // ── Bangun blender baru dengan idle yang benar ───────────────────────────
  const finalIdleClip = vrmaIdleClip ?? idleClip;
  if (!finalIdleClip) {
    console.warn('[Avatar] Tidak ada clip idle sama sekali!');
    return;
  }

  // Buat ulang blender dan mixer agar bersih
  mixer.stopAllAction();
  blender = new AnimationBlender(mixer);
  blender.addIdle(finalIdleClip);
  idleClip = finalIdleClip;

  // Tambahkan semua one-shot
  for (const [name, clip] of Object.entries(allClips)) {
    blender.addOneShot(name, clip);
    animationClips[name] = clip;
  }

  // Update awal agar idle langsung aktif sebelum frame pertama
  blender.update(0);
  mixer.update(0);

  console.log('[Avatar] Blender siap dengan', Object.keys(animationClips).length, 'animasi one-shot');
}

// ─── Kontrol animasi ────────────────────────────────────────────────────────

/**
 * Picu animasi sekali-putar dengan nama.
 * Jika animasi tidak ditemukan, tampilkan peringatan dan abaikan.
 * @param {string} name
 */
export function playAnimation(name) {
  if (!blender) {
    console.warn('[Avatar] Blender belum siap, animasi diabaikan:', name);
    return;
  }
  blender.trigger(name);
}

/**
 * Kembalikan ke idle secara eksplisit (mis. dipanggil dari WebSocket turn_end).
 * Karena blender otomatis kembali ke idle setelah animasi selesai,
 * fungsi ini hanya diperlukan jika ada kebutuhan khusus.
 */
export function returnToIdle() {
  if (!blender) return;
  blender.returnToIdle();
}

// ─── Update loop ─────────────────────────────────────────────────────────────

/**
 * Tahap 1: Jalankan update animasi (Blender & Mixer) sebelum ekspresi diatur.
 * @param {number} dt
 */
export function updateAvatarAnimation(dt) {
  const clampedDt = Math.min(dt, 0.1);
  if (blender) blender.update(clampedDt);
  if (mixer)   mixer.update(clampedDt);
}

/**
 * Tahap 2: Jalankan update VRM (evaluasi lookAt, humanoid, expressionManager, springBone).
 * Dipanggil SETELAH updateExpressions() agar perubahan ekspresi langsung diterapkan di frame yang sama tanpa delay 1 frame.
 * @param {number} dt
 */
export function updateAvatarVRM(dt) {
  const clampedDt = Math.min(dt, 0.1);
  if (vrm) vrm.update(clampedDt);
}

/**
 * Kompatibilitas mundur: jalankan seluruh siklus update sekaligus.
 * @param {number} dt
 */
export function updateAvatar(dt) {
  updateAvatarAnimation(dt);
  updateAvatarVRM(dt);
}

// ─── Kelengkapan track (normalisasi himpunan tulang) ──────────────────────────

/**
 * Normalisasi himpunan track tulang di semua clip agar setiap clip
 * menyentuh tulang yang sama. Clip yang tidak punya track untuk tulang X
 * mendapat track konstan (identitas atau nilai dari clip referensi).
 *
 * @param {THREE.AnimationClip[]} clips - semua clip yang akan dinormalisasi
 * @param {THREE.AnimationClip} referenceClip - clip yang jadi referensi nilai default (idle)
 */
function normalizeTrackSets(clips, referenceClip) {
  if (!clips.length) return;

  // Kumpulkan semua nama track unik dari gabungan seluruh clip
  const allTrackNames = new Set();
  for (const clip of clips) {
    for (const track of clip.tracks) {
      allTrackNames.add(track.name);
    }
  }

  // Bangun peta nama track → track dari referensi (idle)
  const referenceTrackMap = new Map();
  for (const track of referenceClip.tracks) {
    referenceTrackMap.set(track.name, track);
  }

  // Untuk setiap clip, tambahkan track konstan untuk tulang yang hilang
  for (const clip of clips) {
    const existingTrackNames = new Set(clip.tracks.map((t) => t.name));

    for (const trackName of allTrackNames) {
      if (existingTrackNames.has(trackName)) continue;

      // Cari nilai dari clip referensi atau clip lain yang punya track ini
      let sourceTrack = referenceTrackMap.get(trackName);
      if (!sourceTrack) {
        for (const otherClip of clips) {
          sourceTrack = otherClip.tracks.find((t) => t.name === trackName);
          if (sourceTrack) break;
        }
      }

      // Buat track konstan (2 keyframe: t=0 dan t=duration)
      let constantTrack;
      if (sourceTrack instanceof THREE.QuaternionKeyframeTrack) {
        // Ambil nilai frame pertama sebagai nilai konstan
        const firstVal = sourceTrack.values.slice(0, 4); // [x,y,z,w]
        constantTrack = new THREE.QuaternionKeyframeTrack(
          trackName,
          [0, clip.duration],
          [...firstVal, ...firstVal],
          THREE.InterpolateLinear,
        );
      } else if (sourceTrack instanceof THREE.VectorKeyframeTrack) {
        const firstVal = sourceTrack.values.slice(0, 3);
        constantTrack = new THREE.VectorKeyframeTrack(
          trackName,
          [0, clip.duration],
          [...firstVal, ...firstVal],
          THREE.InterpolateLinear,
        );
      } else if (sourceTrack) {
        // Generic: salin nilai pertama
        const valSize = sourceTrack.values.length / sourceTrack.times.length;
        const firstVal = sourceTrack.values.slice(0, valSize);
        // Gunakan tipe track yang sama
        constantTrack = new sourceTrack.constructor(
          trackName,
          [0, clip.duration],
          [...firstVal, ...firstVal],
          THREE.InterpolateLinear,
        );
      } else {
        // Tidak ada referensi → quaternion identitas
        if (trackName.endsWith('.quaternion')) {
          constantTrack = new THREE.QuaternionKeyframeTrack(
            trackName,
            [0, clip.duration],
            [0, 0, 0, 1, 0, 0, 0, 1],
            THREE.InterpolateLinear,
          );
        } else if (trackName.endsWith('.position')) {
          constantTrack = new THREE.VectorKeyframeTrack(
            trackName,
            [0, clip.duration],
            [0, 0, 0, 0, 0, 0],
            THREE.InterpolateLinear,
          );
        }
        // Lewati track tipe tidak dikenal
      }

      if (constantTrack) {
        clip.tracks.push(constantTrack);
      }
    }
  }

  console.log(
    `[Avatar] Normalisasi track: ${allTrackNames.size} track unik di ${clips.length} clip.`,
  );
}

// ─── Filter track ekspresi ───────────────────────────────────────────────────

/**
 * Cek apakah nama track merupakan track ekspresi VRM.
 * three-vrm-animation menghasilkan track dengan format nama seperti:
 *  - "VRMExpression.happy.weight"
 *  - Atau path node internal yang mengandung nama ekspresi
 * Karena format exakt bergantung versi library, gunakan substring matching.
 *
 * @param {string} trackName
 * @param {import('@pixiv/three-vrm').VRM} vrm
 * @returns {boolean}
 */
function isExpressionTrack(trackName, vrm) {
  const em = vrm?.expressionManager;
  if (!em) return false;

  const lower = trackName.toLowerCase();

  // Format umum dari three-vrm-animation:
  // "VRMExpression" atau "expressionManager" dalam nama track
  if (lower.includes('vrmexpression') || lower.includes('expressionmanager')) {
    return true;
  }

  // Cek apakah nama track mengandung nama ekspresi yang dikenal
  const exprNames = em.expressions?.map((e) => e.expressionName.toLowerCase()) ?? [];
  for (const exprName of exprNames) {
    // Track harus mengandung nama ekspresi sebagai kata utuh (bukan substring kebetulan)
    // Format: ".{exprName}." atau "/{exprName}/" atau mengandung nama ekspresi
    if (lower.includes(exprName)) {
      // Tambahan validasi: track body biasanya mengandung .quaternion atau .position
      // track ekspresi tidak mengandung ini
      const isBodyTrack = lower.endsWith('.quaternion') || lower.endsWith('.position') ||
                          lower.endsWith('.scale');
      if (!isBodyTrack) return true;
    }
  }

  return false;
}

// ─── Idle prosedural ──────────────────────────────────────────────────────────

/**
 * Buat AnimationClip idle prosedural (cadangan jika Idle.vrma tidak ada).
 * @returns {THREE.AnimationClip|null}
 */
function createProceduralIdleClip() {
  if (!vrm || !mixer) return null;
  const humanoid = vrm.humanoid;
  const T = PROCEDURAL_IDLE_DURATION;

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
  const larmQ  = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08,  0.05, -1.15));
  const rarmQ  = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08, -0.05,  1.15));
  const lforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -0.25));
  const rforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0,  0.25));
  const staticArr = (q) => [q.x, q.y, q.z, q.w, q.x, q.y, q.z, q.w];

  const larm  = boneTrack('leftUpperArm',  [0, T], staticArr(larmQ));
  const rarm  = boneTrack('rightUpperArm', [0, T], staticArr(rarmQ));
  const lfore = boneTrack('leftLowerArm',  [0, T], staticArr(lforeQ));
  const rfore = boneTrack('rightLowerArm', [0, T], staticArr(rforeQ));

  if (larm)  tracks.push(larm);
  if (rarm)  tracks.push(rarm);
  if (lfore) tracks.push(lfore);
  if (rfore) tracks.push(rfore);

  // Animasi napas lembut (spine & head)
  const N_BREATH = 8;
  const breathTimes = [];
  const spineVals = [];
  const headVals  = [];

  for (let i = 0; i <= N_BREATH; i++) {
    const t = (i / N_BREATH) * T;
    breathTimes.push(t);
    const phase = (i / N_BREATH) * Math.PI * 2;
    const sinP = Math.sin(phase);

    const sQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(sinP * 0.015, 0, 0));
    spineVals.push(sQ.x, sQ.y, sQ.z, sQ.w);

    const hQ = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(
        -sinP * 0.01 + Math.sin(phase * 0.5) * 0.012,
        Math.cos(phase * 0.5) * 0.018,
        0,
      ),
    );
    headVals.push(hQ.x, hQ.y, hQ.z, hQ.w);
  }

  const spineTrack = boneTrack('spine', breathTimes, spineVals);
  const headTrack  = boneTrack('head',  breathTimes, headVals);
  if (spineTrack) tracks.push(spineTrack);
  if (headTrack)  tracks.push(headTrack);

  if (!tracks.length) return null;

  return new THREE.AnimationClip('__procedural_idle__', T, tracks);
}
