/**
 * js/scene.js - Three.js Scene, Camera, Lighting & Controls
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export let scene = null;
export let camera = null;
export let renderer = null;
export let controls = null;

export function initScene() {
  const canvasWrap = document.getElementById('canvas-wrap');
  
  // WebGLRenderer: antialias aktif untuk menghaluskan helai rambut & mesh VRM anime (cegah crawling artifacts)
  renderer = new THREE.WebGLRenderer({
    antialias: true,
    powerPreference: 'high-performance',
  });
  // Batasi pixelRatio maksimal 1.5 untuk menghemat beban fragment shader & GPU fillrate
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  // Nonaktifkan shadow map karena model tidak memakai bayangan terproyeksi (hemat render pass & VRAM)
  renderer.shadowMap.enabled = false;
  // Catatan: Tidak menggunakan postprocessing (langsung render ke canvas framebuffer)

  canvasWrap.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d0f14);

  // Pencahayaan
  const dirLight = new THREE.DirectionalLight(0xffffff, Math.PI * 0.9);
  dirLight.position.set(1, 2, 2);
  scene.add(dirLight);
  scene.add(new THREE.AmbientLight(0x8890cc, 0.8));

  // Kamera (gaya streamer: pinggang ke atas)
  camera = new THREE.PerspectiveCamera(24, 1, 0.1, 50);
  camera.position.set(0, 1.35, 2.6);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 1.2, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 0.8;
  controls.maxDistance = 6;
  controls.maxPolarAngle = Math.PI * 0.72;
  controls.update();

  function onResize() {
    const w = canvasWrap.clientWidth, h = canvasWrap.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(onResize).observe(canvasWrap);
  onResize();

  return { scene, camera, renderer, controls };
}

export function frameCamera(vrm) {
  if (!vrm || !camera || !controls) return;
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const fov = THREE.MathUtils.degToRad(camera.fov);
  
  // Frame pinggang ke atas: target di ~60% tinggi model
  const targetY = box.min.y + size.y * 0.6;
  controls.target.set(0, targetY, 0);
  const dist = (size.y * 0.55) / Math.tan(fov / 2);
  camera.position.set(0, targetY + 0.05, dist);
  controls.update();
}
