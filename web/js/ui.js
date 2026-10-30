/**
 * js/ui.js - Antarmuka Pengguna, Subtitle, Status, Debug Panel & Monitor Performa
 */

const statusPill    = document.getElementById('status-pill');
const statusText    = document.getElementById('status-text');
const subtitleJp    = document.getElementById('subtitle-jp');
const subtitleId    = document.getElementById('subtitle-id');
const userTextEl    = document.getElementById('user-text');
const toast         = document.getElementById('toast');

const perfWidget    = document.getElementById('perf-monitor');
const btnTogglePerf = document.getElementById('btn-toggle-perf');
const perfToggleIcon = document.getElementById('perf-toggle-icon');
const perfCpuVal    = document.getElementById('perf-cpu-val');
const perfCpuBar    = document.getElementById('perf-cpu-bar');
const perfRamVal    = document.getElementById('perf-ram-val');
const perfRamBar    = document.getElementById('perf-ram-bar');
const perfGpuRow    = document.getElementById('perf-gpu-row');
const perfGpuName   = document.getElementById('perf-gpu-name');
const perfGpuVal    = document.getElementById('perf-gpu-val');
const perfGpuBar    = document.getElementById('perf-gpu-bar');
const perfVramRow   = document.getElementById('perf-vram-row');
const perfVramVal   = document.getElementById('perf-vram-val');
const perfVramBar   = document.getElementById('perf-vram-bar');
const perfFpsVal    = document.getElementById('perf-fps-val');
const perfTempBadge = document.getElementById('perf-temp-badge');
const perfTempVal   = document.getElementById('perf-temp-val');

const STATUS_LABELS = {
  idle:         'Mikrofon mati',
  listening:    'Mendengarkan...',
  transcribing: 'Memproses...',
  thinking:     'Berpikir...',
  speaking:     'Berbicara...',
  disconnected: 'Terputus – menyambung kembali...',
};

export function setStatusUI(state) {
  if (!statusPill || !statusText) return;
  statusPill.dataset.state = state;
  statusText.textContent = STATUS_LABELS[state] ?? state;
}

export function setSubtitle(jp, id) {
  if (subtitleJp) subtitleJp.textContent = jp ?? '';
  if (subtitleId) subtitleId.textContent = id ?? '';
}

let userTextTimer = null;
export function showUserText(text) {
  if (!userTextEl) return;
  userTextEl.textContent = '🎤 ' + text;
  userTextEl.classList.add('visible');
  clearTimeout(userTextTimer);
  userTextTimer = setTimeout(() => userTextEl.classList.remove('visible'), 8000);
}

let toastTimer = null;
export function showToast(msg) {
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 5000);
}

/** Tampilkan petunjuk kecil di bawah tombol mic (dikosongkan otomatis setelah delay). */
let micHintTimer = null;
export function showMicHint(msg, { warn = false, duration = 3500 } = {}) {
  const el = document.getElementById('mic-hint');
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle('hint-warn', warn);
  clearTimeout(micHintTimer);
  if (duration > 0) {
    micHintTimer = setTimeout(() => {
      el.textContent = '';
      el.classList.remove('hint-warn');
    }, duration);
  }
}

export function updateFps(fps) {
  if (perfFpsVal) perfFpsVal.textContent = fps;
}

function setBarColor(barElem, percent) {
  if (!barElem) return;
  barElem.classList.remove('warn', 'danger');
  if (percent >= 90)      barElem.classList.add('danger');
  else if (percent >= 75) barElem.classList.add('warn');
}

export function updatePerfStats(stats) {
  if (!stats) return;

  if (stats.cpu) {
    const cpuPct = Math.round(stats.cpu.percent || 0);
    perfCpuVal.textContent = `${cpuPct}%`;
    perfCpuBar.style.width = `${Math.min(100, cpuPct)}%`;
    setBarColor(perfCpuBar, cpuPct);
  }

  if (stats.ram) {
    const ramPct = Math.round(stats.ram.percent || 0);
    perfRamVal.textContent = `${stats.ram.used_gb} / ${stats.ram.total_gb} GB (${ramPct}%)`;
    perfRamBar.style.width = `${Math.min(100, ramPct)}%`;
    setBarColor(perfRamBar, ramPct);
  }

  if (stats.gpu) {
    perfGpuRow.style.display  = '';
    perfVramRow.style.display = '';

    if (stats.gpu.name) {
      const shortName = stats.gpu.name.replace(/NVIDIA\s+/i, '').replace(/Laptop GPU/i, 'Mobile');
      perfGpuName.textContent = shortName;
      perfGpuName.title       = stats.gpu.name;
    }

    const gpuPct = Math.round(stats.gpu.load || 0);
    perfGpuVal.textContent = `${gpuPct}%`;
    perfGpuBar.style.width = `${Math.min(100, gpuPct)}%`;
    setBarColor(perfGpuBar, gpuPct);

    const vramUsed  = Math.round(stats.gpu.vram_used_mb  || 0);
    const vramTotal = Math.round(stats.gpu.vram_total_mb  || 0);
    const vramPct   = Math.round(stats.gpu.vram_percent   || 0);
    perfVramVal.textContent = `${vramUsed} / ${vramTotal} MB (${vramPct}%)`;
    perfVramBar.style.width = `${Math.min(100, vramPct)}%`;
    setBarColor(perfVramBar, vramPct);

    if (stats.gpu.temp !== undefined && stats.gpu.temp !== null) {
      perfTempBadge.style.display = '';
      perfTempVal.textContent = `${Math.round(stats.gpu.temp)}°C`;
    }
  } else {
    perfGpuRow.style.display  = 'none';
    perfVramRow.style.display = 'none';
    perfTempBadge.style.display = 'none';
  }
}

export function initUIListeners({ onSendText, onMouthSlider }) {
  // Toggle panel performa
  if (btnTogglePerf) {
    btnTogglePerf.onclick = () => {
      const isCollapsed = perfWidget.classList.toggle('collapsed');
      perfToggleIcon.textContent = isCollapsed ? '+' : '−';
    };
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'm' || e.key === 'M') {
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      const isCollapsed = perfWidget.classList.toggle('collapsed');
      perfToggleIcon.textContent = isCollapsed ? '+' : '−';
    }
  });

  // Toggle debug panel (tombol D)
  const debugPanel = document.getElementById('debug-panel');
  document.getElementById('btn-debug-toggle').onclick = () => {
    debugPanel.classList.toggle('hidden');
  };
  window.addEventListener('keydown', (e) => {
    if (e.key === 'd' || e.key === 'D') {
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      debugPanel.classList.toggle('hidden');
    }
  });

  // Toggle subtitle bahasa indonesia
  const btnToggleId = document.getElementById('btn-toggle-id');
  btnToggleId.onclick = () => {
    const hidden = subtitleId.classList.toggle('hidden');
    btnToggleId.textContent = hidden ? 'Tampilkan terjemahan' : 'Sembunyikan terjemahan';
  };

  // Slider mulut
  const mouthSlider = document.getElementById('mouth-slider');
  const mouthVal    = document.getElementById('mouth-val');
  mouthSlider.oninput = (e) => {
    const val = Number(e.target.value) / 100;
    mouthVal.textContent = `${e.target.value}%`;
    if (onMouthSlider) onMouthSlider(val);
  };

  // Input teks
  const textInput = document.getElementById('text-input');
  const btnSend   = document.getElementById('btn-send');
  function handleSend() {
    const text = textInput.value.trim();
    if (!text) return;
    if (onSendText) onSendText(text);
    showUserText(text);
    textInput.value = '';
  }
  btnSend.onclick = handleSend;
  textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
}

// ─── Debug Panel ──────────────────────────────────────────────────────────────

/** Interval ID untuk update HUD debug */
let debugHudInterval = null;

/**
 * Bangun panel debug dengan tombol animasi, emosi, uji beruntun, slow-mo, dan HUD bobot.
 */
export function buildDebugPanel({
  animationClips,
  appConfig,
  onPlayAnimation,
  onSetEmotion,
  getBlenderState,
  getExprSnapshot,
  getRenderStats,
  onSetRenderFps,
}) {
  // ── Tombol preset target FPS ──────────────────────────────────────────────
  const fpsBtns = document.querySelectorAll('#dbg-fps-buttons .dbg-fps-btn');
  if (fpsBtns.length) {
    fpsBtns.forEach((btn) => {
      btn.onclick = () => {
        const val = Number(btn.dataset.fps);
        const fpsTarget = val > 0 ? val : null;
        if (onSetRenderFps) onSetRenderFps(fpsTarget);
        fpsBtns.forEach((b) => b.classList.remove('dbg-btn-active'));
        btn.classList.add('dbg-btn-active');
      };
      if (btn.dataset.fps === '30') {
        btn.classList.add('dbg-btn-active');
      }
    });
  }

  // ── Tombol animasi ─────────────────────────────────────────────────────────
  const animBtns = document.getElementById('anim-btns');
  animBtns.innerHTML = '';

  const animNames = Object.keys(animationClips);
  if (animNames.length) {
    for (const name of animNames) {
      const btn = document.createElement('button');
      btn.className    = 'dbg-btn';
      btn.textContent  = name;
      btn.id           = `dbg-anim-${name}`;
      btn.onclick      = () => onPlayAnimation(name);
      animBtns.appendChild(btn);
    }

    // Tombol "Uji Beruntun" – memicu urutan animasi cepat
    const btnSeq = document.createElement('button');
    btnSeq.className   = 'dbg-btn dbg-btn-special';
    btnSeq.textContent = '🔁 Uji Beruntun';
    btnSeq.id          = 'dbg-btn-sequence';
    btnSeq.onclick     = () => runSequenceTest(animNames, onPlayAnimation, onSetEmotion);
    animBtns.appendChild(btnSeq);
  } else {
    animBtns.innerHTML = '<span style="font-size:12px;color:var(--muted)">Tidak ada animasi dimuat.</span>';
  }

  // ── Tombol emosi ──────────────────────────────────────────────────────────
  const emotionBtns = document.getElementById('emotion-btns');
  emotionBtns.innerHTML = '';
  const emotions = appConfig?.emotions ?? [];
  for (const em of emotions) {
    const btn = document.createElement('button');
    btn.className   = 'dbg-btn';
    btn.textContent = em;
    btn.id          = `dbg-em-${em}`;
    btn.onclick     = () => onSetEmotion(em);
    emotionBtns.appendChild(btn);
  }

  // ── Animasi hilang ────────────────────────────────────────────────────────
  const missing        = appConfig?.missing_animations ?? [];
  const missingSection = document.getElementById('missing-anim-section');
  if (missing.length) {
    missingSection.style.display = '';
    document.getElementById('missing-anim-list').textContent = missing.join(', ');
  }

  // ── Kontrol Slow-mo ───────────────────────────────────────────────────────
  const slowmoSection = document.getElementById('dbg-slowmo-section');
  if (slowmoSection) {
    const btnSlowmo = document.getElementById('dbg-btn-slowmo');
    if (btnSlowmo) {
      let slowActive = false;
      btnSlowmo.onclick = () => {
        slowActive = !slowActive;
        // Blender tersedia via closure dari main.js lewat window._setTimeScale
        if (window._setTimeScale) window._setTimeScale(slowActive ? 0.1 : 1.0);
        btnSlowmo.textContent = slowActive ? '▶ Kecepatan Normal' : '🐢 Slow-mo 0.1×';
        btnSlowmo.classList.toggle('dbg-btn-active', slowActive);
      };
    }
  }

  // ── HUD bobot animasi & ekspresi ──────────────────────────────────────────
  // Buat elemen HUD jika belum ada
  let hudEl = document.getElementById('dbg-weight-hud');
  if (!hudEl) {
    hudEl = document.createElement('div');
    hudEl.id        = 'dbg-weight-hud';
    hudEl.className = 'dbg-section dbg-hud';
    hudEl.innerHTML = `<h3>Bobot Animasi & Ekspresi</h3><pre id="dbg-weight-pre" style="font-size:10px;line-height:1.5;margin:0;overflow-x:auto;"></pre>`;
    document.getElementById('debug-panel-inner').appendChild(hudEl);
  }

  const preEl = document.getElementById('dbg-weight-pre');

  // Update HUD setiap 100ms
  if (debugHudInterval) clearInterval(debugHudInterval);
  debugHudInterval = setInterval(() => {
    if (!preEl) return;
    // Hanya update jika panel terbuka
    const panel = document.getElementById('debug-panel');
    if (!panel || panel.classList.contains('hidden')) return;

    // ── Update Statistik Render Three.js ─────────────────────────────────────
    if (getRenderStats) {
      const stats = getRenderStats();
      const elFps = document.getElementById('dbg-actual-fps');
      const elCalls = document.getElementById('dbg-draw-calls');
      const elTri = document.getElementById('dbg-triangles');
      const elPr = document.getElementById('dbg-pixel-ratio');
      const elTarget = document.getElementById('dbg-target-fps');
      const elStatus = document.getElementById('dbg-render-status');

      if (elFps) elFps.textContent = `${stats.fps} FPS`;
      if (elCalls) elCalls.textContent = `${stats.drawCalls} calls`;
      if (elTri) elTri.textContent = stats.triangles ? stats.triangles.toLocaleString() : '--';
      if (elPr) elPr.textContent = stats.pixelRatio ? stats.pixelRatio.toFixed(2) : '--';
      if (elTarget) elTarget.textContent = stats.targetFps ? `${stats.targetFps}` : 'Max';
      if (elStatus) {
        elStatus.textContent = stats.isPaused ? 'Dijeda (Tidak Fokus/Tersembunyi)' : 'Aktif';
        elStatus.style.color = stats.isPaused ? 'var(--warn)' : 'var(--success)';
      }
    }

    let lines = ['── Bobot Animasi ──'];
    if (getBlenderState) {
      const state = getBlenderState();
      const total = state.totalWeight ?? 0;
      const warn  = Math.abs(total - 1) > 0.01 ? ' ⚠ PERINGATAN!' : '';
      lines.push(`Aktif: ${state.active}`);
      lines.push(`Total: ${total.toFixed(4)}${warn}`);
      for (const [name, w] of Object.entries(state.weights ?? {})) {
        const bar = '█'.repeat(Math.round((w.effective ?? 0) * 20)).padEnd(20, '░');
        lines.push(`${name.padEnd(12)} ${bar} ${((w.effective ?? 0) * 100).toFixed(1)}%`);
      }
    }

    lines.push('');
    lines.push('── Ekspresi ──');
    if (getExprSnapshot) {
      const snap = getExprSnapshot();
      for (const [name, v] of Object.entries(snap)) {
        const bar = '█'.repeat(Math.round(v.current * 20)).padEnd(20, '░');
        const tgt = `→${(v.target * 100).toFixed(0).padStart(3)}%`;
        lines.push(`${name.padEnd(10)} ${bar} ${(v.current * 100).toFixed(1)}% ${tgt}`);
      }
    }

    preEl.textContent = lines.join('\n');
  }, 100);
}

/**
 * Uji beruntun: picu urutan animasi & emosi cepat untuk menguji transisi.
 * @param {string[]} animNames
 * @param {(name: string) => void} onPlayAnimation
 * @param {(em: string) => void} onSetEmotion
 */
async function runSequenceTest(animNames, onPlayAnimation, onSetEmotion) {
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  console.log('[UjiBeruntun] Mulai...');

  // Uji emosi bergantian cepat
  const emotions = ['happy', 'angry', 'sad', 'surprised', 'neutral'];
  for (const em of emotions) {
    console.log(`[UjiBeruntun] Emosi: ${em}`);
    onSetEmotion(em);
    await delay(600);
  }

  // Uji animasi berurutan
  const testAnims = animNames.slice(0, Math.min(3, animNames.length));
  for (const name of testAnims) {
    console.log(`[UjiBeruntun] Animasi: ${name}`);
    onPlayAnimation(name);
    await delay(1200); // interupsi di tengah animasi sebelumnya
  }

  // Uji animasi yang sama dua kali cepat (harus diabaikan jika masih aktif)
  if (testAnims.length > 0) {
    const first = testAnims[0];
    console.log(`[UjiBeruntun] Animasi sama 2x: ${first}`);
    onPlayAnimation(first);
    await delay(200);
    onPlayAnimation(first); // harus diabaikan
    await delay(1500);
  }

  console.log('[UjiBeruntun] Selesai.');
  showToast('✅ Uji beruntun selesai – periksa konsol untuk detail.');
}
