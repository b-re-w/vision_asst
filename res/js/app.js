/**
 * Vision Assistant — Web Client
 *
 * Protocol (JSON over WebSocket /ws/web):
 *   TX: { type:"audio", data:"<base64 pcm 16kHz 16bit mono>" }
 *       { type:"video", data:"<base64 jpeg>" }
 *   RX: { type:"audio",      data:"<base64 pcm 24kHz 16bit mono>" }
 *       { type:"transcript", role:"input"|"output", text:"..." }
 *       { type:"interrupted" }
 */

'use strict';

// ─── DOM refs ────────────────────────────────────────────────────────────────
const video          = document.getElementById('video');
const camPlaceholder = document.getElementById('cam-placeholder');
const recDot         = document.getElementById('rec-dot');
const statusDot      = document.getElementById('status-dot');
const messages       = document.getElementById('messages');
const btnToggle      = document.getElementById('btn-toggle');
const micRing        = document.getElementById('mic-ring');
const micBarEls      = document.querySelectorAll('#mic-bars span');

// Touch devices (phone WebView) get the lightweight rendering path. We detect via
// maxTouchPoints — NOT a (pointer: coarse) media query, which is false on phones whose
// primary input is fine (e.g. Samsung S-Pen), silently disabling every mobile rule.
const IS_TOUCH = (navigator.maxTouchPoints || 0) > 0 || 'ontouchstart' in window;
document.documentElement.classList.toggle('mobile', IS_TOUCH);

// ─── Camera color extraction ──────────────────────────────────────────────────
// Tiny canvas — samples average color from camera feed → drives CSS ambient light
const _colorCvs = document.createElement('canvas');
_colorCvs.width  = 16;
_colorCvs.height = 12;
const _colorCtx = _colorCvs.getContext('2d', { willReadFrequently: true });

function startColorExtraction() {
  let timer = null;

  function extract() {
    try {
      if (video.readyState >= 2) {
        _colorCtx.drawImage(video, 0, 0, 16, 12);
        const d = _colorCtx.getImageData(0, 0, 16, 12).data;
        let r = 0, g = 0, b = 0;
        const n = d.length / 4;
        for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i+1]; b += d[i+2]; }
        r = Math.round(r / n);
        g = Math.round(g / n);
        b = Math.round(b / n);

        // Boost saturation so orbs are visible even in grey/dark scenes
        const avg = (r + g + b) / 3;
        const boost = 2.2;
        r = Math.min(255, Math.round(avg + (r - avg) * boost));
        g = Math.min(255, Math.round(avg + (g - avg) * boost));
        b = Math.min(255, Math.round(avg + (b - avg) * boost));
        // Ensure minimum brightness so orbs are never invisible
        const minBrightness = 60;
        r = Math.max(minBrightness, r);
        g = Math.max(minBrightness, g);
        b = Math.max(minBrightness, b);

        // Primary orb — dominant camera color
        document.documentElement.style.setProperty('--cam-r', r);
        document.documentElement.style.setProperty('--cam-g', g);
        document.documentElement.style.setProperty('--cam-b', b);
        // Secondary orb — hue-rotated variant (swap channels)
        document.documentElement.style.setProperty('--cam-r2', Math.min(255, Math.round(b * 0.9)));
        document.documentElement.style.setProperty('--cam-g2', Math.min(255, Math.round(r * 0.7 + 30)));
        document.documentElement.style.setProperty('--cam-b2', Math.min(255, Math.round(g * 1.1 + 40)));
      }
    } catch (_) { /* cross-origin or video not ready */ }
    timer = setTimeout(extract, 600);
  }

  timer = setTimeout(extract, 800); // slight delay to let video stabilize
  return () => clearTimeout(timer); // returns a stop function
}

function stopColorExtraction() {
  if (state.stopColorExtraction) {
    state.stopColorExtraction();
    state.stopColorExtraction = null;
  }
  // Reset to CSS @property initial values (handled automatically)
  document.documentElement.style.removeProperty('--cam-r');
  document.documentElement.style.removeProperty('--cam-g');
  document.documentElement.style.removeProperty('--cam-b');
  document.documentElement.style.removeProperty('--cam-r2');
  document.documentElement.style.removeProperty('--cam-g2');
  document.documentElement.style.removeProperty('--cam-b2');
}

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  ws:               null,
  session:          null,   // Gemini Live session
  connected:        false,  // true while the Live session is open
  token:            null,   // ephemeral auth token
  audioCtx:         null,
  micStream:        null,
  videoStream:      null,
  workletNode:      null,   // AudioWorkletNode capturing mic PCM
  workletReady:     false,  // true once the worklet module is added to the context
  analyser:         null,
  micAnimId:        null,
  camInterval:      null,
  nextPlayTime:     0,
  currentUserMsg:   null,   // active user message element
  currentModelMsg:  null,   // active model message element
  modelMsgText:        '',     // accumulated model transcript so far
  manualDisconnect:    false,  // true only when user explicitly disconnects
  stopColorExtraction: null,   // cleanup fn returned by startColorExtraction()
  isVideoMode:         false,
  useMic:              false,
  mediaElementSource:  null,
  micSource:           null,
};

const BAR_COUNT = 12;

// ─── Utilities ───────────────────────────────────────────────────────────────
function bufToBase64(ab) {
  const bytes = new Uint8Array(ab);
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

function base64ToInt16(b64) {
  const binary = atob(b64);
  const buf    = new ArrayBuffer(binary.length);
  const view   = new Uint8Array(buf);
  for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
  return new Int16Array(buf);
}

// ─── Gemini Live (direct) ───────────────────────────────────────────────────────
// We connect straight to the Gemini Live API using the ephemeral token, replacing
// the old relay WebSocket. The token locks the model + config (system prompt, audio,
// voice) server-side, so the client cannot change them.
const GEMINI_MODEL = 'gemini-3.1-flash-live-preview';
const GENAI_SDK_URL = 'https://cdn.jsdelivr.net/npm/@google/genai@1/+esm';

async function geminiConnect() {
  if (!state.token) {
    showToast('토큰이 없어 연결할 수 없습니다', 'error');
    onDisconnected();
    return;
  }
  try {
    const { GoogleGenAI, Modality } = await import(GENAI_SDK_URL);
    const ai = new GoogleGenAI({
      apiKey: state.token,
      httpOptions: { apiVersion: 'v1alpha' },
    });
    state.session = await ai.live.connect({
      model: GEMINI_MODEL,
      config: {
        responseModalities: [Modality.AUDIO],
        temperature: 0.3,
        inputAudioTranscription: {},
        outputAudioTranscription: {},
      },
      callbacks: {
        onopen: onConnected,
        onmessage: onServerMessage,
        onerror: (e) => console.error('Gemini Live error:', e),
        onclose: (e) => { console.warn('Gemini Live closed:', e?.reason || ''); onDisconnected(); },
      },
    });
  } catch (err) {
    console.error('Gemini connect failed:', err);
    showToast('Gemini 연결 실패', 'error');
    onDisconnected();
  }
}

function onConnected() {
  state.connected = true;
  statusDot.classList.add('connected');
  btnToggle.textContent = 'Disconnect';
  btnToggle.classList.add('live');
  btnToggle.disabled = false;

  startCameraCapture();

  recDot.classList.add('active');
  micRing.classList.add('active');
}

function onDisconnected() {
  state.connected = false;
  state.session = null;
  statusDot.classList.remove('connected');
  btnToggle.classList.remove('live');
  btnToggle.disabled = false;
  teardown();

  if (state.manualDisconnect) {
    // User explicitly disconnected — stay disconnected
    state.manualDisconnect = false;
    btnToggle.textContent = 'Connect';
  } else {
    // Unexpected close (network hiccup, session expiry) — auto-reconnect
    btnToggle.textContent = 'Reconnecting…';
    btnToggle.disabled = true;
    setTimeout(async () => {
      if (!isWsOpen()) {
        // The ephemeral token is single-use, so mint a fresh one per session.
        state.token = await acquireToken();
        await setupCamera();
        await setupMic();
        geminiConnect();
      }
    }, 3000);
  }
}

function onServerMessage(message) {
  const content = message.serverContent;
  if (!content) return;

  if (content.modelTurn?.parts) {
    for (const part of content.modelTurn.parts) {
      if (part.inlineData?.data) {
        ensureModelMsg();
        playAudio(part.inlineData.data);
        setWaveformLive(state.currentModelMsg, true);
      }
    }
  }
  if (content.outputTranscription?.text) {
    ensureModelMsg();
    setTranscript(state.currentModelMsg, content.outputTranscription.text, true);
  }
  if (content.inputTranscription?.text) {
    ensureUserMsg();
    setTranscript(state.currentUserMsg, content.inputTranscription.text, false);
    sealUserMsg();
  }
  if (content.interrupted) {
    sealModelMsg();
  }
}

// Close the Live session. onclose → onDisconnected handles UI/reconnect.
function disconnect() {
  try { state.session?.close(); } catch (_) { /* already closing */ }
  state.connected = false;
}

// ─── Camera ──────────────────────────────────────────────────────────────────
async function setupCamera() {
  try {
    const params = new URLSearchParams(window.location.search);
    const videoSrc = params.get('video');
    const useMic = params.get('mic') === 'true'; // '?video=...&mic=true'

    if (videoSrc) {
      state.isVideoMode = true;
      state.useMic = useMic;
      // Use provided video instead of camera
      video.src = videoSrc;
      video.loop = false;
      video.muted = false; // Always hear the video
      video.play().catch(e => console.warn('Video play error:', e));
      
      video.onended = () => {
        if (isWsOpen()) {
          state.manualDisconnect = true;
          disconnect();
        }
      };
      
      // Simulate video stream for the capture loop
      state.videoStream = true; 
    } else {
      state.isVideoMode = false;
      // Normal camera setup
      state.videoStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, facingMode: 'environment' },
      });
      video.srcObject = state.videoStream;
    }
    
    camPlaceholder.style.display = 'none';
    // Begin sampling camera pixels → update CSS ambient color vars.
    // Skipped on touch devices — re-blurring the orbs every frame is too costly there.
    if (!IS_TOUCH) {
      state.stopColorExtraction = startColorExtraction();
    }
  } catch (err) {
    console.warn('Camera unavailable:', err);
  }
}

function startCameraCapture() {
  const canvas = document.createElement('canvas');
  canvas.width  = 320;
  canvas.height = 240;
  const ctx2d   = canvas.getContext('2d');

  state.camInterval = setInterval(() => {
    if (!isWsOpen() || !state.videoStream) return;
    ctx2d.drawImage(video, 0, 0, 320, 240);
    canvas.toBlob((blob) => {
      if (!blob) return;
      blob.arrayBuffer().then((buf) => {
        send({ type: 'video', data: bufToBase64(buf) });
      });
    }, 'image/jpeg', 0.72);
  }, 200); // 5 fps
}

// ─── Microphone ───────────────────────────────────────────────────────────────
async function setupMic() {
  if (!state.audioCtx) {
    state.audioCtx = new AudioContext();
  } else if (state.audioCtx.state === 'suspended') {
    state.audioCtx.resume();
  }
  const mixer = state.audioCtx.createGain();

  if (state.isVideoMode) {
    // In video mode, route the video's audio track to both speakers and mixer
    if (!state.mediaElementSource) {
      state.mediaElementSource = state.audioCtx.createMediaElementSource(video);
    }
    const videoSource = state.mediaElementSource;
    videoSource.connect(state.audioCtx.destination);
    videoSource.connect(mixer);
  }
  
  if (!state.isVideoMode || state.useMic) {
    try {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      state.micSource = state.audioCtx.createMediaStreamSource(state.micStream);
      state.micSource.connect(mixer);
    } catch (err) {
      console.warn('Microphone unavailable:', err);
      // If we're strictly relying on mic, abort. In video mode, keep going.
      if (!state.isVideoMode) return;
    }
  }

  // Analyser for mic-bar visualization
  state.analyser        = state.audioCtx.createAnalyser();
  state.analyser.fftSize = 128;
  mixer.connect(state.analyser);

  // AudioWorklet — downsample to 16 kHz + Int16 conversion on the audio thread,
  // off the main/UI thread (replaces the deprecated ScriptProcessorNode that janked).
  try {
    if (!state.workletReady) {
      await state.audioCtx.audioWorklet.addModule('/res/js/pcm-worklet.js');
      state.workletReady = true;
    }
    const node = new AudioWorkletNode(state.audioCtx, 'pcm-capture');
    node.port.onmessage = (e) => {
      if (!isWsOpen()) return;
      const pcm = new Int16Array(e.data);
      send({ type: 'audio', data: bufToBase64(pcm.buffer) });
      updateUserWaveform(pcm);
    };
    mixer.connect(node);
    node.connect(state.audioCtx.destination); // outputs silence; keeps the node pulled
    state.workletNode = node;
  } catch (err) {
    console.error('AudioWorklet init failed:', err);
  }

  animateMicBars();
  ensureUserMsg();
}

// ─── Audio Playback ───────────────────────────────────────────────────────────
function playAudio(b64) {
  if (!state.audioCtx) return;

  const int16  = base64ToInt16(b64);
  const buffer = state.audioCtx.createBuffer(1, int16.length, 24000);
  const ch     = buffer.getChannelData(0);
  for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 32768;

  const src   = state.audioCtx.createBufferSource();
  src.buffer  = buffer;
  src.connect(state.audioCtx.destination);

  const start = Math.max(state.nextPlayTime, state.audioCtx.currentTime + 0.02);
  src.start(start);
  state.nextPlayTime = start + buffer.duration;

  // When the chunk finishes and no more audio is queued, seal the bubble
  src.addEventListener('ended', () => {
    setTimeout(() => {
      if (state.audioCtx && state.nextPlayTime <= state.audioCtx.currentTime + 0.15) {
        sealModelMsg();
      }
    }, 400);
  });
}

// ─── Chat messages ────────────────────────────────────────────────────────────
function createMessage(role) {
  const el = document.createElement('div');
  el.className = `message ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'U' : '✦';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const waveform = document.createElement('div');
  waveform.className = 'waveform live';
  for (let i = 0; i < BAR_COUNT; i++) {
    const span = document.createElement('span');
    waveform.appendChild(span);
  }

  const transcript = document.createElement('p');
  transcript.className = 'transcript';
  transcript.style.display = 'none';

  bubble.appendChild(waveform);
  bubble.appendChild(transcript);
  el.appendChild(avatar);
  el.appendChild(bubble);
  messages.appendChild(el);

  scrollToBottom();
  return el;
}

function ensureUserMsg() {
  if (!state.currentUserMsg) state.currentUserMsg = createMessage('user');
}

function ensureModelMsg() {
  if (!state.currentModelMsg) state.currentModelMsg = createMessage('model');
}

function sealUserMsg() {
  if (!state.currentUserMsg) return;
  setWaveformLive(state.currentUserMsg, false);
  state.currentUserMsg = null;
}

function sealModelMsg() {
  if (!state.currentModelMsg) return;
  setWaveformLive(state.currentModelMsg, false);
  state.currentModelMsg = null;
  state.modelMsgText    = '';  // reset accumulator for next response
}

function setWaveformLive(msgEl, live) {
  if (!msgEl) return;
  msgEl.querySelector('.waveform')?.classList.toggle('live', live);
}

function setTranscript(msgEl, text, isModel = false) {
  if (!msgEl) return;
  const t = msgEl.querySelector('.transcript');
  if (!t) return;
  t.style.display = 'block';

  if (!isModel) {
    // User transcript: simple set (arrives once, fully formed)
    t.textContent = text;
    return;
  }

  // Model transcript: Gemini sends delta chunks — always append incoming text
  const toAdd = text;
  if (!toAdd) return;

  state.modelMsgText += toAdd;

  // Append each new character wrapped in an animated <span>
  toAdd.split('').forEach((ch, i) => {
    const span = document.createElement('span');
    span.className = 'char-reveal';
    // 30ms per character, capped at 450ms so long chunks don't drag
    span.style.animationDelay = `${Math.min(i * 30, 450)}ms`;
    span.textContent = ch;
    t.appendChild(span);
  });

  scrollToBottom();
}

// Update user bubble waveform bars from microphone amplitude data
function updateUserWaveform(pcm) {
  if (!state.currentUserMsg) return;
  const bars = state.currentUserMsg.querySelectorAll('.waveform span');
  const step = Math.floor(pcm.length / bars.length) || 1;
  bars.forEach((bar, i) => {
    const amp = Math.abs((pcm[i * step] ?? 0) / 32768); // Int16 → [0,1]
    bar.style.height = `${Math.max(3, Math.min(20, amp * 80))}px`;
  });
}

// ─── Mic-ring bar visualization (AnalyserNode driven) ─────────────────────────
function animateMicBars() {
  if (!state.analyser) return;
  const data = new Uint8Array(state.analyser.frequencyBinCount);

  function frame() {
    state.micAnimId = requestAnimationFrame(frame);
    state.analyser.getByteFrequencyData(data);
    const step = Math.floor(data.length / micBarEls.length) || 1;
    micBarEls.forEach((bar, i) => {
      const v = data[i * step] / 255;
      bar.style.height = `${Math.max(3, v * 17)}px`;
    });
  }
  frame();
}

// ─── Scroll & blur ────────────────────────────────────────────────────────────
function scrollToBottom() {
  requestAnimationFrame(() => {
    messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
    applyScrollBlur();
  });
}

function applyScrollBlur() {
  // Per-message blur filters spawn composited layers that corrupt on mobile GPUs.
  if (IS_TOUCH) return;
  const allMsgs = messages.querySelectorAll('.message');

  // No scroll has happened yet — clear any residual blur and exit
  if (messages.scrollTop < 10) {
    allMsgs.forEach((msg) => { msg.style.opacity = ''; msg.style.filter = ''; });
    return;
  }

  const containerTop = messages.getBoundingClientRect().top;
  allMsgs.forEach((msg) => {
    const rect       = msg.getBoundingClientRect();
    const distBottom = rect.bottom - containerTop; // bottom edge distance from container top
    const fadeZone   = 90;
    if (distBottom < fadeZone && distBottom > 0) {
      const t = Math.max(0, distBottom / fadeZone);
      msg.style.opacity = t;
      msg.style.filter  = `blur(${(1 - t) * 5}px)`;
    } else {
      msg.style.opacity = '';
      msg.style.filter  = '';
    }
  });
}

messages.addEventListener('scroll', applyScrollBlur);

// ─── Teardown ─────────────────────────────────────────────────────────────────
function teardown() {
  clearInterval(state.camInterval);
  state.camInterval = null;

  cancelAnimationFrame(state.micAnimId);
  state.micAnimId = null;

  state.micStream?.getTracks().forEach((t) => t.stop());
  state.micStream = null;

  if (state.videoStream && typeof state.videoStream.getTracks === 'function') {
    state.videoStream.getTracks().forEach((t) => t.stop());
  }
  state.videoStream = null;

  state.workletNode?.port.close();
  state.workletNode?.disconnect();
  state.workletNode = null;

  if (state.mediaElementSource) {
    state.mediaElementSource.disconnect();
  }
  if (state.micSource) {
    state.micSource.disconnect();
    state.micSource = null;
  }
  
  // Do NOT close audioCtx because createMediaElementSource can only be called once per video element.
  // We just reset scheduling.
  state.nextPlayTime = 0;

  state.currentUserMsg  = null;
  state.currentModelMsg = null;

  video.srcObject = null;
  video.removeAttribute('src');
  camPlaceholder.style.display = '';
  recDot.classList.remove('active');
  micRing.classList.remove('active');
  micBarEls.forEach((b) => (b.style.height = ''));
  stopColorExtraction();   // clear color extraction loop and CSS vars
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function isWsOpen() {
  return state.connected;
}

function send(obj) {
  const s = state.session;
  if (!s || !state.connected) return;
  if (obj.type === 'audio') {
    s.sendRealtimeInput({ audio: { data: obj.data, mimeType: 'audio/pcm;rate=16000' } });
  } else if (obj.type === 'video') {
    s.sendRealtimeInput({ video: { data: obj.data, mimeType: 'image/jpeg' } });
  }
}

// ─── Ephemeral token ────────────────────────────────────────────────────────────
// Primary issuer; if unreachable we fall back to a Python test server running on the
// local machine (so dev sessions don't need to reach cuws).
const TOKEN_SERVER = 'http://cuws.duckdns.org:8000';
const FALLBACK_TOKEN_SERVER = 'http://localhost:8000';

function showToast(message, type = 'info') {
  const host = document.getElementById('toast-host');
  if (!host) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
  }, 3200);
}

async function fetchToken(url, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { token } = await res.json();
    if (!token) throw new Error('empty token');
    return token;
  } finally {
    clearTimeout(timer);
  }
}

// Try the main server first; if it doesn't respond, fall back to our own origin.
// Returns the ephemeral token, or null if both fail.
async function acquireToken() {
  console.info(`[token] requesting from main server ${TOKEN_SERVER}/token`);
  try {
    const token = await fetchToken(`${TOKEN_SERVER}/token`, 4000);
    console.info('[token] acquired from main server');
    showToast('토큰 발급 성공', 'success');
    return token;
  } catch (err) {
    console.warn(`[token] main server unreachable (${err.message}); trying fallback ${FALLBACK_TOKEN_SERVER}/token`);
    showToast('메인 서버 접근 실패 · 폴백 시도', 'warn');
    try {
      const token = await fetchToken(`${FALLBACK_TOKEN_SERVER}/token`, 4000);
      console.info('[token] acquired from fallback server');
      showToast('토큰 발급 성공 (폴백)', 'success');
      return token;
    } catch (err2) {
      console.error(`[token] both issuers failed: ${err2.message}`);
      showToast('토큰 발급 실패', 'error');
      return null;
    }
  }
}

// ─── Button ───────────────────────────────────────────────────────────────────
btnToggle.addEventListener('click', async () => {
  if (isWsOpen()) {
    state.manualDisconnect = true;   // mark as intentional
    disconnect();
  } else {
    btnToggle.disabled = true;
    btnToggle.textContent = 'Connecting…';

    state.token = await acquireToken();

    // Run setup during user interaction to bypass autoplay policies
    await setupCamera();
    await setupMic();

    geminiConnect();
  }
});

// ─── Auto-connect on page load ────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('video')) {
    // Skip auto-connect in video mode to ensure we get a user click 
    // to bypass browser autoplay policies for unmuted audio.
    return;
  }
  btnToggle.disabled = true;
  btnToggle.textContent = 'Connecting…';

  state.token = await acquireToken();

  await setupCamera();
  await setupMic();
  geminiConnect();
});
