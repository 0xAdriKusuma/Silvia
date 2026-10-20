/**
 * js/ui.js - Antarmuka Pengguna, Subtitle, Status, Debug Panel & Monitor Performa
 */

const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const subtitleJp  = document.getElementById('subtitle-jp');
const subtitleId  = document.getElementById('subtitle-id');
const userTextEl  = document.getElementById('user-text');
const toast = document.getElementById('toast');

const perfWidget = document.getElementById('perf-monitor');
const btnTogglePerf = document.getElementById('btn-toggle-perf');
const perfToggleIcon = document.getElementById('perf-toggle-icon');
const perfCpuVal = document.getElementById('perf-cpu-val');
const perfCpuBar = document.getElementById('perf-cpu-bar');
const perfRamVal = document.getElementById('perf-ram-val');
const perfRamBar = document.getElementById('perf-ram-bar');
const perfGpuRow = document.getElementById('perf-gpu-row');
const perfGpuName = document.getElementById('perf-gpu-name');
const perfGpuVal = document.getElementById('perf-gpu-val');
const perfGpuBar = document.getElementById('perf-gpu-bar');
const perfVramRow = document.getElementById('perf-vram-row');
const perfVramVal = document.getElementById('perf-vram-val');
const perfVramBar = document.getElementById('perf-vram-bar');
const perfFpsVal = document.getElementById('perf-fps-val');
const perfTempBadge = document.getElementById('perf-temp-badge');
const perfTempVal = document.getElementById('perf-temp-val');

const STATUS_LABELS = {
  listening:    'Mendengarkan...',
  transcribing: 'Mentranskripsi...',
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

export function updateFps(fps) {
  if (perfFpsVal) perfFpsVal.textContent = fps;
}

function setBarColor(barElem, percent) {
  if (!barElem) return;
  barElem.classList.remove('warn', 'danger');
  if (percent >= 90) barElem.classList.add('danger');
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
    perfGpuRow.style.display = '';
    perfVramRow.style.display = '';

    if (stats.gpu.name) {
      const shortName = stats.gpu.name.replace(/NVIDIA\s+/i, '').replace(/Laptop GPU/i, 'Mobile');
      perfGpuName.textContent = shortName;
      perfGpuName.title = stats.gpu.name;
    }

    const gpuPct = Math.round(stats.gpu.load || 0);
    perfGpuVal.textContent = `${gpuPct}%`;
    perfGpuBar.style.width = `${Math.min(100, gpuPct)}%`;
    setBarColor(perfGpuBar, gpuPct);

    const vramUsed = Math.round(stats.gpu.vram_used_mb || 0);
    const vramTotal = Math.round(stats.gpu.vram_total_mb || 0);
    const vramPct = Math.round(stats.gpu.vram_percent || 0);
    perfVramVal.textContent = `${vramUsed} / ${vramTotal} MB (${vramPct}%)`;
    perfVramBar.style.width = `${Math.min(100, vramPct)}%`;
    setBarColor(perfVramBar, vramPct);

    if (stats.gpu.temp !== undefined && stats.gpu.temp !== null) {
      perfTempBadge.style.display = '';
      perfTempVal.textContent = `${Math.round(stats.gpu.temp)}°C`;
    }
  } else {
    perfGpuRow.style.display = 'none';
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

  // Toggle debug panel
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
  const mouthVal = document.getElementById('mouth-val');
  mouthSlider.oninput = (e) => {
    const val = Number(e.target.value) / 100;
    mouthVal.textContent = `${e.target.value}%`;
    if (onMouthSlider) onMouthSlider(val);
  };

  // Input teks
  const textInput = document.getElementById('text-input');
  const btnSend = document.getElementById('btn-send');
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

export function buildDebugPanel({ animationClips, appConfig, onPlayAnimation, onSetEmotion }) {
  const animBtns = document.getElementById('anim-btns');
  animBtns.innerHTML = '';
  for (const name of Object.keys(animationClips)) {
    const btn = document.createElement('button');
    btn.className = 'dbg-btn';
    btn.textContent = name;
    btn.onclick = () => onPlayAnimation(name);
    animBtns.appendChild(btn);
  }
  if (!animBtns.children.length) {
    animBtns.innerHTML = '<span style="font-size:12px;color:var(--muted)">Tidak ada animasi dimuat.</span>';
  }

  const emotionBtns = document.getElementById('emotion-btns');
  emotionBtns.innerHTML = '';
  const emotions = appConfig?.emotions ?? [];
  for (const em of emotions) {
    const btn = document.createElement('button');
    btn.className = 'dbg-btn';
    btn.textContent = em;
    btn.onclick = () => onSetEmotion(em);
    emotionBtns.appendChild(btn);
  }

  const missing = appConfig?.missing_animations ?? [];
  const missingSection = document.getElementById('missing-anim-section');
  if (missing.length) {
    missingSection.style.display = '';
    document.getElementById('missing-anim-list').textContent = missing.join(', ');
  }
}
