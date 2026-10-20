/**
 * js/websocket.js - WebSocket Connection & Line Playback Queue
 */

import { playAudioBuffer } from './audio.js';
import { setEmotion } from './expressions.js';
import { playAnimation, returnToIdle } from './avatar.js';
import { setStatusUI, setSubtitle, showUserText, showToast, updatePerfStats } from './ui.js';

const WS_URL = `ws://${location.host}/ws`;
const EXPR_RETURN_DELAY = 0.6; // detik setelah audio selesai baru balik neutral

let ws = null;
let wsReady = false;
let wsReconnectTimer = null;

const lineQueue = [];
let isPlayingLine = false;
let returnNeutralTimer = null;

export function connectWS() {
  if (ws && ws.readyState < 2) ws.close();
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsReady = true;
    console.log('[WS] Terhubung');
    setStatusUI('listening');
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
    setStatusUI('disconnected');
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWS, 3000);
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'status':
      setStatusUI(msg.state);
      break;
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
      clearTimeout(returnNeutralTimer);
      returnNeutralTimer = setTimeout(() => {
        setEmotion('neutral');
        returnToIdle();
      }, EXPR_RETURN_DELAY * 1000);

      sendWS({ type: 'playback_done' });
      break;
    }

    if (item.type !== 'line') continue;

    // 1. Set emosi
    setEmotion(item.emotion);
    clearTimeout(returnNeutralTimer);

    // 2. Picu animasi
    if (item.animation) {
      playAnimation(item.animation);
    }

    // 3. Update subtitle
    setSubtitle(item.jp, item.id);
    setStatusUI('speaking');

    // 4. Putar audio
    if (item.audio) {
      const binStr = atob(item.audio);
      const buf = new ArrayBuffer(binStr.length);
      const view = new Uint8Array(buf);
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
