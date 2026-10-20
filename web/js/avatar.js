/**
 * js/avatar.js - VRM Model Loader & Animation Manager (VRMA + Idle)
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import {
  VRMAnimationLoaderPlugin,
  VRMLookAtQuaternionProxy,
  createVRMAnimationClip,
} from '@pixiv/three-vrm-animation';
import { discoverExpressions } from './expressions.js';
import { frameCamera } from './scene.js';

const FADE_DURATION = 0.25;          // crossfade animasi (detik)
const IDLE_DURATION = 5.0;           // durasi satu siklus idle prosedural (detik)

export let vrm = null;
export let mixer = null;
export let idleAction = null;
export let currentAction = null;
export let animationClips = {};

const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));
loader.register((p) => new VRMAnimationLoaderPlugin(p));

/**
 * Muat model VRM dari URL.
 */
export async function loadVRM(url, scene, camera) {
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

  // Look-at: mata mengikuti kamera
  if (vrm.lookAt) {
    const proxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
    proxy.name = 'lookAtQuaternionProxy';
    vrm.scene.add(proxy);
    vrm.lookAt.target = camera;
  }

  scene.add(vrm.scene);

  mixer = new THREE.AnimationMixer(vrm.scene);
  mixer.addEventListener('finished', onAnimationFinished);

  discoverExpressions(vrm);

  // Buat idle prosedural awal
  idleAction = createProceduralIdleAction();
  if (idleAction) {
    idleAction.play();
    currentAction = idleAction;
  }

  frameCamera(vrm);
  console.log('[VRM] Model dimuat:', url);
  return vrm;
}

/**
 * Muat semua animasi VRMA dari mapping config.
 */
export async function loadAnimations(animationsMap) {
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

  // Jika Idle.vrma tersedia, gantikan sebagai idle action utama
  if (animationClips['idle']) {
    const vrmaIdleClip = animationClips['idle'];
    const newIdleAction = mixer.clipAction(vrmaIdleClip);
    newIdleAction.setLoop(THREE.LoopRepeat, Infinity);
    newIdleAction.clampWhenFinished = false;
    newIdleAction.enabled = true;

    const prev = currentAction;
    if (prev && prev !== newIdleAction) {
      prev.crossFadeTo(newIdleAction, FADE_DURATION, true);
    }
    newIdleAction.play();
    idleAction = newIdleAction;
    currentAction = newIdleAction;
    console.log('[Idle] Berhasil mengaktifkan animasi looping: Idle.vrma');
  }
}

/**
 * Mainkan animasi sekali putar dengan crossfade halus tanpa resiko T-pose.
 */
export function playAnimation(name) {
  if (!vrm || !mixer) return;
  const clip = animationClips[name];
  if (!clip) {
    console.warn(`[VRMA] Animasi '${name}' tidak ada di model ini, dilewati.`);
    return;
  }

  const prev = currentAction;
  const next = mixer.clipAction(clip);
  next.setLoop(THREE.LoopOnce, 1);
  next.clampWhenFinished = true;
  next.enabled = true;
  next.reset();

  // Pastikan idleAction tetap aktif sebagai base layer
  if (idleAction) {
    idleAction.enabled = true;
    idleAction.setEffectiveWeight(1.0);
    idleAction.play();
  }

  next.fadeIn(FADE_DURATION).play();
  if (prev && prev !== next && prev !== idleAction) {
    prev.fadeOut(FADE_DURATION);
  }

  currentAction = next;
}

/**
 * Kembali ke idle dengan transisi halus.
 */
export function returnToIdle() {
  if (!idleAction) return;
  const prev = currentAction;
  if (prev === idleAction) return;

  if (prev) {
    prev.fadeOut(FADE_DURATION);
  }

  idleAction.enabled = true;
  idleAction.setEffectiveWeight(1.0);
  idleAction.play();

  currentAction = idleAction;
}

function onAnimationFinished(e) {
  if (e.action === currentAction && e.action !== idleAction) {
    returnToIdle();
  }
}

/**
 * Buat AnimationClip idle prosedural jika tidak ada file Idle.vrma.
 */
function createProceduralIdleAction() {
  if (!vrm || !mixer) return null;
  const humanoid = vrm.humanoid;
  const T = IDLE_DURATION;

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
  const larmQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08, 0.05, -1.15));
  const rarmQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.08, -0.05, 1.15));
  const lforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -0.25));
  const rforeQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0,  0.25));
  const staticArr = (q) => [q.x, q.y, q.z, q.w, q.x, q.y, q.z, q.w];

  const larm = boneTrack('leftUpperArm', [0, T], staticArr(larmQ));
  const rarm = boneTrack('rightUpperArm', [0, T], staticArr(rarmQ));
  const lfore = boneTrack('leftLowerArm', [0, T], staticArr(lforeQ));
  const rfore = boneTrack('rightLowerArm', [0, T], staticArr(rforeQ));

  if (larm)  tracks.push(larm);
  if (rarm)  tracks.push(rarm);
  if (lfore) tracks.push(lfore);
  if (rfore) tracks.push(rfore);

  // Napas lembut (spine & head)
  const N_BREATH = 8;
  const breathTimes = [];
  const spineVals = [];
  const headVals = [];

  for (let i = 0; i <= N_BREATH; i++) {
    const t = (i / N_BREATH) * T;
    breathTimes.push(t);
    const phase = (i / N_BREATH) * Math.PI * 2;
    const sinP = Math.sin(phase);

    const sQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(sinP * 0.015, 0, 0));
    spineVals.push(sQ.x, sQ.y, sQ.z, sQ.w);

    const hQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(-sinP * 0.01 + Math.sin(phase * 0.5) * 0.012, Math.cos(phase * 0.5) * 0.018, 0));
    headVals.push(hQ.x, hQ.y, hQ.z, hQ.w);
  }

  const spineTrack = boneTrack('spine', breathTimes, spineVals);
  const headTrack  = boneTrack('head',  breathTimes, headVals);
  if (spineTrack) tracks.push(spineTrack);
  if (headTrack)  tracks.push(headTrack);

  if (!tracks.length) return null;

  const clip = new THREE.AnimationClip('idle', T, tracks);
  const action = mixer.clipAction(clip);
  action.setLoop(THREE.LoopRepeat, Infinity);
  action.clampWhenFinished = false;
  return action;
}

export function updateAvatar(dt) {
  if (mixer) mixer.update(dt);
  if (vrm) vrm.update(dt);
}
