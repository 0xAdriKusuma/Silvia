/**
 * js/websocket.js - WebSocket Connection, Push-to-Talk & Line Playback Queue
 *
 * Perubahan push-to-talk:
 *  - Menangani state baru "idle" dari server: tampilkan "Mikrofon mati" di UI.
 *  - Tombol mic besar: Pointer Events (pointerdown/pointerup/pointercancel) untuk hold,
 *    click untuk toggle; hotkey dari /api/config.
 *  - Fail-safe: visibilitychange / blur memicu stop saat mode hold.
 *  - Pesan hint untuk: "terlalu singkat", "Tidak ada suara", "Silvia sedang berbicara".
 *  - Mode always: tombol disembunyikan.
 */

import { playAudioBuffer } from './audio.js';
import { setEmotion } from './expressions.js';
import { playAnimation } from './avatar.js';
import { setStatusUI, setSubtitle, showUserText, showToast, showMicHint, updatePerfStats } from './ui.js';

const WS_URL = `ws://${location.host}/ws`;
const EXPR_RETURN_DELAY_MS = 600; // ms setelah audio selesai baru balik neutral

let ws               = null;
let wsReady          = false;
let wsReconnectTimer = null;

// Konfigurasi listen mode dari server (diisi setelah /api/config)
let listenMode   = 'toggle';  // 'toggle' | 'hold' | 'always'
let listenHotkey = 'Space';   // nama KeyboardEvent.code

// State tombol mic saat ini
let micActive = false;        // true = sedang mendengarkan (tombol ditekan/aktif)
let holdPressTime = 0;        // waktu pointerdown untuk deteksi tekan terlalu singkat

const HOLD_MIN_MS = 300;      // kurang dari ini di mode hold → diabaikan

const lineQueue    = [];
let isPlayingLine  = false;
let returnNeutralTimer = null;

// ── Inisialisasi mic button (dipanggil dari main.js setelah config diambil) ─

export function initMicButton(config) {
  listenMode   = (config.listen_mode   ?? 'toggle').toLowerCase();
  listenHotkey = config.listen_hotkey  ?? 'Space';

  const wrap   = document.getElementById('mic-btn-wrap');
  const btn    = document.getElementById('btn-mic');
  if (!wrap || !btn) return;

  // Mode always: sembunyikan tombol
  if (listenMode === 'always') {
    wrap.classList.add('mode-always');
    return;
  }

  // Update tooltip dengan hotkey
  btn.title = listenMode === 'hold'
    ? `Tahan untuk bicara (${listenHotkey})`
    : `Klik untuk bicara (${listenHotkey})`;

  // Tampilkan petunjuk hotkey di bawah tombol
  const hint = document.getElementById('mic-hint');
  if (hint) hint.textContent = listenHotkey;

  if (listenMode === 'hold') {
    // ── Mode hold: pointerdown = start, pointerup/cancel = stop ───────────
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      btn.setPointerCapture(e.pointerId);
      holdPressTime = Date.now();
      _startListening();
    });
    btn.addEventListener('pointerup',     _holdRelease);
    btn.addEventListener('pointercancel', _holdRelease);

    // Fail-safe: tab tersembunyi atau blur saat hold
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && micActive) _holdRelease();
    });
    window.addEventListener('blur', () => {
      if (micActive) _holdRelease();
    });

  } else {
    // ── Mode toggle: click bergantian start/cancel ─────────────────────────
    btn.addEventListener('click', () => {
      if (micActive) {
        _cancelListening();
      } else {
        _startListening();
      }
    });
  }

  // ── Hotkey (Space atau konfigurasi) ───────────────────────────────────────
  window.addEventListener('keydown', (e) => {
    // Abaikan bila fokus ada di kolom teks / input
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
    // Abaikan key repeat
    if (e.repeat) return;

    const code = e.code; // gunakan e.code agar layout-agnostic
    // Cocokkan dengan listenHotkey (bisa "Space", "KeyQ", "F1", dll.)
    if (code !== listenHotkey && e.key !== listenHotkey) return;

    e.preventDefault();

    if (listenMode === 'hold') {
      holdPressTime = Date.now();
      _startListening();
    } else {
      if (micActive) _cancelListening(); else _startListening();
    }
  });

  window.addEventListener('keyup', (e) => {
    if (listenMode !== 'hold') return;
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
    const code = e.code;
    if (code !== listenHotkey && e.key !== listenHotkey) return;
    _holdRelease();
  });
}

// ── Aksi tombol mic ──────────────────────────────────────────────────────────

function _startListening() {
  if (micActive) return;
  sendWS({ type: 'listen', action: 'start' });
  // UI akan diperbarui saat server mengirim status:listening
}

function _holdRelease() {
  if (!micActive) return;
  const held = Date.now() - holdPressTime;
  if (held < HOLD_MIN_MS) {
    // Tekan terlalu singkat: batal dan beri petunjuk
    sendWS({ type: 'listen', action: 'cancel' });
    showMicHint('Tahan lebih lama (' + HOLD_MIN_MS + 'ms)', { warn: true });
    return;
  }
  sendWS({ type: 'listen', action: 'stop' });
  // UI akan diperbarui saat server mengirim status:transcribing
}

function _cancelListening() {
  sendWS({ type: 'listen', action: 'cancel' });
  // UI akan diperbarui saat server mengirim status:idle
}

// ── Perbarui tombol mic berdasarkan state ────────────────────────────────────

function _updateMicButton(state) {
  const btn = document.getElementById('btn-mic');
  if (!btn || listenMode === 'always') return;

  const isListening = state === 'listening';
  const isBusy      = ['transcribing', 'thinking', 'speaking'].includes(state);

  micActive = isListening;
  btn.setAttribute('aria-pressed', isListening ? 'true' : 'false');
  btn.disabled = isBusy;  // nonaktif saat busy (tidak bisa klik)

  if (isBusy) {
    btn.title = 'Silvia sedang berbicara...';
  } else if (listenMode === 'hold') {
    btn.title = `Tahan untuk bicara (${listenHotkey})`;
  } else {
    btn.title = isListening
      ? `Klik untuk batal (${listenHotkey})`
      : `Klik untuk bicara (${listenHotkey})`;
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

export function connectWS() {
  if (ws && ws.readyState < 2) ws.close();
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsReady = true;
    console.log('[WS] Terhubung');
    // Tampilkan idle sampai server mengirim state
    setStatusUI('idle');
  };

  ws.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    handleWSMessage(msg);
  };

  ws.onerror = (e) => console.warn('[WS] Error:', e);

  ws.onclose = () => {
    wsReady = false;
    micActive = false;
    setStatusUI('disconnected');
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWS, 3000);
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'status': {
      setStatusUI(msg.state);
      _updateMicButton(msg.state);

      // Petunjuk khusus berdasarkan hint dari server
      if (msg.hint === 'timeout') {
        showMicHint('Tidak ada suara', { warn: true });
      } else if (msg.hint === 'cancelled') {
        showMicHint('Dibatalkan');
      } else if (msg.hint === 'busy') {
        showMicHint('Silvia sedang berbicara', { warn: true });
      }
      break;
    }
    case 'user_text':
      showUserText(msg.text);
      break;
    case 'line':
      lineQueue.push(msg);
      processLineQueue();
      break;
    case 'turn_end':
      lineQueue.push({ type: 'turn_end' });
      processLineQueue();
      break;
    case 'error':
      showToast(msg.message);
      break;
    case 'stats':
      updatePerfStats(msg);
      break;
  }
}

async function processLineQueue() {
  if (isPlayingLine) return;
  if (!lineQueue.length) return;
  isPlayingLine = true;

  while (lineQueue.length > 0) {
    const item = lineQueue.shift();

    if (item.type === 'turn_end') {
      // Batalkan timer emosi lama sebelum mengatur yang baru
      clearTimeout(returnNeutralTimer);

      // Kembalikan ke neutral setelah delay singkat
      returnNeutralTimer = setTimeout(() => {
        setEmotion('neutral');
        // CATATAN: TIDAK memanggil returnToIdle() – AnimationBlender menangani ini otomatis
      }, EXPR_RETURN_DELAY_MS);

      sendWS({ type: 'playback_done' });
      break;
    }

    if (item.type !== 'line') continue;

    if (item.continuation) {
      // Potongan lanjutan: hanya putar audio, tidak memicu ulang emosi/animasi/subtitle
      if (item.audio) {
        const binStr = atob(item.audio);
        const buf    = new ArrayBuffer(binStr.length);
        const view   = new Uint8Array(buf);
        for (let i = 0; i < binStr.length; i++) view[i] = binStr.charCodeAt(i);
        await playAudioBuffer(buf);
      }
      continue;
    }

    // Potongan pertama: batalkan timer return-neutral dari baris sebelumnya
    clearTimeout(returnNeutralTimer);
    returnNeutralTimer = null;

    // 1. Set emosi TEPAT saat baris mulai (sebelum audio)
    setEmotion(item.emotion);

    // 2. Picu animasi (jika ada)
    if (item.animation) {
      playAnimation(item.animation);
    }

    // 3. Update subtitle
    setSubtitle(item.jp, item.id);
    setStatusUI('speaking');

    // 4. Putar audio dan tunggu selesai
    if (item.audio) {
      const binStr = atob(item.audio);
      const buf    = new ArrayBuffer(binStr.length);
      const view   = new Uint8Array(buf);
      for (let i = 0; i < binStr.length; i++) view[i] = binStr.charCodeAt(i);
      await playAudioBuffer(buf);
    }
  }

  isPlayingLine = false;
  processLineQueue();
}

export function sendWS(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}
